#!/usr/bin/env python3
"""
CLI tool for PAM Bastion administration (Refactored v2).
"""
import sys, os, argparse, base64, secrets, signal, subprocess
sys.path.insert(0, os.path.dirname(__file__))

import metax_client as mx
from config import T_USER, T_GROUP, T_SERVER, T_PERMISSION, BASTION_KEY

#def cmd_user_add(a):
#    sec = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
#    uid = mx.create_user(a.username, sec, a.key)
#    print(f"Created user '{a.username}'\n  UUID: {uid}\n  TOTP: {sec}\n  URI: otpauth://totp/PAM:{a.username}?secret={sec}&issuer=PAMBastion")
def cmd_user_add(a):
    sec = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    uid = mx.create_user(a.username, sec, a.key)

    # Автоматическое создание пользователя в Linux и добавление в группу pam-users
    try:
        subprocess.run(["sudo", "useradd", "-m", "-G", "pam-users", a.username], check=True)
        print(f"Системный пользователь {a.username} успешно создан на бастионе.")
    except Exception as e:
        print(f"Внимание: не удалось создать системного пользователя: {e}")
    print(f"Created user '{a.username}'\n  UUID: {uid}\n  TOTP: {sec}\n  URI: otpauth://totp/PAM:{a.username}?secret={sec}&issuer=PAMBastion")

def cmd_user_list(a):
    print(f"{'Username':<20} {'UUID':<36}\n{'-'*58}")
    for u in mx.get_list("users"): print(f"{u.get('username',''):<20} {u.get('uuid',''):<36}")

def cmd_group_add(a):
    obj = {"type": T_GROUP, "name": a.name, "members": [], "permissions": []}
    uid = mx.db_save(obj)
    obj["uuid"] = uid; mx.db_save(obj, uid)
    root = mx.get_root(); root.setdefault("groups", []).append(uid); mx.save_root(root)
    print(f"Created group {a.name} ({uid})")

def cmd_group_add_member(a):
    grp = mx.db_get(a.group)
    if a.user not in grp.get("members", []):
        grp.setdefault("members", []).append(a.user); mx.db_save(grp, a.group)
        usr = mx.db_get(a.user); usr.setdefault("groups", []).append(a.group); mx.db_save(usr, a.user)
        print(f"Added {a.user} to {a.group}")
    else: print("Already in group.")

def cmd_server_add(a):
    obj = {"type": T_SERVER, "name": a.name, "host": a.host, "port": a.port, "bastion_user": a.bastion_user, "bootstrapped": "no", "sudo_password_enc": ""}
    uid = mx.db_save(obj)
    obj["uuid"] = uid; mx.db_save(obj, uid)
    root = mx.get_root(); root.setdefault("servers", []).append(uid); mx.save_root(root)
    print(f"Created server {a.name} ({uid})")

def cmd_server_list(a):
    print(f"{'Name':<20} {'Host':<20} {'Port':<6} {'Bootstrapped':<12} UUID\n{'-'*80}")
    for s in mx.get_list("servers"): print(f"{s.get('name',''):<20} {s.get('host',''):<20} {s.get('port','22'):<6} {s.get('bootstrapped','no'):<12} {s.get('uuid','')}")

def cmd_server_gen_token(a):
    tid = mx.create_bootstrap_token(a.server)
    try: sname = mx.db_get(a.server).get("name", a.server)
    except: sname = a.server
    from config import TOKEN_TTL_MINUTES, PUBLIC_VIEWER_HOST, BOOTSTRAP_PORT
    print(f"\n✅ Token created for '{sname}' (expires in {TOKEN_TTL_MINUTES}m)\nRun on target:\n  curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{tid} | sudo bash\n")

def cmd_server_reset_sudo(a):
    srv = mx.get_server_by_name(a.host)
    if not srv: return print(f"Server {a.host} not found.")
    print(f"Generating new bootstrap script for {a.host} to reset sudo password...")
    a.server = srv["uuid"]
    cmd_server_gen_token(a)

def cmd_perm_add(a):
    obj = {"type": T_PERMISSION, "name": f"perm-{a.group[:8]}-{a.server[:8]}", "group": a.group, "server": a.server, "allow_sudo": "true" if a.sudo else "false"}
    uid = mx.db_save(obj)
    obj["uuid"] = uid; mx.db_save(obj, uid)
    root = mx.get_root(); root.setdefault("permissions", []).append(uid); mx.save_root(root)
    grp = mx.db_get(a.group); grp.setdefault("permissions", []).append(uid); mx.db_save(grp, a.group)
    print(f"Created permission {uid} (sudo={a.sudo})")

