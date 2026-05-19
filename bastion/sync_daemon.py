#!/usr/bin/env python3
"""
PAM Bastion — OS sync daemon (Refactored v2).
Оригинальный размер: 435 строк.
Новый размер: ~120 строк. (Сокращение почти в 4 раза).
"""
import sys, os, subprocess, time, logging, signal
sys.path.insert(0, os.path.dirname(__file__))

import metax_client as mx
from config import PAM_ROOT, AUTHORIZED_KEYS, PUBLIC_VIEWER_HOST, BOOTSTRAP_PORT, TOKEN_REGEN_MINUTES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sync] %(message)s")
log = logging.getLogger("sync")
POLL_INTERVAL = 30

def run(*a):
    r = subprocess.run(a, capture_output=True)
    if r.returncode != 0: log.warning(f"cmd fail {a}: {r.stderr.decode()}")

def sys_users(): return {l.split(":")[0] for l in open("/etc/passwd") if l.strip()}
def sys_groups(): return {l.split(":")[0] for l in open("/etc/group") if l.strip()}

def get_auth_keys():
    if not os.path.exists(AUTHORIZED_KEYS): return {}
    ks, u = {}, None
    for l in open(AUTHORIZED_KEYS):
        l = l.strip()
        if l.startswith("# user:"): u = l[7:]
        elif l and not l.startswith("#") and u: ks[u] = l; u = None
    return ks

def save_auth_keys(ks):
    os.makedirs(os.path.dirname(AUTHORIZED_KEYS) or ".", exist_ok=True)
    tmp = AUTHORIZED_KEYS + ".tmp"
    with open(tmp, "w") as f: f.write("\n".join(f"# user:{u}\n{k}" for u, k in sorted(ks.items())) + "\n")
    os.chmod(tmp, 0o644); os.replace(tmp, AUTHORIZED_KEYS)

def ensure_user(un: str, pub_key: str):
    if un not in sys_users(): run("useradd", "-m", "-s", "/bin/bash", un)
    run("usermod", "-aG", "pam_users", un)
    ks = get_auth_keys()
    ks[un] = f'command="/usr/bin/python3 {os.path.abspath(os.path.join(os.path.dirname(__file__), "bastion.py"))}",no-port-forwarding,no-X11-forwarding,no-agent-forwarding {pub_key.strip()}'
    save_auth_keys(ks)

def remove_user(un: str):
    ks = get_auth_keys(); ks.pop(un, None); save_auth_keys(ks)
    if un in sys_users(): run("userdel", "-r", un)

def sync_group_members(gname: str, members: set):
    if gname not in sys_groups(): run("groupadd", gname)
    r = subprocess.run(["getent", "group", gname], capture_output=True)
    cur = set(r.stdout.decode().strip().split(":")[3].split(",")) if r.returncode == 0 and r.stdout.decode().strip().split(":")[3] else set()
    for u in members - cur: run("usermod", "-aG", gname, u)
    for u in cur - members: run("gpasswd", "-d", u, gname)

def full_sync() -> list[str]:
    uuids = [PAM_ROOT]; wanted_u, wanted_g = {}, {}
    try: root = mx.get_root()
    except: return uuids

    for u in root.get("users", []):
        uuids.append(u)
        try:
            usr = mx.db_get(u)
            un = usr.get("username") or (usr.get("name", "") if isinstance(usr.get("name"), str) else next(iter(usr.get("name", {}).values()), ""))
            if un and not usr.get("totp_secret"):
                import totp; sec = totp.generate_secret()
                usr.update({"totp_secret": sec, "totp_url": f"otpauth://totp/PAM:{un}?secret={sec}&issuer=PAMBastion", "username": un})
                mx.db_save(usr, u); log.info(f"Generated TOTP for {un}")
            if un and usr.get("ssh_public_key"): wanted_u[un] = usr["ssh_public_key"]
        except: pass

    for g in root.get("groups", []):
        uuids.append(g)
        try:
            grp = mx.db_get(g)
            gn = grp.get("name", "") if isinstance(grp.get("name"), str) else next(iter(grp.get("name", {}).values()), "")
            if gn:
                members = {mx.db_get(m).get("username") for m in grp.get("members", [])}
                wanted_g[gn] = {m for m in members if m}
        except: pass

    uuids.extend(root.get("permissions", []))

    for s in root.get("servers", []):
        uuids.append(s)
        try:
            srv = mx.db_get(s)
            if srv.get("bootstrapped") != "yes" and time.time() - float(srv.get("token_generated_at", 0)) > TOKEN_REGEN_MINUTES * 60:
                tok = mx.create_bootstrap_token(s)
                srv.update({"bootstrap_command": f"curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{tok} | sudo bash", "token_generated_at": time.time()})
                mx.db_save(srv, s); log.info(f"Auto-bootstrapped {srv.get('name')}")
        except: pass

    managed = set(get_auth_keys().keys()); w_users = set(wanted_u.keys())
    for un, k in wanted_u.items(): ensure_user(un, k)
    for un in managed - w_users: remove_user(un)
    for gn, ms in wanted_g.items(): sync_group_members(gn, ms)

    log.info(f"Sync: wanted={len(w_users)}, managed={len(managed)}, rm={len(managed-w_users)}, grps={len(wanted_g)}")
    return uuids + root.get("sessions", [])

def check_kills():
    killed = 0
    for s in mx.get_root().get("sessions", []):
        try:
            sess = mx.db_get(s)
            if sess.get("ended_at") or sess.get("status", "").lower() != "inactive": continue
            pid = int(sess.get("bastion_pid", 0))
            if not pid: raise ValueError("No PID")
            os.kill(pid, 0)
            os.kill(pid, signal.SIGHUP)
            killed += 1
        except ProcessLookupError:
            sess.update({"ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "description": (sess.get("description", "") + "\n[sync: gone]")})
            mx.db_save(sess, s)
        except Exception as e:
            if not sess.get("bastion_pid"):
                sess.update({"ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "description": (sess.get("description", "") + "\n[sync: no pid]")})
                mx.db_save(sess, s)
    if killed: log.info(f"Killed {killed} sessions.")

def main():
    while True:
        try:
            log.info("Connecting to WS...")
            ws = mx.MetaxWebSocket()
            ws._sock.settimeout(5.0) # Prevents infinite block if no WS events arrive, enabling the POLL_INTERVAL
            if not (msg := ws.recv()) or msg.get("event") != "connected": time.sleep(5); continue
            ws.token = msg["token"]; subs = set(); last = 0
            while True:
                msg = ws.recv()
                if time.time() - last >= POLL_INTERVAL or (msg and msg.get("event") == "update"):
                    new_uuids = full_sync()
                    last = time.time(); check_kills()
                    for u in set(new_uuids) - subs:
                        try: ws.register_listener(u); subs.add(u)
                        except: pass
        except Exception as e:
            if "timed out" not in str(e).lower(): log.error(f"WS Error: {e} - reconnecting..."); time.sleep(5)

if __name__ == "__main__":
    if os.geteuid() != 0: sys.exit("Run as root")
    main()

