"""
PAM Bastion — Metax2 HTTP/2 + WebSocket client.
Zero external deps beyond httpx+h2 (already installed).
WebSocket uses stdlib ssl+socket.
"""
import json, ssl, socket, hashlib, base64, struct, os, time
import httpx
from config import METAX_HOST, METAX_PORT, METAX_CERT

# ── HTTP/2 client (singleton) ──────────────────────────────────────────────────
def _make_client():
    return httpx.Client(
        base_url=f"https://{METAX_HOST}:{METAX_PORT}",
        http2=True,
        verify=False,          # self-signed cert; swap to METAX_CERT for strict
        timeout=10.0,
    )

_client = None
def client():
    global _client
    if _client is None:
        _client = _make_client()
    return _client

# ── Low-level DB API ───────────────────────────────────────────────────────────
def db_get(uuid: str) -> dict:
    r = client().get(f"/db/get", params={"id": uuid})
    r.raise_for_status()
    return json.loads(r.content)

def db_save(data: dict, uuid: str | None = None) -> str:
    params = {"id": uuid} if uuid else {}
    r = client().post(
        "/db/save/node",
        params=params,
        content=json.dumps(data),
        headers={"content-type": "application/json"},
    )
    r.raise_for_status()
    return r.json()["uuid"]

def db_save_file(content: bytes, mime_type: str, uuid: str | None = None) -> str:
    """Upload binary content to Metax. Uses a fresh client (not singleton)
    so it can have its own long timeout without affecting other calls."""
    params = {"id": uuid} if uuid else {}
    try:
        # Do NOT use the singleton client() here — it has a short timeout.
        # Large recordings need up to 2 minutes to upload.
        fresh = httpx.Client(
            base_url=f"https://{METAX_HOST}:{METAX_PORT}",
            http2=True,
            verify=False,
            timeout=120.0,
        )
        r = fresh.post(
            "/db/save/node",
            params=params,
            content=content,
            headers={"content-type": mime_type},
        )
        r.raise_for_status()
        return r.json()["uuid"]
    except Exception as e:
        print(f"[metax] db_save_file failed: {e}")
        raise

# ── PAM root helpers ───────────────────────────────────────────────────────────
def get_root() -> dict:
    from config import PAM_ROOT
    return db_get(PAM_ROOT)

def save_root(root: dict):
    from config import PAM_ROOT
    db_save(root, PAM_ROOT)

# ── Query helpers ──────────────────────────────────────────────────────────────
def get_users() -> list[dict]:
    root = get_root()
    return [db_get(u) for u in root.get("users", [])]

def get_user_by_username(username: str) -> dict | None:
    for u in get_users():
        if u.get("username") == username:
            return u
    return None

def get_user_by_uuid(uuid: str) -> dict:
    return db_get(uuid)

def get_group(uuid: str) -> dict:
    return db_get(uuid)

def get_server(uuid: str) -> dict:
    return db_get(uuid)

def get_server_by_name(name: str) -> dict | None:
    root = get_root()
    for s in root.get("servers", []):
        srv = db_get(s)
        if srv.get("name") == name or srv.get("host") == name:
            return srv
    return None

def get_permissions() -> list[dict]:
    root = get_root()
    return [db_get(p) for p in root.get("permissions", [])]

def check_permission(user_uuid: str, server_uuid: str) -> dict | None:
    """Return permission object if user has access to server, else None."""
    user_groups = set()
    root = get_root()
    for g_uuid in root.get("groups", []):
        try:
            grp = get_group(g_uuid)
            if user_uuid in grp.get("members", []):
                user_groups.add(g_uuid)
        except Exception:
            pass

    for perm in get_permissions():
        if perm.get("server") == server_uuid and perm.get("group") in user_groups:
            return perm
    return None

def create_user(username: str, totp_secret: str, ssh_public_key: str) -> str:
    from config import T_USER
    root = get_root()
    obj = {
        "type": T_USER, "name": username,
        "username": username, "totp_secret": totp_secret,
        "ssh_public_key": ssh_public_key, "groups": [],
    }
    uuid = db_save(obj)
    obj["uuid"] = uuid
    db_save(obj, uuid)
    root.setdefault("users", []).append(uuid)
    save_root(root)
    return uuid

def create_session(user_uuid: str, server_uuid: str, ttyrec_path: str) -> str:
    from config import T_SESSION
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    obj = {
        "type": T_SESSION, "name": f"session-{now}",
        "user": user_uuid, "server": server_uuid,
        "started_at": now, "ended_at": "",
        "ttyrec_path": ttyrec_path,
    }
    uuid = db_save(obj)

    try:
        from config import PUBLIC_VIEWER_HOST
        viewer_host = PUBLIC_VIEWER_HOST
    except ImportError:
        viewer_host = METAX_HOST

    obj["uuid"] = uuid
    # playback_url always uses SESSION uuid — viewer will resolve the file internally
    obj["live_url"]     = f"https://{viewer_host}:9000/live/{uuid}"
    obj["playback_url"] = f"https://{viewer_host}:9000/play_uuid/{uuid}"

    db_save(obj, uuid)
    root = get_root()
    root.setdefault("sessions", []).append(uuid)
    save_root(root)
    return uuid

