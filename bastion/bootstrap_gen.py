"""
PAM Bastion — bootstrap script generator.
Generates a one-time shell script that prepares a target server.
"""
import os

BOOTSTRAP_TEMPLATE = r"""#!/bin/bash
# PAM Bastion bootstrap script for {name} ({host})
# This script must be run as root (via: ssh root@{host} 'bash -s' < script.sh)
set -euo pipefail

BASTION_PUBKEY="{bastion_pubkey}"
PAM_USER="{bastion_user}"
SERVER_UUID="{server_uuid}"

echo "=== PAM Bastion Bootstrap: {name} ({host}) ==="
echo ""

# ── Step 1: Create PAM system user ────────────────────────────────────────────
echo "[1/4] Creating PAM system user ($PAM_USER)..."
if ! id "$PAM_USER" &>/dev/null; then
    /usr/sbin/useradd -m -s /bin/bash "$PAM_USER"
    echo "  Created user: $PAM_USER"
else
    echo "  User already exists: $PAM_USER"
fi

# ── Step 2: Install bastion SSH key for PAM user ───────────────────────────────
echo "[2/4] Installing bastion SSH key for $PAM_USER..."
mkdir -p /home/$PAM_USER/.ssh
# Append key if not already present (idempotent)
if ! grep -qF "$BASTION_PUBKEY" /home/$PAM_USER/.ssh/authorized_keys 2>/dev/null; then
    echo "$BASTION_PUBKEY" >> /home/$PAM_USER/.ssh/authorized_keys
    echo "  SSH key added to $PAM_USER"
else
    echo "  SSH key already present for $PAM_USER"
fi
chmod 700 /home/$PAM_USER/.ssh
chmod 600 /home/$PAM_USER/.ssh/authorized_keys
chown -R $PAM_USER:$PAM_USER /home/$PAM_USER/.ssh

# ── Step 3: Install bastion SSH key for root ───────────────────────────────────
# Root SSH access is used ONLY for ephemeral password rotation:
#   ssh root@host "usermod -p '<hash>' <pam_user>"
# This does NOT allow interactive root login from bastion sessions.
echo "[3/4] Installing bastion SSH key for root (password rotation)..."
mkdir -p /root/.ssh
if ! grep -qF "$BASTION_PUBKEY" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "$BASTION_PUBKEY" >> /root/.ssh/authorized_keys
    echo "  SSH key added to root"
else
    echo "  SSH key already present for root"
fi
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys

# Ensure root SSH login is allowed (required for password rotation)
SSHD_CFG=/etc/ssh/sshd_config
if grep -q "^PermitRootLogin no" "$SSHD_CFG" 2>/dev/null; then
    sed -i "s/^PermitRootLogin no/PermitRootLogin prohibit-password/" "$SSHD_CFG"
    echo "  Set PermitRootLogin prohibit-password (key-only, no password login)"
elif ! grep -q "^PermitRootLogin" "$SSHD_CFG" 2>/dev/null; then
    echo "PermitRootLogin prohibit-password" >> "$SSHD_CFG"
    echo "  Added PermitRootLogin prohibit-password"
else
    echo "  PermitRootLogin already configured: $(grep '^PermitRootLogin' $SSHD_CFG)"
fi

# ── Step 4: Configure SSH (pubkey auth) ───────────────────────────────────────
echo "[4/4] Configuring SSH..."
if grep -q "^#PubkeyAuthentication yes" "$SSHD_CFG"; then
    sed -i "s/^#PubkeyAuthentication yes/PubkeyAuthentication yes/" "$SSHD_CFG"
elif ! grep -q "^PubkeyAuthentication yes" "$SSHD_CFG"; then
    echo "PubkeyAuthentication yes" >> "$SSHD_CFG"
fi
systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
echo "  SSH restarted"

echo ""
echo "=== Bootstrap complete! ==="
echo "  Server:      {name} ({host})"
echo "  PAM user:    $PAM_USER"
echo "  Root access: bastion key installed in /root/.ssh/authorized_keys"
echo ""
echo "Next: verify with:"
echo "  python3 pam_cli.py server check-sudo --host {host}"
"""

def generate(server: dict, bastion_pubkey: str, **kwargs) -> str:
    """Return a bootstrap shell script string for the given server."""
    return BOOTSTRAP_TEMPLATE.format(
        name=server.get("name", "unknown"),
        host=server.get("host", ""),
        bastion_pubkey=bastion_pubkey,
        bastion_user=server.get("bastion_user", "bastion"),
        server_uuid=server.get("uuid", ""),
    )

def get_bastion_pubkey() -> str:
    from config import BASTION_KEY
    pub_path = BASTION_KEY + ".pub"
    if os.path.exists(pub_path):
        with open(pub_path) as f:
            return f.read().strip()
    return ""

if __name__ == "__main__":
    import sys, getpass, subprocess

    if len(sys.argv) < 2:
        sys.exit("Usage: bootstrap_gen.py <server-uuid> [--run root@host]")

    sys.path.insert(0, os.path.dirname(__file__))
    from metax_client import db_get

    srv = db_get(sys.argv[1])
    script = generate(srv, get_bastion_pubkey())

    # --run root@host  →  pipe script to ssh
    if len(sys.argv) >= 4 and sys.argv[2] == "--run":
        target = sys.argv[3]
        result = subprocess.run(
            ["ssh", target, "bash -s"],
            input=script.encode(),
        )
        sys.exit(result.returncode)
    else:
        print(script)
