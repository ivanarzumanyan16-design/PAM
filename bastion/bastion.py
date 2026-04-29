#!/usr/bin/env python3
"""
PAM Bastion — main entry point.

Invoked via SSH authorized_keys command= restriction:
  command="python3 /opt/bastion/bastion.py",no-port-forwarding,...

SSH_ORIGINAL_COMMAND format:
  alice@prod-web-01          → connect as bastion@prod-web-01:22
  alice@prod-web-01:2222     → connect as bastion@prod-web-01:2222
  (empty)                    → show interactive server list

Flow:
  1. Parse SSH_ORIGINAL_COMMAND
  2. Resolve Linux user → Metax2 user object (by username)
  3. Prompt for TOTP → verify
  4. Check permission (user's groups × server)
  5. (if allow_sudo) set ephemeral sudo password on target
  6. Open ttyrec recording
  7. SSH proxy via PTY (with sudo injection)
  8. Close: update session record, clear sudo password, write audit log
"""
import os, sys, time, secrets, termios

sys.path.insert(0, os.path.dirname(__file__))

import metax_client as mx
import totp as totp_mod
import audit
from session import run_session, set_ephemeral_sudo_password, clear_sudo_password
from config import BASTION_KEY, RECORDINGS_DIR, M_TRUE


# ── Helpers ────────────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1):
    print(f"\r\n\033[31m[bastion] {msg}\033[0m\r\n", file=sys.stderr)
    sys.exit(code)

def banner():
    print("\r\n\033[1;36m╔══════════════════════════════╗\r\n"
          "║    PAM Bastion — Welcome     ║\r\n"
          "╚══════════════════════════════╝\033[0m\r\n")

def prompt(msg: str, echo: bool = True) -> str:
    """Read a line from stdin; suppress echo if echo=False."""
    sys.stdout.write(msg)
    sys.stdout.flush()
    if not echo:
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            import tty; tty.setraw(fd)
            buf = b""
            while True:
                ch = os.read(fd, 1)
                if ch in (b"\r", b"\n"):
                    break
                if ch == b"\x03":
                    raise KeyboardInterrupt
                if ch == b"\x7f" and buf:
                    buf = buf[:-1]
                else:
                    buf += ch
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print("\r")
            return buf.decode()
        except termios.error:
            pass
    return sys.stdin.readline().rstrip("\n")


# ── Target parsing ─────────────────────────────────────────────────────────────

def parse_target(cmd: str) -> tuple[str, str, int]:
    """
    Parse SSH_ORIGINAL_COMMAND.
    Returns (target_user, host, port).
    Formats: user@host  or  user@host:port
    """
    cmd = cmd.strip()
    if "@" not in cmd:
        die(f"Invalid target format: '{cmd}'. Expected user@host[:port]")
    target_user, hostpart = cmd.split("@", 1)
    if ":" in hostpart:
        host, port_s = hostpart.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            die(f"Invalid port in target: '{cmd}'")
    else:
        host, port = hostpart, 22
    return target_user.strip(), host.strip(), port


# ── Interactive server selector (when no SSH_ORIGINAL_COMMAND) ─────────────────

