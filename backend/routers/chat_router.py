from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from database import get_db, ChatHistory, UsageStat, User
from auth import get_current_user
from rag_pipeline import rag_query

router = APIRouter(prefix="/chat", tags=["chat"])


class QueryRequest(BaseModel):
    question: str
    doc_type_filter: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /chat  — main chat endpoint (requires login)
# ---------------------------------------------------------------------------

@router.post("")
def chat(
    req: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Run RAG pipeline
    result = rag_query(req.question, doc_type_filter=req.doc_type_filter)

    # Save to chat history
    history = ChatHistory(
        user_id=current_user.id,
        question=req.question,
        answer=result["answer"],
        sources=result.get("citations", []),
        cache_hit=result.get("cache_hit", False),
    )
    db.add(history)

    # Update daily usage stats
    today = date.today()
    stat = db.query(UsageStat).filter(UsageStat.date == today).first()
    if not stat:
        stat = UsageStat(date=today, total_queries=0, cache_hits=0)
        db.add(stat)
    stat.total_queries += 1
    if result.get("cache_hit"):
        stat.cache_hits += 1

    db.commit()

    return result


# ---------------------------------------------------------------------------
# GET /chat/history  — returns current user's chat history
# ---------------------------------------------------------------------------

@router.get("/history")
def get_chat_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    history = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id":         str(h.id),
            "question":   h.question,
            "answer":     h.answer,
            "sources":    h.sources,
            "cache_hit":  h.cache_hit,
            "created_at": h.created_at,
        }
        for h in history
    ]


# ---------------------------------------------------------------------------
# DELETE /chat/history  — clear current user's history
# ---------------------------------------------------------------------------

@router.delete("/history")
def clear_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = db.query(ChatHistory).filter(ChatHistory.user_id == current_user.id).delete()
    db.commit()
    return {"deleted": deleted}