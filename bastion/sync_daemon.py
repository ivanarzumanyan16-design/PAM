"""
PAM Bastion — OS sync daemon.
Keeps local Linux users/groups in sync with Metax2 pam-root state.

Two sync triggers:
  1. WebSocket events from Metax2 (subscribed to root + all child UUIDs)
  2. Periodic polling every POLL_INTERVAL seconds (fallback)

Deletion logic:
  - Tracks PAM-managed users via /etc/pam_authorized_keys
  - On sync: computes diff (wanted vs managed) and removes stale users/groups

Run as root (needs useradd/userdel/groupadd/gpasswd).
"""
import sys, os, json, subprocess, time, logging, threading, signal
from metax_client import MetaxWebSocket, db_get, db_save, get_root, client, create_bootstrap_token
import totp
from config import PAM_ROOT, AUTHORIZED_KEYS, PUBLIC_VIEWER_HOST, BOOTSTRAP_PORT, TOKEN_REGEN_MINUTES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sync] %(message)s")
log = logging.getLogger("sync")

POLL_INTERVAL = 30  # seconds between forced re-syncs

# ── Linux user/group helpers ───────────────────────────────────────────────────

def linux_users() -> set[str]:
    with open("/etc/passwd") as f:
        return {line.split(":")[0] for line in f if line.strip()}

def linux_groups() -> set[str]:
    with open("/etc/group") as f:
        return {line.split(":")[0] for line in f if line.strip()}

def run(*args):
    result = subprocess.run(list(args), capture_output=True)
    if result.returncode != 0:
        log.warning("cmd failed %s: %s", args, result.stderr.decode())
    return result.returncode == 0

def ensure_user(username: str, ssh_pub_key: str):
    existing = linux_users()
    if username not in existing:
        log.info("useradd %s", username)
        run("useradd", "-m", "-s", "/bin/bash", username)
    # Add to pam_users group so sshd Match Group works
    run("usermod", "-aG", "pam_users", username)
    _write_authorized_key(username, ssh_pub_key)

def remove_user(username: str):
    log.info("removing PAM user: %s", username)
    _remove_authorized_key(username)
    if username in linux_users():
        log.info("userdel -r %s", username)
        run("userdel", "-r", username)

def ensure_group(name: str):
    if name not in linux_groups():
        log.info("groupadd %s", name)
        run("groupadd", name)

def remove_group(name: str):
    log.info("removing PAM group: %s", name)
    if name in linux_groups():
        log.info("groupdel %s", name)
        run("groupdel", name)

def sync_group_members(group_name: str, member_usernames: list[str]):
    """Ensure exactly these users are in the group."""
    result = subprocess.run(["getent", "group", group_name], capture_output=True)
    if result.returncode != 0:
        return
    line = result.stdout.decode().strip()
    current = set(line.split(":")[3].split(",")) if line.split(":")[3] else set()
    wanted = set(member_usernames)
    for u in wanted - current:
        log.info("usermod -aG %s %s", group_name, u)
        run("usermod", "-aG", group_name, u)
    for u in current - wanted:
        log.info("gpasswd -d %s %s", u, group_name)
        run("gpasswd", "-d", u, group_name)


# ── authorized_keys management ─────────────────────────────────────────────────

def _load_auth_keys() -> dict[str, str]:
    """Return {username: key_line}. This is our source of truth for 'managed users'."""
    keys = {}
    if not os.path.exists(AUTHORIZED_KEYS):
        return keys
    username = None
    with open(AUTHORIZED_KEYS) as f:
        for line in f:
            line = line.strip()
            if line.startswith("# user:"):
                username = line[7:]
            elif line and not line.startswith("#") and username:
                keys[username] = line
                username = None
    return keys

def pam_managed_users() -> set[str]:
    """Return set of usernames currently managed by PAM (from authorized_keys)."""
    return set(_load_auth_keys().keys())

def _write_authorized_key(username: str, ssh_pub_key: str):
    bastion_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "bastion.py"))
    restricted = (
        f'command="/usr/bin/python3 {bastion_py}",'
        f'no-port-forwarding,no-X11-forwarding,no-agent-forwarding '
        f'{ssh_pub_key.strip()}'
    )
    keys = _load_auth_keys()
    keys[username] = restricted
    _flush_auth_keys(keys)

def _remove_authorized_key(username: str):
    keys = _load_auth_keys()
    keys.pop(username, None)
    _flush_auth_keys(keys)

def _flush_auth_keys(keys: dict[str, str]):
    os.makedirs(os.path.dirname(AUTHORIZED_KEYS) or ".", exist_ok=True)
    lines = []
    for username, key in sorted(keys.items()):
        lines.append(f"# user:{username}")
        lines.append(key)
    tmp = AUTHORIZED_KEYS + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n" if lines else "")
    os.chmod(tmp, 0o644)
    os.replace(tmp, AUTHORIZED_KEYS)  # atomic


