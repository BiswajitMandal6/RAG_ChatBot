from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="College RAG Chatbot",
    description="RAG-based chatbot for college documents — Phase 3",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

try:
    from database import create_tables
    print("[main] database.py imported OK")
except Exception as e:
    print(f"[main] ERROR importing database.py: {e}")
    create_tables = None

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

try:
    from routers.auth_router import router as auth_router
    app.include_router(auth_router)
    print("[main] auth_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading auth_router: {e}")

try:
    from routers.chat_router import router as chat_router
    app.include_router(chat_router)
    print("[main] chat_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading chat_router: {e}")

try:
    from routers.admin_router import router as admin_router
    app.include_router(admin_router)
    print("[main] admin_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading admin_router: {e}")

try:
    from routers.crawler_router import router as crawler_router
    app.include_router(crawler_router)
    print("[main] crawler_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading crawler_router: {e}")

try:
    from routers.web_router import router as web_router
    app.include_router(web_router)
    print("[main] web_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading web_router: {e}")

try:
    from routers.scraper_router import router as scraper_router
    app.include_router(scraper_router)
    print("[main] scraper_router loaded OK")
except Exception as e:
    print(f"[main] ERROR loading scraper_router: {e}")

# ---------------------------------------------------------------------------
# Cache utils
# ---------------------------------------------------------------------------

try:
    from semantic_cache import clear_cache, cache_stats
except Exception as e:
    print(f"[main] ERROR importing semantic_cache: {e}")
    def clear_cache(): return {}
    def cache_stats(): return {}

# ---------------------------------------------------------------------------
# Public document list
# ---------------------------------------------------------------------------

try:
    from ingestion import list_ingested_documents
except Exception as e:
    print(f"[main] ERROR importing ingestion: {e}")
    def list_ingested_documents(): return []

# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    print("[main] Starting up application...")
    if create_tables:
        try:
            print("[main] Attempting to connect to database and create tables...")
            create_tables()
            print("[main] Database tables ready.")
        except Exception as e:
            print(f"[main] CRITICAL ERROR creating tables: {e}")
            print("[main] The app will still start, but database features may fail.")
    else:
        print("[main] Skipping DB setup — database.py failed to import.")
    
    print("[main] Startup sequence complete. Server is now ready to handle requests.")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def serve_chat():
    index = frontend_path / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Frontend not found."}


@app.get("/admin")
def serve_admin():
    admin = frontend_path / "admin.html"
    if admin.exists():
        return FileResponse(str(admin))
    return {"message": "Admin portal not found."}


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/cache/stats")
def get_cache_stats():
    return cache_stats()


@app.delete("/cache")
def wipe_cache():
    return clear_cache()


@app.get("/documents")
def list_documents_public():
    docs = list_ingested_documents()
    return {"documents": docs, "total": len(docs)}