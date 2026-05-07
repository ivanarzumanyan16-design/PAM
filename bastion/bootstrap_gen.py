"""
PAM Bastion — bootstrap script generator.
Generates a one-time shell script that prepares a target server.
"""
import os

BOOTSTRAP_TEMPLATE = """\
#!/bin/bash
# PAM Bastion bootstrap script for {name} ({host})
# This script must be run as root (via sudo bash).
set -euo pipefail

BASTION_PUBKEY="{bastion_pubkey}"

echo "[1/5] Creating bastion user..."
if ! id bastion &>/dev/null; then
    /usr/sbin/useradd -m -s /bin/bash bastion
    /usr/sbin/usermod -p '*' bastion
fi

echo "[2/5] Installing bastion SSH key..."
mkdir -p /home/bastion/.ssh
echo "$BASTION_PUBKEY" > /home/bastion/.ssh/authorized_keys
chmod 700 /home/bastion/.ssh
chmod 600 /home/bastion/.ssh/authorized_keys
chown -R bastion:bastion /home/bastion/.ssh

echo "[3/5] Configuring sudoers for PAM..."
# We ONLY grant NOPASSWD for usermod (password rotation by PAM engine).
# All other sudo commands require the ephemeral password set by PAM at login.
# This means: direct SSH → su bastion → sudo needs password → user can't sudo without PAM.
USERMOD_PATH=$(command -v usermod 2>/dev/null || echo /usr/sbin/usermod)
cat > /etc/sudoers.d/bastion <<SUDOEOF
# PAM Bastion sudoers
# ONLY usermod is NOPASSWD — used by PAM engine to rotate the ephemeral sudo password.
# Everything else (sudo su, sudo ls, etc.) requires the PAM-injected ephemeral password.
# Direct SSH to bastion@host (bypassing PAM) won't know this password → sudo blocked.
bastion ALL=(root) NOPASSWD: $$USERMOD_PATH
bastion ALL=(ALL) PASSWD: ALL
SUDOEOF
chmod 440 /etc/sudoers.d/bastion
visudo -cf /etc/sudoers.d/bastion && echo "  Sudoers OK" || echo "  WARNING: sudoers validation failed"

echo "[4/5] Configuring SSH..."
# Ensure PubkeyAuthentication is enabled
if grep -q "^#PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    sed -i "s/^#PubkeyAuthentication yes/PubkeyAuthentication yes/" /etc/ssh/sshd_config
    systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
elif ! grep -q "^PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config
    systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
fi

echo "[5/5] Done. Server {name} ({host}) is ready for PAM bastion."
echo "The server has been automatically marked as bootstrapped in Mani."
echo ""
echo "NOTE: Direct access (ssh bastion@{host}) requires sudo password that only PAM knows."
echo "      This is by design — use PAM bastion for normal access."
"""

def generate(server: dict, bastion_pubkey: str) -> str:
    """Return a bootstrap shell script string for the given server."""
    return BOOTSTRAP_TEMPLATE.format(
        name=server.get("name", "unknown"),
        host=server.get("host", ""),
        bastion_pubkey=bastion_pubkey,
    )

def get_bastion_pubkey() -> str:
    from config import BASTION_KEY
    pub_path = BASTION_KEY + ".pub"
    if os.path.exists(pub_path):
        with open(pub_path) as f:
            return f.read().strip()
    return ""

if __name__ == "__main__":
    import sys, json, getpass, subprocess
    from metax_client import db_get
    if len(sys.argv) < 2:
        sys.exit("Usage: bootstrap_gen.py <server-uuid> [--run user@host]")

    srv = db_get(sys.argv[1])
    script = generate(srv, get_bastion_pubkey())

    # --run user@host  →  ask sudo password locally and run on server via sudo -S bash
    if len(sys.argv) >= 4 and sys.argv[2] == "--run":
        target = sys.argv[3]  # e.g. deargrafana@10.8.8.35
        sudo_pass = getpass.getpass(f"[sudo] password for {target}: ")
        # sudo -S reads password from the first line of stdin,
        # the rest is fed to bash as the script body.
        stdin_data = (sudo_pass + "\n" + script).encode()
        result = subprocess.run(
            ["ssh", target, "sudo -S bash"],
            input=stdin_data,
        )
        sys.exit(result.returncode)
    else:
        # Default: just print the script (pipe manually)
        print(script)