def close_session(session_uuid: str, command_log: str = ""):
    sess = db_get(session_uuid)
    sess["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if command_log:
        sess["description"] = command_log

    try:
        from config import PUBLIC_VIEWER_HOST
        viewer_host = PUBLIC_VIEWER_HOST
    except ImportError:
        viewer_host = METAX_HOST

    # Upload recording to Metax
    ttyrec_path = sess.get("ttyrec_path")
    if ttyrec_path and os.path.exists(ttyrec_path):
        try:
            file_size = os.path.getsize(ttyrec_path)
            print(f"[metax] Found recording: {ttyrec_path} ({file_size} bytes)")
            with open(ttyrec_path, "rb") as f:
                content = f.read()
            print(f"[metax] Uploading {file_size} bytes to Metax...")
            # Upload as plain text — asciicast v2 is newline-delimited JSON
            file_uuid = db_save_file(content, "text/plain")
            print(f"[metax] Upload OK. File UUID: {file_uuid}")
            sess["ttyrec_uuid"] = file_uuid
            # playback_url points to the SESSION uuid (viewer resolves file internally)
            sess["playback_url"] = f"https://{viewer_host}:9000/play_uuid/{session_uuid}"
            print(f"[metax] playback_url: {sess['playback_url']}")
        except Exception as e:
            print(f"\r\n[metax] ERROR during recording upload: {e}\r\n")
            import traceback; traceback.print_exc()
    else:
        print(f"[metax] Recording file not found: {ttyrec_path}")

    db_save(sess, session_uuid)
    print(f"[metax] Session {session_uuid} closed.")

# ── Bootstrap token helpers ───────────────────────────────────────────────────
def create_bootstrap_token(server_uuid: str) -> str:
    """Create a one-time bootstrap token. Uses Metax UUID as the token."""
    import time as _time
    from config import TOKEN_TTL_MINUTES
    
    expires_at = _time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        _time.gmtime(_time.time() + TOKEN_TTL_MINUTES * 60)
    )
    obj = {
        "type": "bootstrap_token",
        "server": server_uuid,
        "expires_at": expires_at,
        "used": "false",
    }
    
    # Save to Metax and let it generate a valid UUID
    token_uuid = db_save(obj)
    
    # Update object with its own UUID/token
    obj["uuid"] = token_uuid
    obj["token"] = token_uuid
    db_save(obj, token_uuid)
    
    return token_uuid

def get_bootstrap_token(token: str) -> dict | None:
    """Fetch a bootstrap token object. Returns None if not found."""
    try:
        return db_get(token)
    except Exception:
        return None

def consume_bootstrap_token(token: str, server_uuid: str) -> bool:
    """Mark token as used and server as bootstrapped. Returns True on success."""
    import time as _time
    obj = get_bootstrap_token(token)
    if not obj:
        return False
    if obj.get("used") == "true":
        return False
    if obj.get("server") != server_uuid:
        return False
    # Check expiry
    try:
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(obj["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > exp:
            return False
    except Exception:
        pass
    obj["used"] = "true"
    db_save(obj, token)
    # Mark server bootstrapped
    try:
        srv = db_get(server_uuid)
        srv["bootstrapped"] = "yes"
        db_save(srv, server_uuid)
    except Exception:
        pass
    return True


# ── Minimal stdlib WebSocket client ───────────────────────────────────────────
class MetaxWebSocket:
    """Lightweight WebSocket client (no external lib, stdlib only)."""

    def __init__(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((METAX_HOST, METAX_PORT))
        self._sock = ctx.wrap_socket(raw, server_hostname=METAX_HOST)
        self._do_handshake()
        self.token = None

    def _do_handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {METAX_HOST}:{METAX_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self._sock.recv(4096)
        # expect 101 Switching Protocols

    def recv(self) -> dict | None:
        """Receive one WebSocket text frame → parse JSON."""
        try:
            hdr = self._recv_exact(2)
            payload_len = hdr[1] & 0x7F
            if payload_len == 126:
                payload_len = struct.unpack(">H", self._recv_exact(2))[0]
            elif payload_len == 127:
                payload_len = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(payload_len)
            return json.loads(data.decode())
        except Exception:
            return None

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket closed")
            buf += chunk
        return buf

    def send_get(self, path: str):
        """Send HTTP GET via already-upgraded… no, use httpx for REST calls."""
        pass  # REST calls go through httpx; WS is only for event subscription

    def register_listener(self, uuid: str):
        if self.token:
            client().get("/db/register_listener", params={"id": uuid, "token": self.token})

    def close(self):
        self._sock.close()


