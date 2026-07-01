"""
Celery tasks for the web crawler.
Each crawl job runs in a separate worker process,
completely independent from the FastAPI server.
"""

import json
import asyncio
import sys
from celery_app import celery_app  # Will raise RuntimeError if Redis not configured
from web_crawler import crawl_url_sync
from config import REDIS_URL
import redis


# Windows requires ProactorEventLoop for Playwright subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    
# Redis client for storing job status (separate from Celery backend)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

JOB_TTL = 86400   # keep job status for 24 hours


def set_job_status(job_id: str, status: str, result: dict = None, url: str = ""):
    key = f"crawl_job:{job_id}"
    pipe = redis_client.pipeline()
    pipe.hset(key, "job_id", job_id)
    pipe.hset(key, "status", status)
    pipe.hset(key, "url", url)
    pipe.hset(key, "result", json.dumps(result or {}))
    pipe.expire(key, JOB_TTL)
    pipe.execute()


def get_job_status(job_id: str) -> dict | None:
    data = redis_client.hgetall(f"crawl_job:{job_id}")
    if not data:
        return None
    try:
        data["result"] = json.loads(data.get("result", "{}"))
    except Exception:
        data["result"] = {}
    return data


def list_all_jobs() -> list:
    keys    = redis_client.keys("crawl_job:*")
    jobs    = []
    for key in keys:
        data = redis_client.hgetall(key)
        if data:
            try:
                data["result"] = json.loads(data.get("result", "{}"))
            except Exception:
                data["result"] = {}
            jobs.append(data)
    return sorted(jobs, key=lambda x: x.get("job_id", ""), reverse=True)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="crawler_tasks.crawl_website",
)
def crawl_website(self, job_id: str, url: str, doc_type: str = "web", user_id: str = None):
    """
    Celery task: crawl a URL and ingest content into ChromaDB.

    Args:
        job_id:   Unique job identifier (stored in Redis).
        url:      The URL to crawl.
        doc_type: Document type label.
        user_id:  ID of the user who submitted the job.
    """
    print(f"[task] Starting job {job_id} for {url}")
    set_job_status(job_id, "running", url=url)

    try:
        result = crawl_url_sync(url, doc_type=doc_type)

        if "error" in result:
            set_job_status(job_id, "failed", result=result, url=url)
            print(f"[task] Job {job_id} failed: {result['error']}")
        else:
            # Save to PostgreSQL documents table
            if user_id:
                try:
                    from database import SessionLocal, Document
                    import uuid
                    db  = SessionLocal()
                    doc = db.query(Document).filter(
                        Document.filename == f"web::{result['domain']}"
                    ).first()
                    if doc:
                        doc.chunks = result["chunks_stored"]
                    else:
                        doc = Document(
                            filename=f"web::{result['domain']}",
                            doc_type="web",
                            uploaded_by=uuid.UUID(user_id),
                            chunks=result["chunks_stored"],
                        )
                        db.add(doc)
                    db.commit()
                    db.close()
                except Exception as e:
                    print(f"[task] DB record error: {e}")

            set_job_status(job_id, "done", result=result, url=url)
            print(f"[task] Job {job_id} done: {result['chunks_stored']} chunks")

        return result

    except Exception as exc:
        print(f"[task] Job {job_id} exception: {exc}")
        set_job_status(job_id, "failed",
                       result={"error": str(exc), "pages_scraped": 0, "chunks_stored": 0},
                       url=url)
        # Retry up to max_retries times
        raise self.retry(exc=exc, countdown=30)