#!/usr/bin/env bash
# PAM Bastion — system installation script.
# Run as root on the bastion host.
set -euo pipefail

BASTION_DIR="$(cd "$(dirname "$0")" && pwd)"
BASTION_PY="$BASTION_DIR/bastion.py"
KEY_DIR="/var/pam"
AUTH_KEYS="/etc/pam_authorized_keys"
SYNC_SERVICE="/etc/systemd/system/pam-sync.service"
SSHD_CONF="/etc/ssh/sshd_config.d/pam_bastion.conf"

echo "=== PAM Bastion installer ==="
echo "Bastion dir: $BASTION_DIR"
echo

# 1. Create bastion key directory
echo "[1/6] Setting up /var/pam..."
mkdir -p "$KEY_DIR/recordings"
chmod 700 "$KEY_DIR"

# 2. Generate bastion SSH key (used for outgoing connections)
if [ ! -f "$KEY_DIR/bastion_ed25519" ]; then
    echo "[2/6] Generating bastion SSH key..."
    ssh-keygen -t ed25519 -N "" -C "pam-bastion" -f "$KEY_DIR/bastion_ed25519"
    echo "Bastion public key (install on target servers via bootstrap script):"
    cat "$KEY_DIR/bastion_ed25519.pub"
else
    echo "[2/6] Bastion key already exists — skipping."
fi
echo

# 3. Create empty authorized_keys file
echo "[3/6] Creating shared authorized_keys file..."
touch "$AUTH_KEYS"
chmod 644 "$AUTH_KEYS"
chown root:root "$AUTH_KEYS"

# 4. Write sshd_config snippet
echo "[4/6] Writing sshd config..."
cat > "$SSHD_CONF" << EOF
# PAM Bastion — SSH configuration
# All PAM-managed users share authorized_keys with command= restriction.

# Point all matching users at the shared authorized_keys
Match Group pam_users
    AuthorizedKeysFile $AUTH_KEYS
    ForceCommand python3 $BASTION_PY
    AllowTcpForwarding no
    X11Forwarding no
    PermitTTY yes
EOF

# Validate sshd config before reloading
if sshd -t 2>/dev/null; then
    systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
    echo "  sshd config reloaded."
else
    echo "  WARNING: sshd config validation failed — not reloading. Check $SSHD_CONF"
fi

# 5. Create pam_users group (used by Match Group above)
echo "[5/6] Ensuring pam_users group exists..."
getent group pam_users &>/dev/null || groupadd pam_users
echo "  Group pam_users created/verified."

# 6. Install systemd unit for sync daemon
echo "[6/6] Installing sync daemon service..."
cat > "$SYNC_SERVICE" << EOF
[Unit]
Description=PAM Bastion — Metax2 sync daemon
After=network.target

[Service]
Type=simple
ExecStart=python3 $BASTION_DIR/sync_daemon.py
Restart=always
RestartSec=5
WorkingDirectory=$BASTION_DIR
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pam-sync.service
echo "  pam-sync.service enabled and started."

echo
echo "=== Installation complete! ==="
echo
echo "Bastion public key (for target servers):"
cat "$KEY_DIR/bastion_ed25519.pub"
echo
echo "Next steps:"
echo "  1. Run: python3 $BASTION_DIR/setup_types.py"
echo "  2. Add users: python3 $BASTION_DIR/pam_cli.py user add --username alice --key 'ssh-ed25519 ...'"
echo "  3. Add servers: python3 $BASTION_DIR/pam_cli.py server add --name prod --host 10.0.0.1"
echo "  4. Bootstrap target: python3 $BASTION_DIR/pam_cli.py bootstrap --server <uuid> | ssh root@host bash"
echo "  5. Set permissions: python3 $BASTION_DIR/pam_cli.py perm add --group <uuid> --server <uuid> [--sudo]"
