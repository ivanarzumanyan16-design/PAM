"""
PAM Bastion — audit logger.
Writes append-only pam-audit records to Metax2.
After session ends, uploads the ttyrec file to Metax2 as binary data
and links its UUID in the audit record (viewable via Mani).
"""
import os, time, json
from config import T_AUDIT, T_SESSION

# Action identifiers (stored as strings in Metax2, human-readable)
ACTION_CONNECT    = "connect"
ACTION_DISCONNECT = "disconnect"
ACTION_SUDO       = "sudo"
ACTION_DENIED     = "denied"
ACTION_TOTP_FAIL  = "totp_fail"


def log(user_uuid: str, action: str, server_uuid: str = "", result: str = "success") -> str:
    """Write one audit record to Metax2 and append to root.audit list.
    Returns the UUID of the created audit record."""
    from metax_client import db_save, get_root, save_root
    now = time.strftime("%Y-%m-%d | %H:%M:%S", time.gmtime())
    record = {
        "type":      T_AUDIT,
        "name":      f"{action}-{now}",
        "timestamp": now,
        "audit_user":      user_uuid,
        "action":    action,
        "audit_server":    server_uuid,
        "result":    result,
        "recording": "",   # filled in later by upload_recording()
    }
    try:
        uuid = db_save(record)
        record["uuid"] = uuid
        db_save(record, uuid)
        root = get_root()
        root.setdefault("audit", []).append(uuid)
        save_root(root)
        return uuid
    except Exception as e:
        import sys
        print(f"[audit ERROR] {e}", file=sys.stderr)
        return ""


def start_session(user_uuid: str, server_uuid: str) -> str:
    """Create a pam-session object in Metax2. Returns session UUID."""
    from metax_client import db_save, get_root, save_root
    now = time.strftime("%Y-%m-%d | %H:%M:%S", time.gmtime())
    record = {
        "type":       T_SESSION,
        "name":       f"session-{user_uuid[:8]}-{now}",
        "started_at": now,
        "ended_at":   "",
        "user":       user_uuid,
        "server":     server_uuid,
        "recording":  "",
        "description": "Session active",
    }
    try:
        uuid = db_save(record)
        record["uuid"] = uuid
        db_save(record, uuid)
        root = get_root()
        root.setdefault("sessions", []).append(uuid)
        save_root(root)
        return uuid
    except Exception as e:
        import sys
        print(f"[audit ERROR start_session] {e}", file=sys.stderr)
        return ""


def end_session(session_uuid: str, recording_uuid: str = ""):
    """Mark a pam-session as ended and link its recording UUID."""
    if not session_uuid:
        return
    from metax_client import db_get, db_save
    now = time.strftime("%Y-%m-%d | %H:%M:%S", time.gmtime())
    try:
        record = db_get(session_uuid)
        record["ended_at"] = now
        if recording_uuid:
            record["video"] = recording_uuid
        db_save(record, session_uuid)
    except Exception as e:
        import sys
        print(f"[audit ERROR end_session] {e}", file=sys.stderr)


def upload_recording(ttyrec_path: str, session_uuid: str = "") -> str:
    """
    Upload a .ttyrec file to Metax2 as a Video-typed object.
    Mani has a built-in Video type (UUID 5a6010e0-f920-4755-bba3-b78f90941701)
    which displays these objects properly in the UI.
    Returns the UUID of the uploaded object (empty string on failure).
    """
    if not ttyrec_path or not os.path.exists(ttyrec_path):
        return ""
    # UUID of the built-in Mani "Video" type
    MANI_VIDEO_TYPE = "5a6010e0-f920-4755-bba3-b78f90941701"
    try:
        import httpx
        from config import METAX_HOST, METAX_PORT
        fname = os.path.basename(ttyrec_path)

        # Step 1: Upload raw binary via multipart/form-data (as Metax2 expects)
        with open(ttyrec_path, "rb") as f:
            raw_data = f.read()

        boundary = "PAMBastionBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: application/octet-stream\r\n"
            f"\r\n"
        ).encode() + raw_data + f"\r\n--{boundary}--\r\n".encode()

        client = httpx.Client(
            base_url=f"https://{METAX_HOST}:{METAX_PORT}",
            http2=True,
            verify=False,
            timeout=60.0,
        )
        r = client.post(
            "/db/save/data",
            content=body,
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        r.raise_for_status()
        file_uuid = r.json().get("uuid", "")

        if not file_uuid:
            return ""

        # Step 2: Create a Video-typed metadata object that wraps the file
        # This makes it visible and playable in Mani's Video viewer
        now = time.strftime("%Y-%m-%d | %H:%M:%S", time.gmtime())
        video_record = {
            "type":    MANI_VIDEO_TYPE,
            "name":    f"Session-{fname}",
            "session": session_uuid,
            "started": now,
            "file":    file_uuid,   # UUID of the raw binary blob
        }
        from metax_client import db_save, get_root, save_root
        video_uuid = db_save(video_record)
        video_record["uuid"] = video_uuid
        db_save(video_record, video_uuid)

        # Link the recording into the root.recordings list for easy discovery
        root = get_root()
        root.setdefault("recordings", []).append(video_uuid)
        save_root(root)

        # Update the session object to reference this recording
        if session_uuid and video_uuid:
            end_session(session_uuid, video_uuid)

        return video_uuid
    except Exception as e:
        import sys
        print(f"[audit ERROR upload_recording] {e}", file=sys.stderr)
        return ""


