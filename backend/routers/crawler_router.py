import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, Document, User
from auth import get_current_user, require_faculty
from crawler_tasks import crawl_website, get_job_status, list_all_jobs, set_job_status
from ingestion import delete_document
from semantic_cache import clear_cache

router = APIRouter(prefix="/crawl", tags=["crawler"])

URL_PATTERN = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.I)


class CrawlRequest(BaseModel):
    url:      str
    doc_type: str = "web"


# ---------------------------------------------------------------------------
# POST /crawl  — submit a crawl job to Celery
# ---------------------------------------------------------------------------

@router.post("")
def submit_crawl(
    req: CrawlRequest,
    current_user: User = Depends(get_current_user),
):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    job_id = f"crawl_{uuid.uuid4().hex[:12]}"

    # Set initial status in Redis before dispatching
    set_job_status(job_id, "queued", url=url)

    # Dispatch to Celery worker
    crawl_website.apply_async(
        kwargs={
            "job_id":   job_id,
            "url":      url,
            "doc_type": req.doc_type,
            "user_id":  str(current_user.id),
        },
        task_id=job_id,
    )

    return {
        "message": f"Crawl job queued for {url}",
        "job_id":  job_id,
        "status":  "queued",
    }


# ---------------------------------------------------------------------------
# GET /crawl/status/{job_id}  — poll job status from Redis
# ---------------------------------------------------------------------------

@router.get("/status/{job_id}")
def get_status(job_id: str, current_user: User = Depends(get_current_user)):
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# ---------------------------------------------------------------------------
# GET /crawl/jobs  — list all crawl jobs (faculty only)
# ---------------------------------------------------------------------------

@router.get("/jobs")
def list_jobs(faculty: User = Depends(require_faculty)):
    return {"jobs": list_all_jobs()}


# ---------------------------------------------------------------------------
# GET /crawl/detect  — detect URL in a message string
# ---------------------------------------------------------------------------

@router.get("/detect")
def detect_url(text: str, current_user: User = Depends(get_current_user)):
    match = URL_PATTERN.search(text)
    return {"url": match.group(0) if match else None}


# ---------------------------------------------------------------------------
# DELETE /crawl/{domain}  — remove a crawled site
# ---------------------------------------------------------------------------

@router.delete("/{domain}")
def delete_site(
    domain: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = f"web::{domain}"
    result = delete_document(source)
    db.query(Document).filter(Document.filename == source).delete()
    db.commit()
    clear_cache()
    return {**result, "message": f"Removed {domain} and cleared cache."}