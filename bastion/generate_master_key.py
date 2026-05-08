#!/usr/bin/env python3
"""
PAM Bastion — one-time master key generator.
Run this ONCE on the bastion server during initial setup.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from cryptography.fernet import Fernet
from config import MASTER_KEY_PATH

def main():
    if os.path.exists(MASTER_KEY_PATH):
        print(f"[!] Key already exists: {MASTER_KEY_PATH}")
        print("    Delete it manually if you want to regenerate (WARNING: all stored passwords will be lost).")
        sys.exit(1)

    os.makedirs(os.path.dirname(MASTER_KEY_PATH), exist_ok=True)
    key = Fernet.generate_key()

    with open(MASTER_KEY_PATH, "wb") as f:
        f.write(key + b"\n")

    os.chmod(MASTER_KEY_PATH, 0o400)
    print(f"[+] Master key generated: {MASTER_KEY_PATH}")
    print(f"[+] Permissions set to 400 (read-only by owner)")
    print(f"[!] IMPORTANT: Back up this file securely. Loss = loss of all sudo passwords.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("This script must be run as root.")
    main()
