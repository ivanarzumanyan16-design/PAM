#!/usr/bin/env python3
"""
Скрипт для ручной расшифровки sudo паролей.
Использование: 
  python3 decrypt_pass.py <UUID_сервера>
  или
  python3 decrypt_pass.py <зашифрованная_строка>
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metax_client import decrypt_secret, get_server_sudo_password, db_get

def main():
    if len(sys.argv) != 2:
        print("Использование: python3 decrypt_pass.py <UUID_сервера или зашифрованная_строка>")
        sys.exit(1)
        
    arg = sys.argv[1]
    
    # Токены Fernet обычно начинаются с gAAAAAB
    if arg.startswith("gAAAAAB"): 
        try:
            plain = decrypt_secret(arg)
            print("Расшифрованный пароль:")
            print(f"\033[1;32m{plain}\033[0m")
        except Exception as e:
            print(f"\033[1;31mОшибка расшифровки:\033[0m {e}")
    else:
        # Предполагаем, что это UUID
        try:
            # Пытаемся получить имя сервера для красоты
            try:
                srv = db_get(arg)
                name = srv.get("name", "Unknown")
            except:
                name = "Unknown"
                
            plain = get_server_sudo_password(arg)
            if plain:
                print(f"Пароль для сервера \033[1m{name}\033[0m ({arg}):")
                print(f"\033[1;32m{plain}\033[0m")
            else:
                print(f"\033[1;33mПароль не найден или ошибка расшифровки для {arg}\033[0m")
        except Exception as e:
            print(f"\033[1;31mОшибка:\033[0m {e}")

if __name__ == "__main__":
    main()

