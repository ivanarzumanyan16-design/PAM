#!/usr/bin/env python3
"""
PAM Bastion — Bootstrap HTTP Server (Refactored v2).
"""
import sys, os, json, logging
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))

import metax_client as mx
from bootstrap_gen import generate, get_bastion_pubkey
from config import BOOTSTRAP_PORT, PUBLIC_VIEWER_HOST, TOKEN_TTL_MINUTES

log = logging.getLogger("bootstrap-srv")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [bootstrap-srv] %(message)s")

class BootstrapHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): log.info(fmt % a)
    
    def _res(self, code, ctype, body):
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body_bytes))); self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        if self.path == "/health": return self._res(200, "text/plain", "OK\n")
        if self.path.startswith("/bootstrap/"):
            tok = self.path.split("/bootstrap/")[1].split("?")[0].rstrip("/")
            try: obj = mx.db_get(tok) if tok else None
            except: obj = None
            
            if not obj or obj.get("type") != "bootstrap_token": 
                return self._res(404, "text/plain", "Not found\n")
            
            try:
                srv = mx.db_get(obj["server"])
                script = generate(srv, get_bastion_pubkey(), bootstrap_token=tok, register_url=f"http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/register-sudo-pass")
                if not mx.consume_bootstrap_token(tok, obj["server"]): 
                    return self._res(410, "text/plain", "Token expired or already used\n")
                log.info(f"Served script for {srv.get('name')} to {self.client_address[0]}")
                return self._res(200, "text/x-shellscript", script)
            except Exception as e:
                log.error(f"Gen failed: {e}"); return self._res(500, "text/plain", "Server Error\n")
        self._res(404, "text/plain", "Not found\n")

    def do_POST(self):
        if self.path.startswith("/gen-token/"):
            uid = self.path.split("/gen-token/")[1].split("?")[0].rstrip("/")
            try:
                tok = mx.create_bootstrap_token(uid)
                return self._res(200, "application/json", json.dumps({"ok": True, "server": uid, "token": tok, "command": f"curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{tok} | sudo bash"}))
            except: return self._res(404, "application/json", '{"error":"Server not found"}')
            
        if self.path == "/register-sudo-pass":
            tok = self.headers.get("Authorization", "")[7:]
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
                sid, pw = data.get("server_uuid"), data.get("password")
                obj = mx.db_get(tok) if tok else None
                if not obj or obj.get("server") != sid: 
                    return self._res(403, "application/json", '{"error":"Invalid token for this server"}')
                mx.set_server_sudo_password(sid, pw)
                log.info(f"Registered initial sudo password for server {sid}")
                return self._res(200, "application/json", '{"ok":true}')
            except Exception as e: 
                log.error(f"Register pass failed: {e}")
                return self._res(400, "application/json", '{"error":"Bad request or DB error"}')
        self._res(404, "text/plain", "Not found\n")

def cli_gen_token(uid: str):
    tok = mx.create_bootstrap_token(uid)
    try: n = mx.db_get(uid).get("name", uid)
    except: n = uid
    print(f"\n✅ Bootstrap token created for '{n}' (expires in {TOKEN_TTL_MINUTES}m)\nRun on target:\n  curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{tok} | sudo bash\n")

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "gen-token": cli_gen_token(sys.argv[2])
    elif len(sys.argv) == 1:
        if os.geteuid() != 0: sys.exit("Must run as root")
        log.info(f"Listening on 0.0.0.0:{BOOTSTRAP_PORT}")
        try: HTTPServer(("0.0.0.0", BOOTSTRAP_PORT), BootstrapHandler).serve_forever()
        except KeyboardInterrupt: log.info("Shutting down")
    else: print("Usage: python3 bootstrap_server_v2.py [gen-token <uuid>]")
