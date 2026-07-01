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
# Render free tier does NOT support IPv6.
# Supabase's direct connection (db.*.supabase.co:5432) resolves to IPv6 → FAILS.
#
# REQUIRED: Set DATABASE_URL in Render's dashboard to your Supabase POOLER URL:
#   1. Go to: https://supabase.com/dashboard/project/djgueupzzzphzznkqrbr/settings/database
#   2. Scroll to "Connection pooling" → copy the "Connection string" (port 6543)
#   3. Go to Render dashboard → your service → Environment → update DATABASE_URL
#
# The pooler URL looks like:
#   postgresql://postgres.djgueupzzzphzznkqrbr:<password>@aws-0-<REGION>.pooler.supabase.com:6543/postgres
#
# NOTE: psycopg2 does NOT accept "pgbouncer=true" — we strip it automatically.
# NullPool in database.py already provides PgBouncer transaction-mode compatibility.
# ---------------------------------------------------------------------------

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

SUPABASE_PROJECT_REF = "djgueupzzzphzznkqrbr"


def _clean_db_url(url: str) -> str:
    """
    Sanitise a PostgreSQL URL for psycopg2 + SQLAlchemy:
      1. Convert postgres:// → postgresql://
      2. Strip 'pgbouncer=true' (psycopg2 rejects it; NullPool handles compatibility)
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("pgbouncer", None)
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=clean_query))


raw_db_url = os.getenv("DATABASE_URL", "").strip()

if not raw_db_url or raw_db_url in ("changeme", "disabled", ""):
    raise RuntimeError(
        "\n\n[FATAL] DATABASE_URL is not set!\n"
        "Set it in Render dashboard → Environment → DATABASE_URL\n"
        "Value: get your POOLER connection string from:\n"
        "https://supabase.com/dashboard/project/djgueupzzzphzznkqrbr/settings/database\n"
        "(Scroll to 'Connection pooling', copy port-6543 URL)\n"
    )

# Detect the IPv6 direct-connection URL — CANNOT auto-fix (region is unknown)
if (
    f"db.{SUPABASE_PROJECT_REF}.supabase.co" in raw_db_url
    and "pooler.supabase.com" not in raw_db_url
):
    print(
        "\n[config] FATAL: DATABASE_URL is using the Supabase DIRECT connection\n"
        "         which resolves to IPv6. Render free tier does NOT support IPv6.\n"
        "         FIX: Go to https://supabase.com/dashboard/project/djgueupzzzphzznkqrbr/settings/database\n"
        "              Scroll to 'Connection pooling' → copy the Connection string (port 6543)\n"
        "              Then go to Render dashboard → Environment → update DATABASE_URL\n"
        "         The pooler URL looks like:\n"
        "         postgresql://postgres.djgueupzzzphzznkqrbr:<pwd>@aws-0-<REGION>.pooler.supabase.com:6543/postgres\n"
    )
    # Keep using it anyway so other routes still work — only DB calls will fail
    DATABASE_URL = _clean_db_url(raw_db_url)
else:
    # Strip pgbouncer=true (psycopg2-incompatible) and fix scheme
    DATABASE_URL = _clean_db_url(raw_db_url)

print(f"[config] DATABASE_URL host: {urlparse(DATABASE_URL).hostname}:{urlparse(DATABASE_URL).port}")

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