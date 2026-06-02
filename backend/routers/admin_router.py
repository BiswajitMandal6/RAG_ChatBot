import shutil
from pathlib import Path
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from database import get_db, Document, ChatHistory, UsageStat, User, UserRole
from auth import require_faculty
from ingestion import ingest_document, delete_document, list_ingested_documents
from semantic_cache import clear_cache, cache_stats
from config import DOCUMENTS_PATH

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------

@router.post("/documents/upload")
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("general"),
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    save_dir = Path(DOCUMENTS_PATH)
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / file.filename

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = ingest_document(str(save_path), doc_type=doc_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

    # Record in PostgreSQL
    doc_record = Document(
        filename=file.filename,
        doc_type=doc_type,
        uploaded_by=faculty.id,
        chunks=result["chunks_stored"],
    )
    db.add(doc_record)
    db.commit()

    return {"message": "Document uploaded and ingested.", "details": result}


@router.get("/documents")
def list_documents(
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    """List all documents with uploader info from PostgreSQL."""
    docs = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    return [
        {
            "id":          str(d.id),
            "filename":    d.filename,
            "doc_type":    d.doc_type,
            "chunks":      d.chunks,
            "uploaded_by": d.uploader.name if d.uploader else "unknown",
            "uploaded_at": d.uploaded_at,
        }
        for d in docs
    ]


@router.delete("/documents/{filename}")
def delete_doc(
    filename: str,
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    # Remove from ChromaDB
    result = delete_document(filename)

    # Remove from disk
    disk_path = Path(DOCUMENTS_PATH) / filename
    if disk_path.exists():
        disk_path.unlink()

    # Remove from PostgreSQL
    db.query(Document).filter(Document.filename == filename).delete()
    db.commit()

    # Clear semantic cache since knowledge base changed
    clear_cache()

    return {**result, "message": "Document deleted and cache cleared."}


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(
    days: int = 7,
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    """Usage stats for the last N days."""
    since = date.today() - timedelta(days=days)
    stats = (
        db.query(UsageStat)
        .filter(UsageStat.date >= since)
        .order_by(UsageStat.date.desc())
        .all()
    )

    total_queries = sum(s.total_queries for s in stats)
    total_hits    = sum(s.cache_hits for s in stats)

    return {
        "period_days":   days,
        "total_queries": total_queries,
        "cache_hits":    total_hits,
        "cache_hit_rate": round(total_hits / total_queries * 100, 1) if total_queries else 0,
        "daily": [
            {
                "date":          str(s.date),
                "total_queries": s.total_queries,
                "cache_hits":    s.cache_hits,
            }
            for s in stats
        ],
        "cache_stored": cache_stats()["cached_queries"],
    }


@router.get("/recent-questions")
def recent_questions(
    limit: int = 20,
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    """Most recent questions asked by all students."""
    history = (
        db.query(ChatHistory)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "question":   h.question,
            "cache_hit":  h.cache_hit,
            "asked_at":   h.created_at,
            "user":       h.user.name if h.user else "unknown",
        }
        for h in history
    ]


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    """List all registered users."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id":         str(u.id),
            "name":       u.name,
            "email":      u.email,
            "role":       u.role,
            "is_active":  u.is_active,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/toggle")
def toggle_user(
    user_id: str,
    db: Session = Depends(get_db),
    faculty: User = Depends(require_faculty),
):
    """Activate or deactivate a user account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = not user.is_active
    db.commit()
    return {"user_id": user_id, "is_active": user.is_active}


@router.delete("/cache")
def clear_semantic_cache(faculty: User = Depends(require_faculty)):
    """Manually wipe the semantic cache."""
    return clear_cache()