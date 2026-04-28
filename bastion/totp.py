"""
TOTP — RFC 6238 implementation using stdlib only (no pyotp).
"""
import hmac, hashlib, base64, struct, time as _time

def _hotp(key_bytes: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack(">Q", counter)
    h = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)

def _secret_to_bytes(secret: str) -> bytes:
    # pad to multiple of 8
    secret = secret.upper().strip()
    pad = (8 - len(secret) % 8) % 8
    return base64.b32decode(secret + "=" * pad)

def generate_secret(length: int = 16) -> str:
    """Generate a random base32 secret."""
    import os
    # 16 chars = 80 bits, 32 chars = 160 bits
    # Base32 uses 5 bits per char. 16 chars * 5 = 80 bits = 10 bytes.
    # 32 chars * 5 = 160 bits = 20 bytes.
    # We'll default to 16 chars for compatibility.
    byte_len = (length * 5) // 8
    return base64.b32encode(os.urandom(byte_len)).decode().strip("=")

def generate(secret: str, digits: int = 6, period: int = 30) -> str:
    """Return current TOTP code."""
    key = _secret_to_bytes(secret)
    counter = int(_time.time()) // period
    return _hotp(key, counter, digits)

def verify(secret: str, code: str, digits: int = 6, period: int = 30, window: int = 1) -> bool:
    """Verify TOTP code within ±window periods (default ±30s)."""
    key = _secret_to_bytes(secret)
    counter = int(_time.time()) // period
    for offset in range(-window, window + 1):
        expected = _hotp(key, counter + offset, digits)
        if hmac.compare_digest(code.encode(), expected.encode()):
            return True
    return False

