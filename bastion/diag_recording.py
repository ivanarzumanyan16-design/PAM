#!/usr/bin/env python3
"""
PAM Bastion — Recording Diagnostic Script
Run this ON THE BASTION SERVER to trace exactly where playback breaks.

Usage:
    python3 diag_recording.py                   # auto-picks latest session
    python3 diag_recording.py <session-uuid>    # specific session UUID
"""
import sys, os, json, httpx

sys.path.insert(0, os.path.dirname(__file__))
from config import METAX_HOST, METAX_PORT, PAM_ROOT

OK   = "\033[32m✅\033[0m"
FAIL = "\033[31m❌\033[0m"
WARN = "\033[33m⚠ \033[0m"
INFO = "\033[36mℹ \033[0m"

def metax_get(uuid):
    c = httpx.Client(base_url=f"https://{METAX_HOST}:{METAX_PORT}",
                     http2=True, verify=False, timeout=30)
    r = c.get("/db/get", params={"id": uuid})
    return r.status_code, r.content

def section(title):
    print(f"\n\033[1;33m{'─'*60}\033[0m")
    print(f"\033[1;33m  {title}\033[0m")
    print(f"\033[1;33m{'─'*60}\033[0m")

# ── Step 1: reach Metax ───────────────────────────────────────────────────────
section("1. Metax connectivity")
try:
    status, _ = metax_get(PAM_ROOT)
    if status == 200:
        print(f"{OK} Metax reachable at {METAX_HOST}:{METAX_PORT}")
    else:
        print(f"{FAIL} Metax returned HTTP {status}")
        sys.exit(1)
except Exception as e:
    print(f"{FAIL} Cannot reach Metax: {e}")
    sys.exit(1)

# ── Step 2: find a session ────────────────────────────────────────────────────
section("2. Finding session to test")

session_uuid = sys.argv[1] if len(sys.argv) > 1 else None

if not session_uuid:
    # Auto-pick the latest session from root
    _, root_raw = metax_get(PAM_ROOT)
    try:
        root = json.loads(root_raw)
        sessions = root.get("sessions", [])
        if not sessions:
            print(f"{FAIL} No sessions found in PAM root")
            sys.exit(1)
        session_uuid = sessions[-1]
        print(f"{INFO} Auto-selected latest session: {session_uuid}")
    except Exception as e:
        print(f"{FAIL} Cannot parse root: {e}")
        sys.exit(1)
else:
    print(f"{INFO} Using provided session UUID: {session_uuid}")

# ── Step 3: fetch session object ──────────────────────────────────────────────
section("3. Session object in Metax")
status, sess_raw = metax_get(session_uuid)
if status != 200:
    print(f"{FAIL} Cannot fetch session (HTTP {status})")
    sys.exit(1)

try:
    sess = json.loads(sess_raw)
except Exception:
    print(f"{FAIL} Session data is not JSON — this is the raw cast file! UUID is a FILE, not session.")
    print(f"  First 200 bytes: {sess_raw[:200]}")
    sys.exit(0)

print(f"{OK} Session fetched. Fields:")
for k, v in sess.items():
    val = str(v)[:80] + ("..." if len(str(v)) > 80 else "")
    print(f"  {k:20s} = {val}")

# ── Step 4: check recording file on disk ─────────────────────────────────────
section("4. Recording file on disk")
ttyrec_path = sess.get("ttyrec_path", "")
if not ttyrec_path:
    print(f"{WARN} No ttyrec_path in session object")
else:
    if os.path.exists(ttyrec_path):
        size = os.path.getsize(ttyrec_path)
        print(f"{OK} File exists: {ttyrec_path} ({size} bytes)")
        if size == 0:
            print(f"{FAIL} File is EMPTY — session was not recorded properly")
        else:
            # Check format
            with open(ttyrec_path) as f:
                first_line = f.readline().strip()
            try:
                header = json.loads(first_line)
                ver = header.get("version")
                print(f"{OK} Valid asciicast v{ver} header: width={header.get('width')} height={header.get('height')}")
            except Exception:
                print(f"{WARN} First line is not valid asciicast JSON: {first_line[:100]}")
    else:
        print(f"{FAIL} File NOT FOUND on disk: {ttyrec_path}")
        print(f"  (This is OK if already uploaded to Metax — check ttyrec_uuid below)")

