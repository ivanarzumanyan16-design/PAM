"""
PAM Bastion — central configuration.
All UUIDs are fixed at setup time by setup_types.py and committed here.
"""

# ── Metax2 connection ──────────────────────────────────────────────────────────
METAX_HOST  = "localhost"
METAX_PORT  = 8000
METAX_CERT  = "/opt/PAM/metax_zero_webserver/certs/metax.crt"  # self-signed
PUBLIC_VIEWER_HOST    = "10.8.8.106"
BOOTSTRAP_PORT        = 8766          # port for bootstrap token HTTP server
TOKEN_TTL_MINUTES     = 30            # bootstrap tokens expire after this many minutes
TOKEN_REGEN_MINUTES   = 1            # generate a new bootstrap command if older than this many minutes


# ── Bastion host paths ─────────────────────────────────────────────────────────
BASTION_KEY       = "/var/pam/bastion_ed25519"          # SSH key for outgoing connections
RECORDINGS_DIR    = "/var/pam/recordings"
AUTHORIZED_KEYS   = "/etc/pam_authorized_keys"           # shared authorized_keys managed by sync_daemon

# ── Metax2 meta-model UUIDs (fixed, do not change) ────────────────────────────
M_TRUE           = "b4598a37-3126-42c1-a7b2-2906b12989f8"
M_FALSE          = "df868f39-896b-431b-b699-e71b4233eaf8"
M_META_TYPE      = "585f3fef-7246-4612-8f24-b98d1a9ae8b7"  # type-of-types
M_STRING_TYPE    = "71b30d14-59f8-482d-993d-c913e8737f9e"  # text/string value type
M_COLL_COMPOSE   = "7764d377-e113-434d-a610-8c334a57ed7c"  # composition collection

# ── PAM type UUIDs (created by setup_types.py) ────────────────────────────────
T_USER       = "0a4d2835-8099-4d6e-91d9-39c8aa81ba8e-89bbac2d-5f04-472b-8637-06fdcbd03757"
T_GROUP      = "9f3d43e9-af94-42fb-98ff-d7118c69be6a-d4951da3-dad9-4f45-aa13-f69319522b36"
T_SERVER     = "f58b0daf-7c96-409c-ac87-237d1786c80c-cf2801b9-5f2a-48e7-93e0-02a6a4f25fdf"
T_PERMISSION = "5f6e9dfa-7812-4a29-a50c-5324a9f39f07-6684a52c-0d6e-401a-8eca-a7b5d427c5c9"
T_SESSION    = "ca2ed00f-654e-48aa-919a-d8ea39440a20-6fa929cd-7380-4c08-8e97-4fff2cd86612"
T_AUDIT      = "44936aab-25f9-4891-921e-b420363c7cdc"
T_ROOT       = "636b3e36-1a86-4500-8c33-4d1972197819-e39821ee-b002-443f-afaa-4164c53f70dd"

# ── PAM root instance UUID (singleton container) ──────────────────────────────
PAM_ROOT     = "636b3e36-1a86-4500-8c33-4d1972197819-e39821ee-b002-443f-afaa-4164c53f70dd"

