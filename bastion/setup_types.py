#!/usr/bin/env python3
"""
PAM Bastion — one-time Metax2 type setup.

Creates 7 PAM type objects + 1 pam-root container in Metax2.
Idempotent: safe to run multiple times (overwrites with same UUIDs).

Run before using the bastion:
    python3 setup_types.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
import httpx
from config import (
    METAX_HOST, METAX_PORT,
    M_TRUE, M_FALSE, M_META_TYPE, M_STRING_TYPE, M_COLL_COMPOSE,
    T_USER, T_GROUP, T_SERVER, T_PERMISSION, T_SESSION, T_AUDIT, T_ROOT,
    PAM_ROOT,
)
print(
    METAX_HOST, METAX_PORT,
    M_TRUE, M_FALSE, M_META_TYPE, M_STRING_TYPE, M_COLL_COMPOSE,
    T_USER, T_GROUP, T_SERVER, T_PERMISSION, T_SESSION, T_AUDIT, T_ROOT,
    PAM_ROOT,
)

# ── HTTP/2 client ──────────────────────────────────────────────────────────────
c = httpx.Client(
    base_url=f"https://{METAX_HOST}:{METAX_PORT}",
    http2=True, verify=False, timeout=10.0,
)

def save(data: dict, uuid: str):
    r = c.post(
        "/db/save/node",
        params={"id": uuid},
        content=json.dumps(data),
        headers={"content-type": "application/json"},
    )
    r.raise_for_status()
    print(f"  ✓ saved {uuid}  ({data.get('name', {}).get('en_US', data.get('name',''))})")


# ── Property spec factory ──────────────────────────────────────────────────────
def prop(id_: str, name: str, mandatory: bool = False) -> dict:
    return {
        "id": id_,
        "name": name,
        "value_type": M_STRING_TYPE,
        "mandatory": M_TRUE if mandatory else M_FALSE,
        "default_value": "",
        "kind": "",
        "readonly": M_FALSE,
        "description": "",
        "visible": M_TRUE,
        "visible_in_list_view": M_TRUE,
        "enable_internalization": M_FALSE,
    }

# ── Collection spec factory ────────────────────────────────────────────────────
def coll(id_: str, name: str, element_type: str) -> dict:
    return {
        "id": id_,
        "name": name,
        "element_type": element_type,
        "kind": M_COLL_COMPOSE,
        "description": "",
        "symmetric": "",
    }

# ── Type object factory ────────────────────────────────────────────────────────
def make_type(uuid: str, id_: str, name: str,
              props: list, colls: list) -> dict:
    return {
        "type": M_META_TYPE,
        "uuid": uuid,
        "name": {"en_US": name},
        "id": id_,
        "description": f"PAM Bastion — {name}",
        "properties": props,
        "collections": colls,
        "values": [],
        "methods": [],
        "literal": M_FALSE,
        "vcs_enabled": M_FALSE,
        "discussion_enabled": M_FALSE,
    }


def main():
    #print("Creating PAM type objects in Metax2...\n")

    ## ── pam-user ───────────────────────────────────────────────────────────────
    #save(make_type(T_USER, "pam-user", "PAM User",
    #    props=[
    #        prop("name",           "Name",           mandatory=True),
    #        prop("username",       "Linux username",  mandatory=True),
    #        prop("totp_secret",    "TOTP Secret",     mandatory=True),
    #        prop("ssh_public_key", "SSH Public Key",  mandatory=True),
    #    ],
    #    colls=[
    #        coll("groups", "Groups", T_GROUP),
    #    ],
    #), T_USER)

    ## ── pam-group ──────────────────────────────────────────────────────────────
    #save(make_type(T_GROUP, "pam-group", "PAM Group",
    #    props=[
    #        prop("name", "Group Name", mandatory=True),
    #    ],
    #    colls=[
    #        coll("members",     "Members",     T_USER),
    #        coll("permissions", "Permissions", T_PERMISSION),
    #    ],
    #), T_GROUP)

    ## ── pam-server ─────────────────────────────────────────────────────────────
    #save(make_type(T_SERVER, "pam-server", "PAM Server",
    #    props=[
    #        prop("name",         "Display Name", mandatory=True),
    #        prop("host",         "Hostname / IP", mandatory=True),
    #        prop("port",         "SSH Port"),
    #        prop("bastion_user", "Bastion Username"),
    #        prop("bootstrapped", "Bootstrapped (yes/no)"),
    #    ],
    #    colls=[],
    #), T_SERVER)

    ## ── pam-permission ─────────────────────────────────────────────────────────
    #save(make_type(T_PERMISSION, "pam-permission", "PAM Permission",
    #    props=[
    #        prop("name",       "Description"),
    #        prop("group",      "Group UUID",  mandatory=True),
    #        prop("server",     "Server UUID", mandatory=True),
    #        prop("allow_sudo", "Allow Sudo (true/false)"),
    #    ],
    #    colls=[],
    #), T_PERMISSION)

    ## ── pam-session ────────────────────────────────────────────────────────────
    #save(make_type(T_SESSION, "pam-session", "PAM Session",
    #    props=[
    #        prop("name",        "Name"),
    #        prop("user",        "User UUID"),
    #        prop("server",      "Server UUID"),
    #        prop("started_at",  "Started At"),
    #        prop("ended_at",    "Ended At"),
    #        prop("ttyrec_path", "Recording Path"),
    #    ],
    #    colls=[],
    #), T_SESSION)

    ## ── pam-audit ──────────────────────────────────────────────────────────────
    #save(make_type(T_AUDIT, "pam-audit", "PAM Audit Record",
    #    props=[
    #        prop("name",      "Name"),
    #        prop("timestamp", "Timestamp"),
    #        prop("user",      "User UUID"),
    #        prop("action",    "Action"),
    #        prop("server",    "Server UUID"),
    #        prop("result",    "Result"),
    #    ],
    #    colls=[],
    #), T_AUDIT)

    ## ── pam-root (container type) ──────────────────────────────────────────────
    #save(make_type(T_ROOT, "pam-root", "PAM Root",
    #    props=[
    #        prop("name", "Name"),
    #    ],
    #    colls=[
    #        coll("users",       "Users",       T_USER),
    #        coll("groups",      "Groups",      T_GROUP),
    #        coll("servers",     "Servers",     T_SERVER),
    #        coll("permissions", "Permissions", T_PERMISSION),
    #        coll("sessions",    "Sessions",    T_SESSION),
    #        coll("audit",       "Audit Log",   T_AUDIT),
    #    ],
    #), T_ROOT)

    #print()

    # ── pam-root instance (singleton) ──────────────────────────────────────────
    print("Creating PAM root container instance...")
    # Check if already exists
    try:
        existing = c.get("/db/get", params={"id": PAM_ROOT})
        if existing.status_code == 200:
            print(f"  ✓ PAM root already exists ({PAM_ROOT}) — skipping")
        else:
            raise ValueError("not found")
    except Exception:
        root_obj = {
            "type": T_ROOT,
            "uuid": PAM_ROOT,
            "name": "PAM Root",
            "users": [],
            "groups": [],
            "servers": [],
            "permissions": [],
            "sessions": [],
            "audit": [],
        }
        save(root_obj, PAM_ROOT)

    print("\n\033[32m✓ Setup complete!\033[0m")
    print(f"\nPAM Root UUID: {PAM_ROOT}")
    print("Open Mani in your browser and navigate to this UUID to manage PAM objects.")
    print("\nNext steps:")
    print("  1. Create PAM users/groups/servers/permissions via Mani or CLI")
    print("  2. sudo python3 sync_daemon.py &   (syncs Linux users from Metax2)")
    print("  3. Configure sshd: run install.sh")
    print("  4. Add bastion SSH key: ssh-keygen -t ed25519 -f /var/pam/bastion_ed25519")


if __name__ == "__main__":
    import urllib3; urllib3.disable_warnings()
    main()