# ── Full diff-based sync from Metax2 → OS ─────────────────────────────────────

def full_sync() -> list[str]:
    """
    Sync OS state with Metax2. Returns list of all PAM object UUIDs
    (for WebSocket subscription).
    """
    log.info("Running full sync...")
    all_uuids = [PAM_ROOT]

    try:
        root = get_root()
    except Exception as e:
        log.error("Cannot reach Metax2: %s", e)
        return all_uuids

    # ── Collect wanted state from Metax2 ───────────────────────────────────────
    wanted_users = {}   # {username: ssh_public_key}
    wanted_groups = {}  # {group_name: [member_usernames]}

    # ── Auto-generate TOTP secrets for users ───────────────────────────────────
    for u_uuid in root.get("users", []):
        all_uuids.append(u_uuid)
        try:
            user = db_get(u_uuid)
            uname = user.get("username") or user.get("name", "")
            if isinstance(uname, dict):
                uname = next(iter(uname.values()), "")
            key = user.get("ssh_public_key", "")
            
            needs_save = False
            if not user.get("username") and uname:
                user["username"] = uname
                needs_save = True

            if uname and not user.get("totp_secret"):
                secret = totp.generate_secret()
                user["totp_secret"] = secret
                user["totp_url"] = f"otpauth://totp/PAM:{uname}?secret={secret}&issuer=PAMBastion"
                needs_save = True
                log.info("Auto-generated TOTP secret for user %s", uname)
            
            if needs_save:
                db_save(user, u_uuid)
            
            if uname and key:
                wanted_users[uname] = key
        except Exception as e:
            log.warning("Failed to auto-generate TOTP for user %s: %s", u_uuid, e)

    for g_uuid in root.get("groups", []):
        all_uuids.append(g_uuid)
        try:
            grp = db_get(g_uuid)
            gname = grp.get("name", "")
            if isinstance(gname, dict):
                gname = next(iter(gname.values()), "")
            if not gname:
                continue
            members = []
            for m_uuid in grp.get("members", []):
                try:
                    m = db_get(m_uuid)
                    mn = m.get("username", "")
                    if mn:
                        members.append(mn)
                except Exception:
                    pass
            wanted_groups[gname] = members
        except Exception as e:
            log.warning("Failed to get group %s: %s", g_uuid, e)

    for p_uuid in root.get("permissions", []):
        all_uuids.append(p_uuid)

    # ── Auto-generate bootstrap tokens for servers ─────────────────────────────
    for s_uuid in root.get("servers", []):
        all_uuids.append(s_uuid)
        try:
            srv = db_get(s_uuid)
            if srv.get("bootstrapped") != "yes":
                # Check if we need to generate a new token
                last_gen = float(srv.get("token_generated_at", 0))
                now_ts = time.time()
                if now_ts - last_gen > (TOKEN_REGEN_MINUTES * 60):
                    token = create_bootstrap_token(s_uuid)
                    cmd = f"curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{token} | sudo bash"
                    srv["bootstrap_command"] = cmd
                    srv["token_generated_at"] = now_ts
                    db_save(srv, s_uuid)
                    log.info("Auto-generated new bootstrap command for server %s", srv.get("name"))
        except Exception as e:
            log.warning("Failed to auto-bootstrap server %s: %s", s_uuid, e)

    # ── Compute diff ───────────────────────────────────────────────────────────
    managed = pam_managed_users()
    wanted_set = set(wanted_users.keys())

    # Users to ADD or UPDATE
    for uname in wanted_set:
        ensure_user(uname, wanted_users[uname])

    # Users to DELETE (in managed but not in wanted)
    stale_users = managed - wanted_set
    for uname in stale_users:
        remove_user(uname)

    # Groups to ADD or UPDATE
    managed_pam_groups = set()  # track for deletion
    for gname, members in wanted_groups.items():
        managed_pam_groups.add(gname)
        ensure_group(gname)
        sync_group_members(gname, members)

    # We don't auto-delete Linux groups (too dangerous, might match system groups).
    # Only remove from group members tracking.

    log.info("Full sync done. Users: wanted=%d, managed=%d, removed=%d. Groups: %d",
             len(wanted_set), len(managed), len(stale_users), len(wanted_groups))

    # Also subscribe to session UUIDs so Mani status changes trigger WS events
    for s_uuid in root.get("sessions", []):
        if s_uuid not in all_uuids:
            all_uuids.append(s_uuid)

    return all_uuids