# ── Step 5: check ttyrec_uuid ─────────────────────────────────────────────────
section("5. Recording UUID in session")
ttyrec_uuid = sess.get("ttyrec_uuid", "")
if not ttyrec_uuid:
    print(f"{FAIL} ttyrec_uuid is EMPTY — recording was never uploaded to Metax!")
    print()
    print("  Possible causes:")
    print("  a) Session ended before bastion.py called close_session()")
    print("  b) close_session() crashed during upload (check bastion stderr/journal)")
    print("  c) timeout during upload (file too large for old timeout=60s)")
    print()

    # Try to upload it now if file exists
    if ttyrec_path and os.path.exists(ttyrec_path) and os.path.getsize(ttyrec_path) > 0:
        print(f"{INFO} Attempting manual upload of {ttyrec_path}...")
        try:
            with open(ttyrec_path, "rb") as f:
                content = f.read()
            c = httpx.Client(base_url=f"https://{METAX_HOST}:{METAX_PORT}",
                             http2=True, verify=False, timeout=120)
            r = c.post("/db/save/node", content=content,
                       headers={"content-type": "text/plain"})
            r.raise_for_status()
            file_uuid = r.json()["uuid"]
            print(f"{OK} Manual upload succeeded! File UUID: {file_uuid}")
            # Patch the session
            sess["ttyrec_uuid"] = file_uuid
            from config import PUBLIC_VIEWER_HOST
            sess["playback_url"] = f"https://{PUBLIC_VIEWER_HOST}:9000/play_uuid/{session_uuid}"
            pr = c.post("/db/save/node", params={"id": session_uuid},
                        content=json.dumps(sess).encode(),
                        headers={"content-type": "application/json"})
            pr.raise_for_status()
            print(f"{OK} Session patched with ttyrec_uuid = {file_uuid}")
            print(f"{OK} Playback URL: {sess['playback_url']}")
        except Exception as e:
            print(f"{FAIL} Manual upload failed: {e}")
    sys.exit(0)
else:
    print(f"{OK} ttyrec_uuid = {ttyrec_uuid}")

# ── Step 6: fetch the cast file from Metax ───────────────────────────────────
section("6. Fetching cast file from Metax")
status, cast_raw = metax_get(ttyrec_uuid)
if status != 200:
    print(f"{FAIL} Metax returned HTTP {status} for cast file UUID {ttyrec_uuid}")
    sys.exit(1)

print(f"{OK} Cast file fetched: {len(cast_raw)} bytes")

try:
    first_line = cast_raw.split(b"\n")[0]
    header = json.loads(first_line)
    ver = header.get("version")
    print(f"{OK} Valid asciicast v{ver}: width={header.get('width')} height={header.get('height')}")
    # Count frames
    frames = [l for l in cast_raw.split(b"\n") if l.strip() and not l.strip().startswith(b"{\"version\"")]
    print(f"{OK} Frame count: {len(frames)}")
except Exception as e:
    print(f"{FAIL} Cast file is not valid asciicast: {e}")
    print(f"  First 200 bytes: {cast_raw[:200]}")
    sys.exit(1)

# ── Step 7: check viewer ─────────────────────────────────────────────────────
section("7. Summary")
playback_url = sess.get("playback_url", "")
print(f"{OK} All checks passed!")
print(f"\n  Session UUID : {session_uuid}")
print(f"  File UUID    : {ttyrec_uuid}")
print(f"  Playback URL : {playback_url}")
print(f"\n  Open in browser: http://{METAX_HOST}:9000/debug/session/{session_uuid}")
