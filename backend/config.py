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
# Supabase's direct connection (port 5432) resolves to IPv6 → connection fails.
# Solution: Use Supabase's PgBouncer pooler which uses IPv4:
#   - Host format: aws-0-<region>.pooler.supabase.com
#   - Port: 6543 (transaction mode) or 5432 (session mode on pooler host)
#   - Add ?pgbouncer=true to the URL
#
# Set DATABASE_URL in Render to your Supabase POOLER connection string.
# It looks like: postgresql://postgres.djgueupzzzphzznkqrbr:<password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
# ---------------------------------------------------------------------------

SUPABASE_PROJECT_REF = "djgueupzzzphzznkqrbr"

# This is the IPv4-safe pooler fallback URL.
# The user part changes to postgres.<project-ref> for pooler connections.
_POOLER_FALLBACK = (
    "postgresql://postgres.djgueupzzzphzznkqrbr:Biswajit%407411"
    "@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    "?pgbouncer=true&sslmode=require"
)

raw_db_url = os.getenv("DATABASE_URL", "").strip()

if not raw_db_url or raw_db_url == "changeme":
    # No env var set — use the hardcoded pooler URL (IPv4 safe)
    DATABASE_URL = _POOLER_FALLBACK
else:
    # Fix scheme: SQLAlchemy requires postgresql://, not postgres://
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)

    # Detect if this is the old direct-connection URL pointing at port 5432
    # on the direct host (db.*.supabase.co) and auto-correct it to the pooler.
    if (
        f"db.{SUPABASE_PROJECT_REF}.supabase.co" in raw_db_url
        or ":5432" in raw_db_url
    ) and "pooler.supabase.com" not in raw_db_url:
        print(
            "[config] WARNING: DATABASE_URL points to Supabase direct connection "
            "(IPv6). Render free tier does not support IPv6. "
            "Auto-correcting to PgBouncer pooler URL (IPv4)."
        )
        DATABASE_URL = _POOLER_FALLBACK
    elif "pgbouncer=true" not in raw_db_url and "pooler.supabase.com" in raw_db_url:
        # Pooler URL but missing pgbouncer flag — add it
        sep = "&" if "?" in raw_db_url else "?"
        DATABASE_URL = raw_db_url + sep + "pgbouncer=true"
    else:
        DATABASE_URL = raw_db_url

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