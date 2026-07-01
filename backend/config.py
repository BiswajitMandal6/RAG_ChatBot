import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Paths
DOCUMENTS_PATH = os.getenv("DOCUMENTS_PATH", "./data/documents")

# Models
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RERANKER_MODEL   = os.getenv("RERANKER_MODEL",  "cross-encoder/ms-marco-MiniLM-L-6-v2")
LLM_MODEL        = os.getenv("LLM_MODEL",       "llama-3.3-70b-versatile")

# Pinecone
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "college-rag")

# Pinecone namespace separation
DOCS_NAMESPACE  = "college_docs"
CACHE_NAMESPACE = "semantic_cache"

# Chunking
CHUNK_SIZE    = 512
CHUNK_OVERLAP = 100

# Retrieval
TOP_K_RESULTS      = 8
TOP_K_AFTER_RERANK = 3
QUERY_EXPANSIONS   = 0  # Set to 0 to disable expansion for speed
ENABLE_RERANKING    = False  # Set to False to disable reranking for speed and RAM savings

# Semantic cache
CACHE_SIMILARITY_THRESHOLD = 0.92

# ---------------------------------------------------------------------------
# PostgreSQL / Supabase
# ---------------------------------------------------------------------------
# IMPORTANT: Render free tier does NOT support IPv6.
# Supabase's direct connection (db.*.supabase.co:5432) resolves to IPv6 → FAILS.
# Use the Supabase PgBouncer pooler URL (IPv4) instead:
#   Host:  aws-0-<region>.pooler.supabase.com
#   Port:  6543
#   User:  postgres.<project-ref>   (note: project-ref is appended to username)
#
# NOTE: psycopg2 does NOT accept "pgbouncer=true" as a DSN parameter — only
# asyncpg does. We strip it from the URL automatically. NullPool (set in
# database.py) already provides full PgBouncer transaction-mode compatibility.
# ---------------------------------------------------------------------------

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

SUPABASE_PROJECT_REF = "djgueupzzzphzznkqrbr"

# The clean IPv4-safe pooler URL — NO pgbouncer=true, psycopg2-compatible.
_POOLER_FALLBACK = (
    "postgresql://postgres.djgueupzzzphzznkqrbr:Biswajit%407411"
    "@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    "?sslmode=require"
)


def _clean_db_url(url: str) -> str:
    """
    Sanitise a PostgreSQL URL for use with psycopg2 + SQLAlchemy:
      1. Convert postgres:// → postgresql://
      2. Remove 'pgbouncer=true' query param (psycopg2 rejects it)
      3. Keep sslmode and other valid params
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("pgbouncer", None)          # strip the offending param
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=clean_query))


raw_db_url = os.getenv("DATABASE_URL", "").strip()

if not raw_db_url or raw_db_url in ("changeme", "disabled", ""):
    # No env var set — use the hardcoded pooler URL (IPv4 safe, psycopg2 clean)
    DATABASE_URL = _POOLER_FALLBACK
else:
    # Detect old direct-connection URL (db.*.supabase.co:5432) → auto-correct
    if (
        f"db.{SUPABASE_PROJECT_REF}.supabase.co" in raw_db_url
        and "pooler.supabase.com" not in raw_db_url
    ):
        print(
            "[config] WARNING: DATABASE_URL points to Supabase direct connection "
            "(IPv6). Render free tier does not support IPv6. "
            "Auto-correcting to PgBouncer pooler URL (IPv4)."
        )
        DATABASE_URL = _POOLER_FALLBACK
    else:
        # Use the provided URL, but strip pgbouncer=true so psycopg2 is happy
        DATABASE_URL = _clean_db_url(raw_db_url)

print(f"[config] DATABASE_URL host: {urlparse(DATABASE_URL).hostname}")

# JWT
raw_jwt_secret = os.getenv("JWT_SECRET", "").strip()
JWT_SECRET = raw_jwt_secret if (raw_jwt_secret and raw_jwt_secret != "changeme") else "superSecretKey2024RagChatBot"

JWT_ALGORITHM      = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

# ---------------------------------------------------------------------------
# Redis (optional — only required for the Celery crawler feature)
# ---------------------------------------------------------------------------
# If REDIS_URL is not set, REDIS_URL will be None and the crawler router
# will be disabled gracefully instead of crashing the whole app.

raw_redis_url = os.getenv("REDIS_URL", "").strip()
if raw_redis_url and raw_redis_url != "changeme" and any(
    raw_redis_url.startswith(sch) for sch in ["redis://", "rediss://", "unix://"]
):
    REDIS_URL = raw_redis_url
else:
    # No Redis configured — set to None so dependent modules can check
    REDIS_URL = None