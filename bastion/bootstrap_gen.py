"""
PAM Bastion — bootstrap script generator.
Generates a one-time shell script that prepares a target server.
"""
import os

# Raw string (r\"\"\") prevents Python from interpreting \n, \t, etc.
# Only {placeholders} are substituted by .format(). All $BASH_VARS are untouched.
BOOTSTRAP_TEMPLATE = r"""#!/bin/bash
# PAM Bastion bootstrap script for {name} ({host})
# This script must be run as root (via sudo bash).
set -euo pipefail

BASTION_PUBKEY="{bastion_pubkey}"
PAM_USER="{bastion_user}"
SERVER_UUID="{server_uuid}"
BASTION_REGISTER_URL="{register_url}"
BOOTSTRAP_TOKEN="{bootstrap_token}"

echo "[1/6] Creating PAM system user ($PAM_USER)..."
if ! id "$PAM_USER" &>/dev/null; then
    /usr/sbin/useradd -m -s /bin/bash "$PAM_USER"
fi

echo "[2/6] Installing bastion SSH key for $PAM_USER..."
mkdir -p /home/$PAM_USER/.ssh
echo "$BASTION_PUBKEY" > /home/$PAM_USER/.ssh/authorized_keys
chmod 700 /home/$PAM_USER/.ssh
chmod 600 /home/$PAM_USER/.ssh/authorized_keys
chown -R $PAM_USER:$PAM_USER /home/$PAM_USER/.ssh

echo "[3/6] Setting initial sudo password..."
INIT_PASS=$(openssl rand -base64 32 | tr -d '\n=')
/usr/sbin/usermod -p "$(openssl passwd -6 "$INIT_PASS")" "$PAM_USER"

echo "[4/6] Configuring sudoers for PAM ($PAM_USER)..."
rm -f /etc/sudoers.d/bastion /etc/sudoers.d/pam_bastion
# Note: single-quoted heredoc ('SUDOEOF') prevents bash expanding $PAM_USER inside
cat > /etc/sudoers.d/pam_bastion << 'SUDOEOF'
# PAM Bastion sudoers — managed automatically, do not edit.
# No NOPASSWD: bastion engine authenticates with the current known password.
SUDOEOF
echo "$PAM_USER ALL=(ALL) PASSWD: ALL" >> /etc/sudoers.d/pam_bastion
chmod 440 /etc/sudoers.d/pam_bastion
visudo -cf /etc/sudoers.d/pam_bastion && echo "  Sudoers OK" || echo "  WARNING: sudoers validation failed"

echo "[5/6] Configuring SSH..."
if grep -q "^#PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    sed -i "s/^#PubkeyAuthentication yes/PubkeyAuthentication yes/" /etc/ssh/sshd_config
    systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
elif ! grep -q "^PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config
    systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
fi

echo "[6/6] Registering initial sudo password with PAM..."
if [ -n "$BASTION_REGISTER_URL" ] && [ -n "$BOOTSTRAP_TOKEN" ]; then
    PAYLOAD=$(printf '{{"server_uuid":"%s","password":"%s"}}' "$SERVER_UUID" "$INIT_PASS")
    curl -k -sf -X POST "$BASTION_REGISTER_URL" \
      -H "Authorization: Bearer $BOOTSTRAP_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      && echo "  Password registered OK" \
      || echo "  WARNING: Could not register — run on bastion: pam_cli.py server reset-sudo --host {host}"
else
    echo "  WARNING: No registration URL/token — run on bastion: pam_cli.py server reset-sudo --host {host}"
fi

echo ""
echo "Done. Server {name} ({host}) is ready for PAM bastion."
echo "PAM system user: $PAM_USER"
echo "NOTE: No NOPASSWD — bastion uses stored encrypted password for sudo rotation."
"""


def generate(server: dict, bastion_pubkey: str, bootstrap_token: str = "", register_url: str = "") -> str:
    """Return a bootstrap shell script string for the given server."""
    return BOOTSTRAP_TEMPLATE.format(
        name=server.get("name", "unknown"),
        host=server.get("host", ""),
        bastion_pubkey=bastion_pubkey,
        bastion_user=server.get("bastion_user", "bastion"),
        server_uuid=server.get("uuid", ""),
        bootstrap_token=bootstrap_token,
        register_url=register_url,
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
    from metax_client import db_get, create_bootstrap_token
    from config import BOOTSTRAP_PORT, PUBLIC_VIEWER_HOST

    if len(sys.argv) < 2:
        sys.exit("Usage: bootstrap_gen.py <server-uuid> [--run user@host]")

    srv = db_get(sys.argv[1])
    server_uuid = srv.get("uuid", sys.argv[1])

    # Generate a fresh bootstrap token so the password can be auto-registered
    token = create_bootstrap_token(server_uuid)
    reg_url = f"http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/register-sudo-pass"
    script = generate(srv, get_bastion_pubkey(), bootstrap_token=token, register_url=reg_url)

    # --run user@host  →  run on server via SSH
    if len(sys.argv) >= 4 and sys.argv[2] == "--run":
        target = sys.argv[3]
        sudo_pass = getpass.getpass(f"[sudo] password for {target}: ")
        stdin_data = (sudo_pass + "\n" + script).encode()
        result = subprocess.run(["ssh", target, "sudo -S bash"], input=stdin_data)
        sys.exit(result.returncode)
    else:
        print(script)

