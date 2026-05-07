
"""
PAM Bastion — session proxy with PTY, ttyrec, and sudo-password injection.
Uses only stdlib: pty, os, select, termios, tty, struct, time.

Flow:
  1. Allocate PTY
  2. Fork → child exec ssh
  3. Parent: multiplex stdin↔master_fd
  4. Watch output for sudo prompts → inject ephemeral password
  5. Write ttyrec frames to disk
  6. Idle timeout: if no activity for IDLE_TIMEOUT_SECONDS → disconnect
  7. On session end: rotate bastion user password to random (clear_sudo_password)
"""
import os, sys, pty, select, termios, tty, struct, time, fcntl, signal
import subprocess

import json
import socket
import re

IDLE_TIMEOUT_SECONDS = 30 * 60  # 30 minutes of inactivity → disconnect

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
    SSH to target as bastion (key auth) and set bastion user's password via usermod -p.
    Uses openssl passwd -6 to hash locally — avoids chpasswd PAM restrictions.

    Sudoers on target must grant (from bootstrap):
      bastion ALL=(root) NOPASSWD: /usr/sbin/usermod, /sbin/usermod
    """
    # Hash the password locally using openssl (avoids sending plaintext over stdin)
    try:
        hashed_pass = subprocess.check_output(
            ["openssl", "passwd", "-6", password],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception as e:
        raise RuntimeError(f"Failed to generate password hash locally: {e}")

    # Escape single quotes for safe shell embedding
    safe_hash = hashed_pass.replace("'", "'\"'\"'")

    # IMPORTANT: do NOT prefix with "sudo" locally — the BASTION_KEY is readable
    # by pam_users group via setfacl. We SSH as bastion, then sudo -n on the remote.
    cmd = [
        "ssh",
        "-i", bastion_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-p", str(port),
        f"bastion@{host}",
        f"sudo -n usermod -p '{safe_hash}' bastion",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode != 0:
        stderr = result.stderr.decode().strip()
        raise RuntimeError(
            f"Failed to set sudo password on {host}: {stderr}\n"
            f"Check: bastion ALL=(root) NOPASSWD: /usr/sbin/usermod in /etc/sudoers.d/bastion"
        )


def clear_sudo_password(host: str, port: int, bastion_key: str):
    """
    Rotate bastion account password to a new random value after session ends.

    SECURITY DESIGN:
      - We do NOT use passwd -d (empty password) — that allows su bastion without password!
      - We do NOT use usermod -p '*' — that locks completely, but we want the user
        to be required to enter a password when doing 'su bastion' directly (emergency).
      - We SET a NEW random password hash. This means:
        * su bastion (direct, emergency) → asks for password → user doesn't know it → BLOCKED
        * Next PAM session → PAM sets a fresh ephemeral password → sudo works again
    """
    import secrets as _sec
    random_pass = _sec.token_urlsafe(32)
    try:
        hashed = subprocess.check_output(
            ["openssl", "passwd", "-6", random_pass],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        # Fallback: lock the account (still better than nothing)
        hashed = "*"

    safe_hash = hashed.replace("'", "'\"'\"'")
    cmd = [
        "ssh",
        "-i", bastion_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-p", str(port),
        f"bastion@{host}",
        f"sudo -n usermod -p '{safe_hash}' bastion",
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)  # best-effort


def check_sudo_access(host: str, port: int, bastion_key: str) -> bool:
    """
    Check if bastion user can run sudo -n usermod on the target server.
    Returns True if NOPASSWD sudo is configured correctly.
    Used for diagnostics (pam_cli.py server check-sudo).
    """
    cmd = [
        "ssh",
        "-i", bastion_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-p", str(port),
        f"bastion@{host}",
        "sudo -n usermod --help",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=10)
    # sudo -n usermod --help returns 0 or 1 (usage), but NOT 1 with "sudo: ... password required"
    stderr = result.stderr.decode()
    if "sudo: " in stderr and "password" in stderr.lower():
        return False
    return True


# ── Main session runner ────────────────────────────────────────────────────────
SUDO_PATTERNS = (b"[sudo] password", b"password:", b"password for")

def run_session(
    ssh_cmd: list[str],
    rec_path: str,
    session_uuid: str | None = None,
    sudo_password: str | None = None,
    idle_timeout: int = IDLE_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """
    Run ssh_cmd inside a PTY.
    - Records everything to rec_path (.cast) and UDP Live View
    - Injects sudo_password when prompted (if provided)
    - Captures heuristically reconstructed commands (keylogger) honoring ECHO
    - Disconnects after idle_timeout seconds of no activity (default 30 min)
    Returns (exit_code, command_log_string).
    """
    rec = SessionRecorder(rec_path, session_uuid or "")

    # Propagate SIGWINCH (terminal resize) to child
    child_pid = None
    _force_kill = False  # set to True when SIGHUP received from admin kill command

    def _sigwinch(sig, frame):
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    def _sighup(sig, frame):
        """Received when admin runs 'pam_cli.py session kill'. Trigger graceful exit."""
        nonlocal _force_kill
        _force_kill = True

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
    signal.signal(signal.SIGHUP,  _sighup)   # admin force-kill hook

    # Put terminal in raw mode
    old_attrs = termios.tcgetattr(sys.stdin.fileno())
    tty.setraw(sys.stdin.fileno())

    pending_output = b""
    command_buffer = ""
    commands = []
    in_escape = False

    last_activity = time.time()
    idle_warned = False

    try:
        while True:
            rfds, _, _ = select.select([master_fd, sys.stdin], [], [], 1.0)

            now = time.time()
            idle_secs = now - last_activity

            # ── Force-kill by admin ────────────────────────────────────────────
            if _force_kill:
                msg = (
                    "\r\n\033[31m[bastion] ⛔ Session forcefully terminated by administrator.\033[0m\r\n"
                )
                try:
                    os.write(master_fd, msg.encode())
                except OSError:
                    pass
                sys.stdout.buffer.write(msg.encode())
                sys.stdout.buffer.flush()
                try:
                    os.kill(child_pid, signal.SIGHUP)
                except ProcessLookupError:
                    pass
                break

            # ── Idle timeout ───────────────────────────────────────────────────
            if idle_timeout > 0 and idle_secs >= idle_timeout:
                # Warn at 5-minute mark before disconnect
                msg = (
                    f"\r\n\033[33m[bastion] Session idle for {int(idle_secs // 60)} minutes. "
                    f"Disconnecting due to inactivity.\033[0m\r\n"
                )
                sys.stdout.buffer.write(msg.encode())
                sys.stdout.buffer.flush()
                try:
                    os.kill(child_pid, signal.SIGHUP)
                except ProcessLookupError:
                    pass
                break

            if master_fd in rfds:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break

                last_activity = now  # remote output counts as activity
                rec.write(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

                # Sudo password injection
                if sudo_password:
                    pending_output = (pending_output + data)[-512:]
                    low = pending_output.lower()
                    if any(p in low for p in SUDO_PATTERNS):
                        # Small delay to make sure the prompt has fully appeared
                        time.sleep(0.05)
                        os.write(master_fd, (sudo_password + "\n").encode())
                        pending_output = b""

            if sys.stdin in rfds:
                try:
                    data = os.read(sys.stdin.fileno(), 4096)
                except OSError:
                    break
                if not data:
                    break

                last_activity = now  # user keypress resets idle timer
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
