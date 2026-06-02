import uuid
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Boolean,
    DateTime, Integer, Text, Enum, ForeignKey, Date, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import enum

from config import DATABASE_URL

# ---------------------------------------------------------------------------
# Engine & session
# ---------------------------------------------------------------------------

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    student = "student"
    faculty = "faculty"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name          = Column(String(100), nullable=False)
    email         = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role          = Column(Enum(UserRole), default=UserRole.student, nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    chats     = relationship("ChatHistory", back_populates="user", cascade="all, delete")
    documents = relationship("Document",    back_populates="uploader")


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question   = Column(Text, nullable=False)
    answer     = Column(Text, nullable=False)
    sources    = Column(JSON, default=list)   # list of citation dicts
    cache_hit  = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="chats")


class Document(Base):
    __tablename__ = "documents"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename    = Column(String(255), nullable=False)
    doc_type    = Column(String(50), default="general")
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chunks      = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    uploader = relationship("User", back_populates="documents")


class UsageStat(Base):
    __tablename__ = "usage_stats"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date          = Column(Date, default=datetime.utcnow, unique=True)
    total_queries = Column(Integer, default=0)
    cache_hits    = Column(Integer, default=0)
    unique_users  = Column(Integer, default=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    print("[database] Tables created / verified.")