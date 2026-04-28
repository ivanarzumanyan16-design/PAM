#!/usr/bin/env python3
"""
PAM Bastion — Bootstrap token HTTP server.

Serves one-time bootstrap shell scripts to target servers.
Run as root on the bastion host alongside sync_daemon.

Endpoints:
  GET  /bootstrap/<token>       → returns shell script, marks server bootstrapped
  POST /gen-token/<server-uuid> → generates token, returns JSON with curl command
  GET  /health                  → 200 OK

Tokens are created via:
  python3 pam_cli.py server gen-token --server <uuid>
or directly:
  python3 bootstrap_server.py gen-token <server-uuid>
"""
import sys, os, json, logging, ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import metax_client as mx
from bootstrap_gen import generate, get_bastion_pubkey
from config import BOOTSTRAP_PORT, PUBLIC_VIEWER_HOST

logging.basicConfig(level=logging.INFO, format="%(asctime)s [bootstrap-srv] %(message)s")
log = logging.getLogger("bootstrap-srv")


# ── Request handler ────────────────────────────────────────────────────────────

class BootstrapHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log.info(format % args)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, "text/plain", b"OK\n")
            return

        if self.path.startswith("/bootstrap/"):
            token = self.path[len("/bootstrap/"):]
            token = token.split("?")[0].rstrip("/")
            self._handle_bootstrap(token)
            return

        self._respond(404, "text/plain", b"Not found\n")

    def do_POST(self):
        """POST /gen-token/<server-uuid> → create bootstrap token, return JSON."""
        if self.path.startswith("/gen-token/"):
            server_uuid = self.path[len("/gen-token/"):].split("?")[0].rstrip("/")
            self._handle_gen_token(server_uuid)
            return
        self._respond(404, "text/plain", b"Not found\n")

    def _handle_gen_token(self, server_uuid: str):
        # Verify server exists
        try:
            srv = mx.db_get(server_uuid)
        except Exception:
            self._respond(404, "application/json",
                          json.dumps({"error": "Server not found"}).encode())
            return

        token = mx.create_bootstrap_token(server_uuid)
        from config import TOKEN_TTL_MINUTES
        cmd = f"curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{token} | sudo bash"
        body = json.dumps({
            "ok": True,
            "server": server_uuid,
            "server_name": srv.get("name", ""),
            "token": token,
            "expires_minutes": TOKEN_TTL_MINUTES,
            "command": cmd,
        })
        log.info("Generated bootstrap token for server '%s' (%s)",
                 srv.get("name"), server_uuid)
        self._respond(200, "application/json", body.encode())

    def _handle_bootstrap(self, token: str):
        client_ip = self.client_address[0]

        # Fetch token object from Metax (token IS the Metax UUID)
        obj = mx.get_bootstrap_token(token)
        if not obj or obj.get("type") != "bootstrap_token":
            log.warning("Bootstrap: unknown token from %s: %s…", client_ip, token[:8])
            self._respond(404, "text/plain", b"Token not found\n")
            return

        # Check expiry
        try:
            exp = datetime.fromisoformat(obj["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                log.warning("Bootstrap: expired token %s… from %s", token[:8], client_ip)
                self._respond(410, "text/plain", b"Token expired\n")
                return
        except Exception:
            pass

        # Check already used
        if obj.get("used") == "true":
            log.warning("Bootstrap: already-used token %s… from %s", token[:8], client_ip)
            self._respond(410, "text/plain", b"Token already used\n")
            return

        server_uuid = obj.get("server", "")
        try:
            srv = mx.db_get(server_uuid)
        except Exception as e:
            log.error("Bootstrap: cannot fetch server %s: %s", server_uuid, e)
            self._respond(500, "text/plain", b"Server record not found\n")
            return

        # Generate bootstrap shell script
        try:
            script = generate(srv, get_bastion_pubkey())
        except Exception as e:
            log.error("Bootstrap: script generation failed: %s", e)
            self._respond(500, "text/plain", b"Script generation failed\n")
            return

        # Consume token → marks server bootstrapped in Metax
        ok = mx.consume_bootstrap_token(token, server_uuid)
        if not ok:
            log.error("Bootstrap: consume_bootstrap_token failed for %s", token[:8])
            self._respond(500, "text/plain", b"Token consume failed\n")
            return

        log.info(
            "Bootstrap script served for server '%s' (%s) → client %s, token %s…",
            srv.get("name"), server_uuid, client_ip, token[:8],
        )
        self._respond(200, "text/x-shellscript", script.encode())

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    port = BOOTSTRAP_PORT
    httpd = HTTPServer(("0.0.0.0", port), BootstrapHandler)
    log.info("PAM Bootstrap server listening on 0.0.0.0:%d", port)
    log.info("Bastion public host: %s", PUBLIC_VIEWER_HOST)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        httpd.server_close()


# ── CLI shortcut: generate a token directly ────────────────────────────────────
def cli_gen_token(server_uuid: str):
    token = mx.create_bootstrap_token(server_uuid)
    try:
        srv = mx.db_get(server_uuid)
        name = srv.get("name", server_uuid)
    except Exception:
        name = server_uuid
    from config import TOKEN_TTL_MINUTES
    cmd = f"curl -k http://{PUBLIC_VIEWER_HOST}:{BOOTSTRAP_PORT}/bootstrap/{token} | sudo bash"
    print(f"\n✅ Bootstrap token created for server '{name}'")
    print(f"   Expires in: {TOKEN_TTL_MINUTES} minutes")
    print(f"\nRun this on the TARGET server:\n")
    print(f"  {cmd}\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "gen-token":
        cli_gen_token(sys.argv[2])
    elif len(sys.argv) == 1:
        if os.geteuid() != 0:
            sys.exit("bootstrap_server must run as root")
        main()
    else:
        print("Usage:")
        print("  python3 bootstrap_server.py               # start HTTP server (as root)")
        print("  python3 bootstrap_server.py gen-token <server-uuid>")

