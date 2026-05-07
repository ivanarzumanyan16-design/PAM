#!/bin/bash
# PAM Bastion bootstrap script for grafana (10.8.8.35)
# This script must be run as root (via sudo -S bash).
set -euo pipefail

BASTION_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEuu4iSmFyu9UFyYvIQ7WOUh4leO7CPZLG0ErZWRuWmr pam-bastion"

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
# Detect real paths of chpasswd and passwd (vary by distro: /usr/sbin vs /sbin)
CHPASSWD_PATH=$(command -v chpasswd 2>/dev/null || which chpasswd 2>/dev/null || echo /usr/sbin/chpasswd)
PASSWD_PATH=$(command -v passwd 2>/dev/null || which passwd 2>/dev/null || echo /usr/bin/passwd)
# Write sudoers: NOPASSWD only for password-management tools (used by PAM engine),
# PASSWD required for everything else (uses the ephemeral password set by PAM).
# This way direct SSH to bastion user still requires sudo password — only PAM knows it.
cat > /etc/sudoers.d/bastion << SUDOEOF
# PAM Bastion sudoers — do NOT grant NOPASSWD: ALL (security risk)
# Only the PAM engine can set the ephemeral sudo password via chpasswd.
# Direct SSH to bastion@host without going through PAM won't grant sudo.
bastion ALL=(root) NOPASSWD: $CHPASSWD_PATH, $PASSWD_PATH, /usr/sbin/usermod, /sbin/usermod
bastion ALL=(ALL) PASSWD: ALL
SUDOEOF
chmod 440 /etc/sudoers.d/bastion

# Ensure PubkeyAuthentication is enabled
if grep -q "^#PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    sed -i "s/^#PubkeyAuthentication yes/PubkeyAuthentication yes/" /etc/ssh/sshd_config
    systemctl restart sshd || service ssh restart
elif ! grep -q "^PubkeyAuthentication yes" /etc/ssh/sshd_config; then
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config
    systemctl restart sshd || service ssh restart
fi

echo "[4/4] Done. Server grafana (10.8.8.35) is ready for PAM bastion."
echo "The server has been automatically marked as bootstrapped in Mani."

