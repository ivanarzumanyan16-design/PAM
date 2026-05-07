#!/usr/bin/env python3
"""
CLI tool for PAM Bastion administration.
Provides commands to create/list users, groups, servers, permissions.

Usage:
    python3 pam_cli.py user add  --username alice --key "ssh-ed25519 AAAA..."
    python3 pam_cli.py user list
    python3 pam_cli.py group add  --name ops
    python3 pam_cli.py group add-member --group <uuid> --user <uuid>
    python3 pam_cli.py server add --name prod-web --host 10.0.0.1 --port 22
    python3 pam_cli.py perm add   --group <uuid> --server <uuid> [--sudo]
    python3 pam_cli.py bootstrap  --server <uuid>
"""
import sys, os, argparse, base64, hmac, hashlib, struct, secrets
sys.path.insert(0, os.path.dirname(__file__))

import metax_client as mx
from config import T_USER, T_GROUP, T_SERVER, T_PERMISSION, BASTION_KEY, M_TRUE


# ── TOTP secret generation ─────────────────────────────────────────────────────
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


# ── User commands ──────────────────────────────────────────────────────────────
def cmd_user_add(args):
    secret = new_totp_secret()
    uuid = mx.create_user(args.username, secret, args.key)
    print(f"Created user '{args.username}'")
    print(f"  UUID:        {uuid}")
    print(f"  TOTP Secret: {secret}")
    print(f"  TOTP URI:    otpauth://totp/PAM:{args.username}?secret={secret}&issuer=PAMBastion")

def cmd_user_list(args):
    users = mx.get_users()
    if not users:
        print("No users registered.")
        return
    print(f"{'Username':<20} {'UUID':<36}")
    print("-" * 58)
    for u in users:
        print(f"{u.get('username',''):<20} {u.get('uuid',''):<36}")


# ── Group commands ─────────────────────────────────────────────────────────────
def cmd_group_add(args):
    root = mx.get_root()
    obj = {"type": T_GROUP, "name": args.name, "members": [], "permissions": []}
    uuid = mx.db_save(obj)
    obj["uuid"] = uuid
    mx.db_save(obj, uuid)
    root.setdefault("groups", []).append(uuid)
    mx.save_root(root)
    print(f"Created group '{args.name}'  UUID: {uuid}")

def cmd_group_add_member(args):
    grp = mx.db_get(args.group)
    if args.user not in grp.get("members", []):
        grp.setdefault("members", []).append(args.user)
        mx.db_save(grp, args.group)
        # back-reference in user
        user = mx.db_get(args.user)
        if args.group not in user.get("groups", []):
            user.setdefault("groups", []).append(args.group)
            mx.db_save(user, args.user)
        print(f"Added user {args.user} to group {args.group}")
    else:
        print("User already in group.")


# ── Server commands ────────────────────────────────────────────────────────────
def cmd_server_add(args):
    root = mx.get_root()
    obj = {
        "type": T_SERVER,
        "name": args.name,
        "host": args.host,
        "port": str(args.port),
        "bastion_user": args.bastion_user,
        "bootstrapped": "no",
    }
    uuid = mx.db_save(obj)
    obj["uuid"] = uuid
    mx.db_save(obj, uuid)
    root.setdefault("servers", []).append(uuid)
    mx.save_root(root)
    print(f"Created server '{args.name}'  UUID: {uuid}")
    print(f"Run bootstrap: python3 bootstrap_gen.py {uuid} | ssh root@{args.host} bash")

def cmd_server_list(args):
    root = mx.get_root()
    servers = [mx.db_get(s) for s in root.get("servers", [])]
    if not servers:
        print("No servers registered.")
        return
    print(f"{'Name':<20} {'Host':<20} {'Port':<6} {'Bootstrap':<12} {'UUID'}")
    print("-" * 80)
    for s in servers:
        print(f"{s.get('name',''):<20} {s.get('host',''):<20} "
              f"{s.get('port','22'):<6} {s.get('bootstrapped','no'):<12} {s.get('uuid','')}")

def cmd_server_gen_token(args):
    from bootstrap_server import cli_gen_token
    cli_gen_token(args.server)


def cmd_server_check_sudo(args):
    """
    Check if bastion user can run NOPASSWD sudo on the given server.
    Useful for diagnosing why sudo auto-fill isn't working.
    Usage: python3 pam_cli.py server check-sudo --host 10.0.0.5 --port 22
    """
    from session import check_sudo_access
    host = args.host
    port = args.port
    print(f"Checking NOPASSWD sudo access on bastion@{host}:{port} …")
    ok = check_sudo_access(host, port, BASTION_KEY)
    if ok:
        print(f"  ✅ NOPASSWD sudo is configured correctly on {host}.")
        print(f"     PAM will be able to inject the sudo password automatically.")
    else:
        print(f"  ❌ NOPASSWD sudo is NOT working on {host}.")
        print(f"     Fix: ensure /etc/sudoers.d/bastion on {host} contains:")
        print(f"       bastion ALL=(root) NOPASSWD: /usr/sbin/usermod, /sbin/usermod")
        print(f"     Or re-run bootstrap: python3 pam_cli.py server gen-token --server <uuid>")


# ── Permission commands ────────────────────────────────────────────────────────
def cmd_perm_add(args):
    root = mx.get_root()
    obj = {
        "type": T_PERMISSION,
        "name": f"perm-{args.group[:8]}-{args.server[:8]}",
        "group": args.group,
        "server": args.server,
        "allow_sudo": "true" if args.sudo else "false",
    }
    uuid = mx.db_save(obj)
    obj["uuid"] = uuid
    mx.db_save(obj, uuid)
    root.setdefault("permissions", []).append(uuid)
    mx.save_root(root)
    # also add to group's permissions collection
    grp = mx.db_get(args.group)
    grp.setdefault("permissions", []).append(uuid)
    mx.db_save(grp, args.group)
    print(f"Created permission  UUID: {uuid}  (sudo={args.sudo})")


