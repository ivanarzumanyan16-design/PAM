"""
PAM Bastion — bootstrap script generator.
Generates a one-time shell script that prepares a target server.
"""
import os

BOOTSTRAP_TEMPLATE = """\
#!/bin/bash
# PAM Bastion bootstrap script for {name} ({host})
# This script must be run as root (via sudo -S bash).
set -euo pipefail

BASTION_PUBKEY="{bastion_pubkey}"

echo "[1/4] Creating bastion user..."
if ! id bastion &>/dev/null; then
    /usr/sbin/useradd -m -s /bin/bash bastion
    /usr/sbin/usermod -p '*' bastion
fi

echo "[2/4] Installing bastion SSH key..."
mkdir -p /home/bastion/.ssh
echo "$BASTION_PUBKEY" > /home/bastion/.ssh/authorized_keys
chmod 700 /home/bastion/.ssh
chmod 600 /home/bastion/.ssh/authorized_keys
chown -R bastion:bastion /home/bastion/.ssh

echo "[3/4] Configuring sudoers and SSH..."
tee /etc/sudoers.d/bastion << 'EOF' > /dev/null
# PAM Bastion: allow sudo with password (ephemeral password injected by bastion)
bastion ALL=(ALL) PASSWD: ALL
# Allow bastion to set its own password (ephemeral sudo)
bastion ALL=(root) NOPASSWD: /usr/sbin/chpasswd
EOF
chmod 440 /etc/sudoers.d/bastion

# Ensure PubkeyAuthentication is enabled
if grep -q "^#PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    sed -i "s/^#PubkeyAuthentication yes/PubkeyAuthentication yes/" /etc/ssh/sshd_config
    systemctl restart sshd || service ssh restart
elif ! grep -q "^PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config
    systemctl restart sshd || service ssh restart
fi

echo "[4/4] Done. Server {name} ({host}) is ready for PAM bastion."
echo "The server has been automatically marked as bootstrapped in Mani."
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


