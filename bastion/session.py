
"""
PAM Bastion — session proxy with PTY, ttyrec, and sudo-password injection.
Uses only stdlib: pty, os, select, termios, tty, struct, time.

Flow:
  1. Allocate PTY
  2. Fork → child exec ssh
  3. Parent: multiplex stdin↔master_fd
  4. Watch output for sudo prompts → inject ephemeral password
  5. Write ttyrec frames to disk
"""
import os, sys, pty, select, termios, tty, struct, time, fcntl, signal
import subprocess

import json
import socket
import re

# ── Asciicast + UDP Live Streamer ─────────────────────────────────────────────
class SessionRecorder:
    """Writes Asciicast v2 format and broadcasts live data via UDP."""
    def __init__(self, path: str, session_uuid: str):
        self.session_uuid = session_uuid
        self.start_time = time.time()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._f = open(path, "w", encoding="utf-8")
        
        # Determine terminal size if possible, otherwise default
        width, height = 120, 30
        try:
            import fcntl, termios as _t
            winsz = fcntl.ioctl(sys.stdin.fileno(), _t.TIOCGWINSZ, b"\x00" * 8)
            h, w = struct.unpack("hhhh", winsz)[0:2]
            if w > 0 and h > 0:
                width, height = w, h
        except Exception:
            pass

        # Asciicast v2 header
        header = {
            "version": 2,
            "width": width,
            "height": height,
            "timestamp": int(self.start_time),
            "env": {"TERM": os.environ.get("TERM", "xterm-256color")}
        }
        self._f.write(json.dumps(header) + "\n")
        
        # UDP socket for live view
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.live_addr = ("127.0.0.1", 9001)

    def write(self, data: bytes):
        now = time.time() - self.start_time
        try:
            text = data.decode("utf-8", errors="replace")
            frame = [round(now, 4), "o", text]
            self._f.write(json.dumps(frame) + "\n")
            self._f.flush()
        except Exception:
            pass

        # Broadcast live to UDP Viewer Service: "UUID|RAW_BYTES"
        if self.session_uuid:
            try:
                packet = f"{self.session_uuid}|".encode("utf-8") + data
                self.udp_sock.sendto(packet, self.live_addr)
            except Exception:
                pass

    def close(self):
        try:
            self._f.close()
            self.udp_sock.close()
        except Exception:
            pass