def cmd_perm_list(a):
    from config import M_TRUE
    users, grps, srvs = {u["uuid"]: u for u in mx.get_list("users")}, {g["uuid"]: g for g in mx.get_list("groups")}, {s["uuid"]: s for s in mx.get_list("servers")}
    print(f"{'Group':<20} {'Server':<20} {'Host':<18} {'Sudo':<6} UUID\n{'-'*95}")
    for p in mx.get_list("permissions"):
        g, s = grps.get(p.get("group"), {}), srvs.get(p.get("server"), {})
        is_sudo = str(p.get('allow_sudo')).lower() == 'true' or p.get('allow_sudo') == M_TRUE
        print(f"{g.get('name', '')[:20]:<20} {s.get('name', '')[:20]:<20} {s.get('host', '')[:18]:<18} {'yes' if is_sudo else 'no':<6} {p.get('uuid','')}")

def cmd_bootstrap(a):
    from bootstrap_gen import generate, get_bastion_pubkey
    print(generate(mx.db_get(a.server), get_bastion_pubkey()))

def resolve_name(uid, cache, items): return cache.setdefault(uid, items.get(uid, {}).get("name") or items.get(uid, {}).get("username") or uid[:8])

def cmd_session_list(a):
    sess = mx.get_list("sessions") if getattr(a, 'all', False) else mx.get_active_sessions()
    if not sess: return print("No sessions found.")
    usrs, srvs, cache = {u["uuid"]: u for u in mx.get_list("users")}, {s["uuid"]: s for s in mx.get_list("servers")}, {}
    print(f"\n  {'#':<3} {'Started':<20} {'User':<16} {'Server':<16} {'PID':<7} {'Status':<8} UUID\n  {'-'*100}")
    for i, s in enumerate(sess, 1):
        un, sn = resolve_name(s.get("user"), cache, usrs), resolve_name(s.get("server"), cache, srvs)
        st = "ended" if s.get("ended_at") else "\033[32mACTIVE\033[0m"
        print(f"  {i:<3} {s.get('started_at','')[:19]:<20} {un:<16} {sn:<16} {s.get('bastion_pid','-'):<7} {st:<8} {s.get('uuid','')}")

def cmd_session_kill(a):
    s = mx.db_get(a.session)
    if s.get("ended_at"): return print("Session already ended.")
    pid = int(s.get("bastion_pid", 0))
    if not pid: return print("No PID stored.")
    try: os.kill(pid, 0)
    except:
        s["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); mx.db_save(s, a.session); return print("Process already gone, marked ended.")
    print(f"Sending SIGHUP to PID {pid}..."); os.kill(pid, signal.SIGHUP); print("✅ Terminated.")

def build_parser():
    p = argparse.ArgumentParser(description="PAM Bastion CLI (v2)")
    s = p.add_subparsers(dest="entity")
    
    su = s.add_parser("user").add_subparsers(dest="action")
    ua = su.add_parser("add"); ua.add_argument("--username", required=True); ua.add_argument("--key", required=True)
    su.add_parser("list")
    
    sg = s.add_parser("group").add_subparsers(dest="action")
    sg.add_parser("add").add_argument("--name", required=True)
    gm = sg.add_parser("add-member"); gm.add_argument("--group", required=True); gm.add_argument("--user", required=True)
    
    ss = s.add_parser("server").add_subparsers(dest="action")
    sa = ss.add_parser("add"); sa.add_argument("--name", required=True); sa.add_argument("--host", required=True); sa.add_argument("--port", type=int, default=22); sa.add_argument("--bastion-user", default="bastion")
    ss.add_parser("list")
    ss.add_parser("gen-token").add_argument("--server", required=True)
    ss.add_parser("reset-sudo", help="Reset/init sudo pass for a host").add_argument("--host", required=True)
    
    sp = s.add_parser("perm").add_subparsers(dest="action")
    pa = sp.add_parser("add"); pa.add_argument("--group", required=True); pa.add_argument("--server", required=True); pa.add_argument("--sudo", action="store_true")
    sp.add_parser("list")
    
    s.add_parser("bootstrap").add_argument("--server", required=True)
    
    ss2 = s.add_parser("session").add_subparsers(dest="action")
    ss2.add_parser("list").add_argument("--all", action="store_true")
    sk = ss2.add_parser("kill"); sk.add_argument("--session", required=True); sk.add_argument("-y", "--yes", action="store_true")
    s.add_parser("sessions")
    return p

def main():
    a = build_parser().parse_args()
    d = {("user","add"):cmd_user_add, ("user","list"):cmd_user_list, ("group","add"):cmd_group_add, ("group","add-member"):cmd_group_add_member,
         ("server","add"):cmd_server_add, ("server","list"):cmd_server_list, ("server","gen-token"):cmd_server_gen_token, ("server","reset-sudo"):cmd_server_reset_sudo,
         ("perm","add"):cmd_perm_add, ("perm","list"):cmd_perm_list, ("session","list"):cmd_session_list, ("session","kill"):cmd_session_kill,
         ("bootstrap",None):cmd_bootstrap, ("sessions",None):cmd_session_list}
    if fn := d.get((a.entity, getattr(a, "action", None))): fn(a)
    else: build_parser().print_help()

if __name__ == "__main__": main()