def interactive_select_server() -> tuple[str, str, int]:
    """Show numbered list of permitted servers; return selection."""
    linux_user = os.environ.get("USER") or os.getlogin()
    user = mx.get_user_by_username(linux_user)
    if not user:
        die("Your account is not registered in PAM. Contact an administrator.")
    user_uuid = user["uuid"]

    # Collect servers this user can access
    root = mx.get_root()
    accessible = []
    for srv_uuid in root.get("servers", []):
        perm = mx.check_permission(user_uuid, srv_uuid)
        if perm:
            srv = mx.get_server(srv_uuid)
            accessible.append((srv, perm))

    if not accessible:
        die("No servers are accessible with your current permissions.")

    print("\r\nAccessible servers:\r\n")
    for i, (srv, perm) in enumerate(accessible, 1):
        is_sudo = str(perm.get("allow_sudo")).lower() == "true" or perm.get("allow_sudo") == M_TRUE
        sudo_tag = " [sudo]" if is_sudo else ""
        print(f"  {i}. {srv.get('name','?')}  ({srv.get('host','?')}:{srv.get('port', 22)}){sudo_tag}\r")
    print()

    choice = prompt("Enter number (or q to quit): ")
    if choice.lower() == "q":
        sys.exit(0)
    try:
        idx = int(choice) - 1
        srv, _ = accessible[idx]
    except (ValueError, IndexError):
        die("Invalid selection.")

    bastion_user = srv.get("bastion_user", "bastion")
    port = int(srv.get("port", 22))
    return bastion_user, srv["host"], port


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    banner()

    # 1. Who is the SSH user?
    linux_user = os.environ.get("USER") or os.getlogin()

    # 2. Resolve in Metax2
    try:
        user = mx.get_user_by_username(linux_user)
        # Fallback: match by name field (handles Mani-created users without username field)
        if not user:
            for u in mx.get_users():
                name_val = u.get("name", "")
                if isinstance(name_val, dict):
                    name_val = next(iter(name_val.values()), "")
                if str(name_val).lower() == linux_user.lower():
                    # Patch username into Metax so future lookups work directly
                    try:
                        u["username"] = linux_user
                        mx.db_save(u, u["uuid"])
                    except Exception:
                        pass
                    user = u
                    break
    except Exception as e:
        die(f"Cannot reach Metax2: {e}")

    if not user:
        die(f"Account '{linux_user}' is not registered in PAM. Contact an administrator.")

    user_uuid = user["uuid"]
    totp_secret = user.get("totp_secret", "")

    # 3. TOTP verification
    if not totp_secret:
        audit.log(user_uuid, audit.ACTION_TOTP_FAIL, result="no_secret")
        die("TOTP is not configured for your account. Contact an administrator.")

    for attempt in range(3):
        code = prompt(f"TOTP code for {linux_user}: ", echo=False)
        if totp_mod.verify(totp_secret, code):
            break
        print("Invalid code.\r")
        if attempt == 2:
            audit.log(user_uuid, audit.ACTION_TOTP_FAIL, result="wrong_code")
            die("Too many failed TOTP attempts.")
    else:
        die("Authentication failed.")

    # 4. Resolve target
    original_cmd = os.environ.get("SSH_ORIGINAL_COMMAND", "").strip()
    if not original_cmd:
        target_user, target_host, target_port = interactive_select_server()
    else:
        target_user, target_host, target_port = parse_target(original_cmd)

    # 5. Find server in Metax2
    server = mx.get_server_by_name(target_host)
    if not server:
        audit.log(user_uuid, audit.ACTION_DENIED, result=f"unknown_server:{target_host}")
        die(f"Server '{target_host}' is not registered in PAM.")

    server_uuid = server["uuid"]

    # 6. Permission check
    perm = mx.check_permission(user_uuid, server_uuid)
    if not perm:
        audit.log(user_uuid, audit.ACTION_DENIED, server_uuid, result="no_permission")
        die(f"Access denied to {target_host}.")

    allow_sudo = str(perm.get("allow_sudo")).lower() == "true" or perm.get("allow_sudo") == M_TRUE

    # 7. Sudo password setup
    sudo_pass = None
    if allow_sudo:
        sudo_pass = secrets.token_urlsafe(24)
        try:
            set_ephemeral_sudo_password(target_host, target_port, BASTION_KEY, sudo_pass)
        except Exception as e:
            print(f"\r\n[warn] Could not set sudo password: {e}\r\n")
            sudo_pass = None

    # 8. Prepare recording path
    ts = time.strftime("%Y%m%d_%H%M%S")
    rec_path = os.path.join(
        RECORDINGS_DIR,
        f"{ts}_{linux_user}_{target_host.replace('.', '-')}.cast"
    )

    # 9. Create session record
    try:
        session_uuid = mx.create_session(user_uuid, server_uuid, rec_path)
    except Exception:
        session_uuid = None

    audit.log(user_uuid, audit.ACTION_CONNECT, server_uuid)

    # Build SSH command — NO local sudo needed: we use setfacl -m g:pam_users:r 
    # to grant read access to the root-owned BASTION_KEY for the pam_users group.
    ssh_cmd = [
        "ssh",
        "-i", BASTION_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ServerAliveInterval=30",
        "-p", str(target_port),
        f"{target_user}@{target_host}",
    ]

    print(f"\033[32mConnecting to {target_user}@{target_host}:{target_port} …\033[0m\r\n")

    # 11. Run session (PTY + asciicast + sudo injection + live stream + command log)
    exit_code, command_log = run_session(ssh_cmd, rec_path, session_uuid=session_uuid, sudo_password=sudo_pass)

    # 12. Cleanup
    if allow_sudo and sudo_pass:
        try:
            clear_sudo_password(target_host, target_port, BASTION_KEY)
        except Exception:
            pass

    if session_uuid:
        try:
            mx.close_session(session_uuid, command_log)
        except Exception as e:
            print(f"\r\n[bastion error] Failed to close session or upload to Metax: {e}\r\n")
            import traceback
            traceback.print_exc()

    audit.log(user_uuid, audit.ACTION_DISCONNECT, server_uuid,
              result=f"exit:{exit_code}")

    print(f"\r\n\033[36m[bastion] Session ended (exit {exit_code}).\033[0m\r\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with open("/tmp/bastion_error.log", "a") as f:
            import traceback
            f.write(f"\n--- {time.ctime()} ---\n")
            traceback.print_exc(file=f)
        print(f"\r\n[bastion FATAL ERROR] {e}\r\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\r\n[bastion] Interrupted.\r\n")
        sys.exit(130)