# ── Sudo password setter (separate SSH connection before session) ──────────────
def set_ephemeral_sudo_password(host: str, port: int, bastion_key: str, password: str):
    """
    SSH to target as bastion (key auth) and set bastion user's password via chpasswd.
    Sudoers on target must grant NOPASSWD for chpasswd:
      bastion ALL=(root) NOPASSWD: /usr/sbin/chpasswd, /usr/bin/passwd
    NOTE: do NOT use 'sudo -S' here — -S reads sudo auth password from stdin,
    which conflicts with piping chpasswd data through stdin.
    NOPASSWD means sudo needs no password at all.
    """
    import subprocess
    # Escape single quotes in password for safe shell embedding
    safe_pass = password.replace("'", "'\"'\"'")
    # NO local sudo: we use setfacl -m g:pam_users:r on the bastion key instead.
    # On the REMOTE side, we use 'sudo -n' (non-interactive).
    # If NOPASSWD is set correctly in /etc/sudoers.d/bastion on the target,
    # it will work. If not, it will fail cleanly without consuming stdin.
    # Hash the password locally on the bastion using openssl
    try:
        hashed_pass = subprocess.check_output(["openssl", "passwd", "-6", password]).decode().strip()
    except Exception as e:
        raise RuntimeError(f"Failed to generate password hash locally: {e}")

    cmd = [
        "sudo", "ssh", "-i", bastion_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-p", str(port),
        f"bastion@{host}",
        f"sudo -n usermod -p '{hashed_pass}' bastion",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to set sudo password: {result.stderr.decode()}")


def clear_sudo_password(host: str, port: int, bastion_key: str):
    """
    Lock bastion account after session ends (best-effort).
    SECURITY: use 'usermod -p *' NOT 'passwd -d'.
      passwd -d  → empty password → 'su bastion' works WITHOUT password (hole!)
      usermod -p '*' → invalid hash → login impossible until PAM sets next ephemeral password
    """
    import subprocess
    cmd = [
        "sudo", "ssh", "-i", bastion_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-p", str(port),
        f"bastion@{host}",
        "sudo -n usermod -p '*' bastion",
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)  # best-effort


# ── Main session runner ────────────────────────────────────────────────────────
SUDO_PATTERNS = (b"[sudo] password", b"password:", b"password for")

def run_session(
    ssh_cmd: list[str],
    rec_path: str,
    session_uuid: str | None = None,
    sudo_password: str | None = None,
) -> tuple[int, str]:
    """
    Run ssh_cmd inside a PTY.
    - Records everything to rec_path (.cast) and UDP Live View
    - Injects sudo_password when prompted (if provided)
    - Captures heuristically reconstructed commands (keylogger) honoring ECHO.
    Returns (exit_code, command_log_string).
    """
    rec = SessionRecorder(rec_path, session_uuid or "")

    # Propagate SIGWINCH (terminal resize) to child
    child_pid = None
    def _sigwinch(sig, frame):
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    master_fd, slave_fd = pty.openpty()

    # Copy current terminal size to slave
    try:
        import fcntl, termios as _t
        winsz = fcntl.ioctl(sys.stdin.fileno(), _t.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(slave_fd, _t.TIOCSWINSZ, winsz)
    except Exception:
        pass

    pid = os.fork()
    if pid == 0:
        # ── child ─────────────────────────────────────────────────────────────
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        for fd in (0, 1, 2):
            os.dup2(slave_fd, fd)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(ssh_cmd[0], ssh_cmd)
        os._exit(127)

    # ── parent ─────────────────────────────────────────────────────────────────
    child_pid = pid
    os.close(slave_fd)
    signal.signal(signal.SIGWINCH, _sigwinch)

    # Put terminal in raw mode
    old_attrs = termios.tcgetattr(sys.stdin.fileno())
    tty.setraw(sys.stdin.fileno())

    pending_output = b""
    command_buffer = ""
    commands = []
    in_escape = False

    try:
        while True:
            rfds, _, _ = select.select([master_fd, sys.stdin], [], [], 0.05)

            if master_fd in rfds:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break

                rec.write(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

                # Sudo password injection
                if sudo_password:
                    pending_output = (pending_output + data)[-256:]
                    if any(p in pending_output.lower() for p in SUDO_PATTERNS):
                        os.write(master_fd, (sudo_password + "\n").encode())
                        pending_output = b""

            if sys.stdin in rfds:
                try:
                    data = os.read(sys.stdin.fileno(), 4096)
                except OSError:
                    break
                if not data:
                    break
                os.write(master_fd, data)

                # Capture typed commands
                for byte in data:
                    if in_escape:
                        if 64 <= byte <= 126 and byte != 91 and byte != 79:
                            in_escape = False
                        continue
                    
                    if byte == 27:
                        in_escape = True
                        continue
                        
                    if byte in (13, 10):
                        if command_buffer.strip():
                            commands.append(command_buffer.strip())
                        command_buffer = ""
                    elif byte in (127, 8):
                        command_buffer = command_buffer[:-1]
                    elif byte == 21:
                        command_buffer = ""
                    elif byte == 23:
                        command_buffer = command_buffer.rsplit(' ', 1)[0] if ' ' in command_buffer else ""
                    elif byte == 3:
                        command_buffer = ""
                    else:
                        try:
                            char = bytes([byte]).decode('utf-8')
                            if char.isprintable():
                                command_buffer += char
                        except Exception:
                            pass

    except OSError:
        pass
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)
        os.close(master_fd)
        rec.close()

    _, wstatus = os.waitpid(pid, 0)
    numbered_commands = [f"{i+1}. {cmd}" for i, cmd in enumerate(commands)]
    log_str = "\n".join(numbered_commands)
    
    # Debug: always write commands to a temp file so we can verify capture works
    try:
        debug_path = f"/tmp/pam_cmdlog_{session_uuid or 'unknown'}.txt"
        with open(debug_path, "w") as df:
            df.write(log_str if log_str else "(no commands captured)")
    except Exception:
        pass
    
    return os.WEXITSTATUS(wstatus), log_str


