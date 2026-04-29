import asyncio
import os
import urllib.parse
import sys
from aiohttp import web
import socket
import ssl
import httpx
from config import METAX_HOST, METAX_PORT

RECORDINGS_DIR = "/var/pam/recordings"

# Dictionary to hold sets of WebSocket connections per session_uuid
live_sessions = {}

class UdpReceiver(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        print("[viewer] UDP listener started on 127.0.0.1:9001")

    def datagram_received(self, data, addr):
        try:
            sep_idx = data.index(b"|")
            uuid_str = data[:sep_idx].decode("utf-8")
            payload = data[sep_idx+1:]
            
            if uuid_str in live_sessions:
                for ws in list(live_sessions[uuid_str]):
                    asyncio.create_task(ws.send_bytes(payload))
        except Exception:
            pass

async def handle_play(request):
    filename = request.match_info.get("filename", "")
    filename = urllib.parse.unquote(filename)
    if "/" in filename or "\\" in filename:
        return web.Response(status=400, text="Invalid filename")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.css" />
    <style>body {{ background: #000; margin: 0; padding: 20px; }}</style>
</head>
<body>
    <div id="player"></div>
    <script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>
    <script>
        AsciinemaPlayer.create('/cast/{urllib.parse.quote(filename)}', document.getElementById('player'), {{
            autoPlay: true,
            preload: true,
            cols: 120,
            rows: 30,
            fit: 'width'
        }});
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

async def _resolve_cast_uuid(session_uuid: str) -> tuple[str, str]:
    """
    Given a UUID, determine the actual cast file UUID.

    If the UUID points to a SESSION object (contains ttyrec_uuid / recording /
    video field), return (file_uuid, error_string).
    If it already points to a raw cast file, return (session_uuid, "").
    Returns ("", error_msg) on failure.
    """
    url = f"https://{METAX_HOST}:{METAX_PORT}/db/get?id={session_uuid}"
    try:
        async with httpx.AsyncClient(verify=False, http2=True, timeout=30.0) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return "", f"Metax returned HTTP {r.status_code}"

            raw = r.content
            # Try to parse as JSON — if it has cast file fields it IS a session object
            try:
                obj = r.json()
            except Exception:
                # Not JSON → already a raw cast file
                return session_uuid, ""

            # Detect session-like objects: look for known file-pointer fields
            for field in ("ttyrec_uuid", "recording", "video", "file"):
                fid = obj.get(field, "")
                if fid and isinstance(fid, str) and len(fid) > 8:
                    print(f"[viewer] Resolved session {session_uuid} → cast file {fid} (via '{field}')")
                    return fid, ""

            # The JSON object has no file pointer — check if it looks like asciicast
            # (asciicast v2 starts with a JSON line containing 'version' key)
            if b'"version"' in raw[:200]:
                # It IS a cast file stored as JSON — serve it directly
                return session_uuid, ""

            return "", (f"Session {session_uuid[:8]}… has no recording yet. "
                        f"Fields present: {list(obj.keys())}")
    except Exception as e:
        return "", str(e)


async def handle_play_uuid(request):
    """Serve the asciinema player HTML for a session or cast-file UUID.

    The UUID from Mani's playback_url is the SESSION uuid.  We resolve the
    actual cast-file UUID on the server side before building the page so
    the browser never receives a broken URL.
    """
    session_uuid = request.match_info.get("uuid", "")

    # Resolve session → cast file UUID
    cast_uuid, err = await _resolve_cast_uuid(session_uuid)

    if err or not cast_uuid:
        error_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PAM — Playback Error</title>
<style>body{{background:#0d0d0d;color:#ff5555;font-family:monospace;padding:40px;}}</style>
</head><body>
<h2>⚠ Cannot load recording</h2>
<p>{err or 'Recording UUID could not be resolved.'}</p>
<p><small>Session UUID: {session_uuid}</small></p>
</body></html>"""
        return web.Response(text=error_html, content_type="text/html", status=404)

    cast_url = f"/proxy_db/{cast_uuid}"
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PAM Session Playback</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.css" />
    <style>
        body {{ background: #0d0d0d; margin: 0; padding: 30px; font-family: monospace; color: #ccc; }}
        h3   {{ color: #888; margin-bottom: 16px; }}
        #error-msg {{ color: #ff5555; padding: 20px; display: none; font-size: 14px; }}
    </style>
</head>
<body>
    <h3>PAM Session Recording</h3>
    <div id="player"></div>
    <div id="error-msg"></div>
    <script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>
    <script>
        var castUrl = '{cast_url}';
        fetch(castUrl)
            .then(function(resp) {{
                if (!resp.ok) throw new Error('HTTP ' + resp.status + ' — ' + resp.statusText);
                return resp.text();
            }})
            .then(function(text) {{
                if (!text || text.trim().length === 0)
                    throw new Error('Recording file is empty (0 bytes)');
                AsciinemaPlayer.create(castUrl, document.getElementById('player'), {{
                    autoPlay: true,
                    preload: true,
                    cols: 220,
                    rows: 50,
                    fit: 'width',
                    theme: 'monokai'
                }});
            }})
            .catch(function(err) {{
                var el = document.getElementById('error-msg');
                el.style.display = 'block';
                el.innerHTML = '<b>⚠ Cannot load recording:</b> ' + err.message +
                               '<br><small>cast URL: {cast_url}</small>';
                console.error('Playback load error:', err);
            }});
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_proxy_db(request):
    """Proxy raw cast-file bytes from Metax to the browser.

    asciicast v2 is newline-delimited JSON (text/plain).  The asciinema-player
    JS library fetches this URL, so we must return text/plain + CORS header.
    Timeout is generous (120 s) to handle large recordings.
    """
    uuid = request.match_info.get("uuid", "")
    url = f"https://{METAX_HOST}:{METAX_PORT}/db/get?id={uuid}"
    print(f"[viewer] proxy_db → fetching cast file UUID={uuid}")
    try:
        async with httpx.AsyncClient(verify=False, http2=True, timeout=120.0) as c:
            r = await c.get(url)
            print(f"[viewer] Metax status={r.status_code}, size={len(r.content)} bytes")
            if r.status_code != 200:
                return web.Response(
                    status=r.status_code,
                    text=f"Metax error: {r.text}",
                    content_type="text/plain",
                )
            return web.Response(
                body=r.content,
                content_type="text/plain",
                charset="utf-8",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache",
                },
            )
    except Exception as e:
        print(f"[viewer] proxy_db error: {e}")
        return web.Response(status=500, text=f"Proxy error: {str(e)}", content_type="text/plain")

async def handle_live(request):
    uuid = request.match_info.get("uuid", "")
    host = request.host
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <style>body {{ background: #000; margin: 0; padding: 20px; }}</style>
</head>
<body>
    <div id="terminal"></div>
    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
    <script>
        var term = new Terminal({{ theme: {{ background: '#000' }} }});
        term.open(document.getElementById('terminal'));
        term.writeln('Connecting to Live Session...');
        
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var ws = new WebSocket(protocol + '//{host}/ws/live/{uuid}');
        
        ws.binaryType = 'arraybuffer';
        ws.onopen = () => term.writeln('\\r\\n[Connected]');
        ws.onmessage = (ev) => {{
            var data = new Uint8Array(ev.data);
            term.write(data);
        }};
        ws.onclose = () => term.writeln('\\r\\n[Connection Closed]');
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

async def handle_cast(request):
    filename = request.match_info.get("filename", "")
    filename = urllib.parse.unquote(filename)
    if "/" in filename or "\\" in filename:
        return web.Response(status=400, text="Invalid filename")
    
    path = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.exists(path):
        return web.Response(status=404, text="Not found")
    
    return web.FileResponse(path)

async def handle_ws_live(request):
    uuid = request.match_info.get("uuid", "")
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    if uuid not in live_sessions:
        live_sessions[uuid] = set()
    live_sessions[uuid].add(ws)

    try:
        async for msg in ws:
            pass 
    finally:
        live_sessions[uuid].discard(ws)
        if not live_sessions[uuid]:
            del live_sessions[uuid]

    return ws

async def handle_debug_session(request):
    """Diagnostic: show raw Metax object for a UUID.
    Usage: http://<bastion>:9000/debug/session/<uuid>
    """
    uuid = request.match_info.get("uuid", "")
    url = f"https://{METAX_HOST}:{METAX_PORT}/db/get?id={uuid}"
    try:
        async with httpx.AsyncClient(verify=False, http2=True, timeout=30.0) as c:
            r = await c.get(url)
        try:
            obj = r.json()
            import json as _json
            pretty = _json.dumps(obj, indent=2, ensure_ascii=False)
        except Exception:
            obj = None
            pretty = r.text[:4000] + ("..." if len(r.text) > 4000 else "")

        # If it's a session object, resolve the cast file UUID
        cast_uuid = ""
        cast_info = ""
        if obj and isinstance(obj, dict):
            for field in ("ttyrec_uuid", "recording", "video", "file"):
                fid = obj.get(field, "")
                if fid and isinstance(fid, str) and len(fid) > 8:
                    cast_uuid = fid
                    cast_info = f"Field '<b>{field}</b>' → cast file UUID: <code>{fid}</code>"
                    break

        status_color = "#55ff55" if r.status_code == 200 else "#ff5555"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PAM Debug</title>
<style>
  body {{ background:#0d0d0d; color:#ccc; font-family:monospace; padding:30px; }}
  pre  {{ background:#1a1a1a; padding:16px; border-radius:6px; overflow-x:auto; color:#7fff7f; font-size:13px; }}
  h2   {{ color:#ffcc00; }}
  .ok  {{ color:#55ff55; }} .err {{ color:#ff5555; }}
  a    {{ color:#5599ff; }}
</style></head><body>
<h2>🔍 Metax Debug — UUID: {uuid}</h2>
<p>HTTP Status: <span style="color:{status_color}">{r.status_code}</span> &nbsp;|
   Size: {len(r.content)} bytes</p>
<p>{cast_info or '<span class="err">⚠ No cast file pointer found in this object</span>'}</p>
{'<p><a href="/play_uuid/' + uuid + '">▶ Try playback</a> &nbsp;|&nbsp; <a href="/proxy_db/' + cast_uuid + '">⬇ Raw cast file</a></p>' if cast_uuid else ''}
<h3>Raw Metax response:</h3>
<pre>{pretty}</pre>
</body></html>"""
        return web.Response(text=html, content_type="text/html")
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500, content_type="text/plain")


async def start_background_tasks(app):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        UdpReceiver,
        local_addr=('127.0.0.1', 9001)
    )
    app['udp_transport'] = transport

async def cleanup_background_tasks(app):
    app['udp_transport'].close()

def main():
    app = web.Application()
    app.add_routes([
        web.get('/play/{filename}', handle_play),
        web.get('/play_uuid/{uuid}', handle_play_uuid),
        web.get('/proxy_db/{uuid}', handle_proxy_db),
        web.get('/cast/{filename}', handle_cast),
        web.get('/live/{uuid}', handle_live),
        web.get('/ws/live/{uuid}', handle_ws_live),
        web.get('/debug/session/{uuid}', handle_debug_session),
    ])
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    print("PAM Session Viewer running on HTTPS port 9000")
    
    # Configure SSL using the same certificates as Metax2
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    
    # Assuming standard paths for the certs used by Metax2/Mani.
    # Adjust these paths if your production certs are elsewhere.
    cert_path = "/opt/PAM/pam-webserver/certs/metax.crt"
    key_path = "/opt/PAM/pam-webserver/certs/metax.key"
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_ctx.load_cert_chain(cert_path, key_path)
        web.run_app(app, host='0.0.0.0', port=9000, ssl_context=ssl_ctx)
    else:
        print(f"WARNING: SSL certs not found at {cert_path}. Falling back to HTTP.")
        web.run_app(app, host='0.0.0.0', port=9000)

if __name__ == '__main__':
    main()

