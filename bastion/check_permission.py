
import sys
sys.path.insert(0, '.')
from metax_client import *
 
def main():
    if len(sys.argv) == 3:
        username = sys.argv[1]
        ip = sys.argv[2]
    else:
        username = input("Enter username: ").strip()
        ip = input("Enter IP: ").strip()
 
    u = get_user_by_username(username)
    s = get_server_by_name(ip)
    print('Permission:', check_permission(u['uuid'], s['uuid']))
 
if __name__ == '__main__':
    main()
 