# ── Session kill watcher ───────────────────────────────────────────────────────

def check_session_kills():
    """
    Scan all active sessions in Metax.
    If a session has status='inactive' and still has a live bastion PID
    → send SIGHUP to terminate it gracefully.

    Called by the sync daemon on every full_sync cycle and on WebSocket
    update events so that Mani UI changes take effect within seconds.
    """
    try:
        root = get_root()
    except Exception as e:
        log.warning("check_session_kills: cannot reach Metax: %s", e)
        return

    killed = 0
    for s_uuid in root.get("sessions", []):
        try:
            sess = db_get(s_uuid)
        except Exception:
            continue

        # Only care about sessions that are still "open" in Metax
        if sess.get("ended_at"):
            continue

        # Check if Mani/admin set status → inactive
        if sess.get("status", "").lower() != "inactive":
            continue

        pid_str = sess.get("bastion_pid", "")
        if not pid_str:
            # No PID stored — session was started before force-kill support.
            # Mark ended_at so we don't keep looping over it.
            log.warning("Session %s marked inactive but has no PID. Closing record only.", s_uuid[:8])
            sess["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            sess["description"] = (sess.get("description") or "") + "\n[sync-daemon: inactive, no pid]"
            try:
                db_save(sess, s_uuid)
            except Exception:
                pass
            continue

        try:
            pid = int(pid_str)
        except ValueError:
            log.warning("Session %s has invalid PID '%s', skipping.", s_uuid[:8], pid_str)
            continue

        # Check process still alive
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process already gone — just tidy up Metax
            log.info("Session %s (PID %d) already gone. Closing Metax record.", s_uuid[:8], pid)
            sess["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            sess["description"] = (sess.get("description") or "") + "\n[sync-daemon: process already gone]"
            try:
                db_save(sess, s_uuid)
            except Exception:
                pass
            continue
        except PermissionError:
            log.error("Cannot signal PID %d for session %s: permission denied.", pid, s_uuid[:8])
            continue

        # Send SIGHUP → session.py handler shows message to user and exits cleanly
        try:
            os.kill(pid, signal.SIGHUP)
            log.info(
                "Sent SIGHUP to session %s (PID %d) — status set to inactive in Mani.",
                s_uuid[:8], pid
            )
            killed += 1
        except Exception as e:
            log.error("Failed to kill session %s (PID %d): %s", s_uuid[:8], pid, e)

    if killed:
        log.info("check_session_kills: terminated %d session(s).", killed)


# ── WebSocket event loop ───────────────────────────────────────────────────────

def main():
    while True:
        try:
            log.info("Connecting to Metax2 WebSocket...")
            ws = MetaxWebSocket()

            # Get session token from first message
            msg = ws.recv()
            if msg and msg.get("event") == "connected":
                ws.token = msg["token"]
                log.info("WS token: %s", ws.token)
            else:
                log.error("Unexpected first WS message: %s", msg)
                time.sleep(5)
                continue

            # Initial full sync — returns all UUIDs to subscribe to
            all_uuids = full_sync()

            # Subscribe to PAM root AND all child objects
            for uuid in all_uuids:
                try:
                    ws.register_listener(uuid)
                except Exception:
                    pass
            log.info("Subscribed to %d UUIDs", len(all_uuids))

            # Track subscribed UUIDs to detect new ones on re-sync
            subscribed = set(all_uuids)

            # Periodic sync in background thread
            last_sync = time.time()

            # Event loop
            while True:
                msg = ws.recv()  # blocks until data or timeout

                now = time.time()
                need_sync = False

                if msg is not None:
                    if msg.get("event") == "update":
                        uuid = msg.get("uuid", "")
                        log.info("Update event for %s", uuid)
                        need_sync = True

                # Periodic fallback sync
                if now - last_sync >= POLL_INTERVAL:
                    need_sync = True

                if need_sync:
                    new_uuids = full_sync()
                    last_sync = time.time()

                    # Always check for inactive sessions after every sync
                    check_session_kills()

                    # Subscribe to any new UUIDs (e.g., newly created sessions)
                    for uuid in new_uuids:
                        if uuid not in subscribed:
                            try:
                                ws.register_listener(uuid)
                                subscribed.add(uuid)
                                log.info("Subscribed to new UUID: %s", uuid)
                            except Exception:
                                pass

                # Fast-path: if a WS update came in for a session UUID, check kills immediately
                # even if full_sync is not needed yet (e.g. only one session changed)
                elif msg is not None and msg.get("event") == "update":
                    check_session_kills()

                if msg is None:
                    pass

        except Exception as e:
            log.error("Error: %s — reconnecting in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("sync_daemon must run as root")
    main()



