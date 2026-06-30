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

# PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Biswajit%407411@db.djgueupzzzphzznkqrbr.supabase.co:6543/postgres?pgbouncer=true")

# JWT
JWT_SECRET         = os.getenv("JWT_SECRET", "superSecretKey2024RagChatBot")
JWT_ALGORITHM      = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")