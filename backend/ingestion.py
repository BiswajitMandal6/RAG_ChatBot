import os
import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader

from config import (
    CHROMA_DB_PATH,
    DOCUMENTS_PATH,
    EMBEDDING_MODEL,
    COLLECTION_NAME,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

# ---------------------------------------------------------------------------
# Initialise embedding model and ChromaDB (done once at import time)
# ---------------------------------------------------------------------------

print(f"[ingestion] Loading embedding model: {EMBEDDING_MODEL}")
embedder = SentenceTransformer(EMBEDDING_MODEL)

chroma_client = chromadb.PersistentClient(
    path=CHROMA_DB_PATH,
    settings=Settings(anonymized_telemetry=False),
)
collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},   # cosine similarity for text
)


# ---------------------------------------------------------------------------
# Helper: extract raw text from a PDF
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """Read every page of a PDF and return concatenated text."""
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# Helper: split text into overlapping chunks
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Simple word-boundary chunking with overlap.
    For Phase 2 we'll add semantic chunking at paragraph breaks.
    """
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap   # slide forward, keeping overlap words

    return [c for c in chunks if len(c.strip()) > 50]  # drop tiny fragments


# ---------------------------------------------------------------------------
# Helper: stable ID for a chunk (prevents duplicate inserts)
# ---------------------------------------------------------------------------

def make_chunk_id(file_name: str, chunk_index: int) -> str:
    raw = f"{file_name}::chunk_{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core: ingest a single document file
# ---------------------------------------------------------------------------

def ingest_document(file_path: str, doc_type: str = "general") -> dict:
    """
    Full pipeline: file → text → chunks → embeddings → ChromaDB.

    Args:
        file_path:  Absolute or relative path to the PDF.
        doc_type:   Category label stored as metadata. Use values like
                    'syllabus', 'lecture_notes', 'question_paper', etc.

    Returns:
        Dict with ingestion summary.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_name = file_path.name
    print(f"[ingestion] Processing: {file_name}")

    # 1. Extract text
    if file_path.suffix.lower() == ".pdf":
        raw_text = extract_text_from_pdf(str(file_path))
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}. Only PDF supported in Phase 1.")

    if not raw_text.strip():
        raise ValueError(f"No text extracted from {file_name}. File may be scanned/image-based.")

    # 2. Chunk
    chunks = chunk_text(raw_text)
    print(f"[ingestion] {file_name} → {len(chunks)} chunks")

    # 3. Embed
    embeddings = embedder.encode(chunks, show_progress_bar=True).tolist()

    # 4. Prepare ChromaDB records
    ids = [make_chunk_id(file_name, i) for i in range(len(chunks))]
    metadatas = [
        {
            "source": file_name,
            "doc_type": doc_type,
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]

    # 5. Upsert (safe to re-run — won't create duplicates)
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )

    print(f"[ingestion] Done: {file_name} ({len(chunks)} chunks stored)")
    return {
        "file": file_name,
        "doc_type": doc_type,
        "chunks_stored": len(chunks),
    }


# ---------------------------------------------------------------------------
# Core: ingest all PDFs in the documents folder
# ---------------------------------------------------------------------------

def ingest_all_documents(folder_path: str = DOCUMENTS_PATH) -> list[dict]:
    """Walk the documents folder and ingest every PDF found."""
    folder = Path(folder_path)
    folder.mkdir(parents=True, exist_ok=True)

    pdf_files = list(folder.rglob("*.pdf"))
    if not pdf_files:
        print(f"[ingestion] No PDFs found in {folder_path}")
        return []

    results = []
    for pdf in pdf_files:
        try:
            result = ingest_document(str(pdf))
            results.append(result)
        except Exception as e:
            print(f"[ingestion] ERROR processing {pdf.name}: {e}")
            results.append({"file": pdf.name, "error": str(e)})

    return results


# ---------------------------------------------------------------------------
# Core: delete all chunks belonging to a specific document
# ---------------------------------------------------------------------------

def delete_document(file_name: str) -> dict:
    """Remove all ChromaDB entries for a given file (used by admin portal)."""
    results = collection.get(where={"source": file_name})
    ids_to_delete = results["ids"]

    if not ids_to_delete:
        return {"file": file_name, "deleted": 0, "message": "No chunks found for this file."}

    collection.delete(ids=ids_to_delete)
    print(f"[ingestion] Deleted {len(ids_to_delete)} chunks for: {file_name}")
    return {"file": file_name, "deleted": len(ids_to_delete)}


# ---------------------------------------------------------------------------
# Utility: list all ingested documents
# ---------------------------------------------------------------------------

def list_ingested_documents() -> list[dict]:
    """Return a summary of every document currently in ChromaDB."""
    all_meta = collection.get(include=["metadatas"])["metadatas"]

    seen = {}
    for m in all_meta:
        src = m.get("source", "unknown")
        if src not in seen:
            seen[src] = {"source": src, "doc_type": m.get("doc_type", "general"), "chunks": 0}
        seen[src]["chunks"] += 1

    return list(seen.values())