def cmd_perm_list(args):
    """List all permissions showing group→server mapping and sudo flag."""
    root = mx.get_root()
    perms = [mx.db_get(p) for p in root.get("permissions", [])]
    if not perms:
        print("No permissions configured.")
        return

    # Build lookup tables
    users_by_uuid = {u["uuid"]: u for u in mx.get_users()}
    groups_by_uuid = {}
    for g_uuid in root.get("groups", []):
        try:
            g = mx.db_get(g_uuid)
            groups_by_uuid[g_uuid] = g
        except Exception:
            pass
    servers_by_uuid = {}
    for s_uuid in root.get("servers", []):
        try:
            s = mx.db_get(s_uuid)
            servers_by_uuid[s_uuid] = s
        except Exception:
            pass

    print(f"{'Group':<20} {'Server':<20} {'Host':<18} {'Sudo':<6} {'Permission UUID'}")
    print("-" * 95)
    for p in perms:
        g_uuid = p.get("group", "")
        s_uuid = p.get("server", "")
        grp = groups_by_uuid.get(g_uuid, {})
        srv = servers_by_uuid.get(s_uuid, {})
        gname = grp.get("name", g_uuid[:8])
        sname = srv.get("name", s_uuid[:8])
        shost = srv.get("host", "")
        sudo_flag = p.get("allow_sudo", "false")
        is_sudo = sudo_flag == "true" or sudo_flag == M_TRUE
        sudo_str = "yes" if is_sudo else "no"
        print(f"{gname:<20} {sname:<20} {shost:<18} {sudo_str:<6} {p.get('uuid','')}")


# ── Bootstrap ──────────────────────────────────────────────────────────────────
def cmd_bootstrap(args):
    from bootstrap_gen import generate, get_bastion_pubkey
    srv = mx.db_get(args.server)
    print(generate(srv, get_bastion_pubkey()))


# ── Session / audit listing ────────────────────────────────────────────────────
def cmd_sessions(args):
    root = mx.get_root()
    sessions = [mx.db_get(s) for s in root.get("sessions", [])]
    if not sessions:
        print("No sessions recorded.")
        return
    print(f"{'Started':<22} {'User':<36} {'Server':<36} {'Ended'}")
    print("-" * 110)
    for s in sessions:
        print(f"{s.get('started_at',''):<22} {s.get('user',''):<36} "
              f"{s.get('server',''):<36} {s.get('ended_at','active')}")


# ── Argument parser ────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(description="PAM Bastion CLI")
    sub = p.add_subparsers(dest="entity")

    # user
    pu = sub.add_parser("user")
    su = pu.add_subparsers(dest="action")
    ua = su.add_parser("add")
    ua.add_argument("--username", required=True)
    ua.add_argument("--key", required=True, help="SSH public key string")
    su.add_parser("list")

    # group
    pg = sub.add_parser("group")
    sg = pg.add_subparsers(dest="action")
    ga = sg.add_parser("add")
    ga.add_argument("--name", required=True)
    gm = sg.add_parser("add-member")
    gm.add_argument("--group", required=True)
    gm.add_argument("--user", required=True)

    # server
    ps = sub.add_parser("server")
    ss = ps.add_subparsers(dest="action")
    sa = ss.add_parser("add")
    sa.add_argument("--name", required=True)
    sa.add_argument("--host", required=True)
    sa.add_argument("--port", type=int, default=22)
    sa.add_argument("--bastion-user", default="bastion")
    ss.add_parser("list")
    gt = ss.add_parser("gen-token", help="Generate a one-time bootstrap token for a server")
    gt.add_argument("--server", required=True, help="Server UUID")
    cs = ss.add_parser("check-sudo", help="Check if NOPASSWD sudo is configured on target server")
    cs.add_argument("--host", required=True, help="Target server host/IP")
    cs.add_argument("--port", type=int, default=22, help="Target server SSH port")

    # perm
    pp = sub.add_parser("perm")
    sp = pp.add_subparsers(dest="action")
    pa = sp.add_parser("add")
    pa.add_argument("--group", required=True)
    pa.add_argument("--server", required=True)
    pa.add_argument("--sudo", action="store_true")
    sp.add_parser("list", help="List all permissions (group→server mappings)")

    # bootstrap
    pb = sub.add_parser("bootstrap")
    pb.add_argument("--server", required=True)

    # sessions
    sub.add_parser("sessions")

    return p


def main():
    p = build_parser()
    args = p.parse_args()

    dispatch = {
        ("user",    "add"):          cmd_user_add,
        ("user",    "list"):         cmd_user_list,
        ("group",   "add"):          cmd_group_add,
        ("group",   "add-member"):   cmd_group_add_member,
        ("server",  "add"):          cmd_server_add,
        ("server",  "list"):         cmd_server_list,
        ("server",  "gen-token"):    cmd_server_gen_token,
        ("server",  "check-sudo"):   cmd_server_check_sudo,
        ("perm",    "add"):          cmd_perm_add,
        ("perm",    "list"):         cmd_perm_list,
        ("bootstrap", None):         cmd_bootstrap,
        ("sessions",  None):         cmd_sessions,
    }

    key = (args.entity, getattr(args, "action", None))
    fn = dispatch.get(key)
    if fn:
        fn(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()

