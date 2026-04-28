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

async def handle_play_uuid(request):
    uuid = request.match_info.get("uuid", "")
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
        AsciinemaPlayer.create('/proxy_db/{uuid}', document.getElementById('player'), {{
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

async def handle_proxy_db(request):
    uuid = request.match_info.get("uuid", "")
    url = f"https://{METAX_HOST}:{METAX_PORT}/db/get?id={uuid}"
    print(f"[viewer] Proxying playback for UUID: {uuid}")
    try:
        async with httpx.AsyncClient(verify=False, http2=True, timeout=10.0) as client:
            r = await client.get(url)
            err_text = r.text if r.status_code != 200 else ""
            print(f"[viewer] Metax returned status {r.status_code}, error: {err_text}, length {len(r.content)}")
            if r.status_code != 200:
                return web.Response(status=r.status_code, text=f"Metax error: {err_text}")
            return web.Response(body=r.content, content_type="application/x-asciicast")
    except Exception as e:
        print(f"[viewer] Proxy error: {e}")
        return web.Response(status=500, text=f"Proxy error: {str(e)}")

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

