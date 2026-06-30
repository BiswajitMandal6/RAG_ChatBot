import os
import hashlib
from pathlib import Path

from pinecone import Pinecone
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader

from config import (
    PINECONE_API_KEY,
    PINECONE_INDEX,
    DOCS_NAMESPACE,
    DOCUMENTS_PATH,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

# ---------------------------------------------------------------------------
# Initialise embedding model and Pinecone
# ---------------------------------------------------------------------------

_embedder = None
_pine_index = None

def get_embedder():
    global _embedder
    if _embedder is None:
        print(f"[ingestion] Lazy loading embedding model: {EMBEDDING_MODEL}")
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder

def get_pine_index():
    global _pine_index
    if _pine_index is None:
        print(f"[ingestion] Lazy loading Pinecone index: {PINECONE_INDEX}")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pine_index = pc.Index(PINECONE_INDEX)
    return _pine_index

print(f"[ingestion] Ingestion module initialized (Lazy Load enabled)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages  = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    # Using a joined string with explicit newline characters
    sep = chr(10) + chr(10)
    return sep.join(pages)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    words  = text.split()
    chunks = []
    start  = 0
    while start < len(words):
        end   = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 50]


def make_chunk_id(file_name: str, chunk_index: int) -> str:
    raw = f"{file_name}::chunk_{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Ingest a single document
# ---------------------------------------------------------------------------

def ingest_document(file_path: str, doc_type: str = "general") -> dict:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_name = file_path.name
    print(f"[ingestion] Processing: {file_name}")

    if file_path.suffix.lower() == ".pdf":
        raw_text = extract_text_from_pdf(str(file_path))
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    if not raw_text.strip():
        raise ValueError(f"No text extracted from {file_name}.")

    chunks     = chunk_text(raw_text)
    embeddings = get_embedder().encode(chunks, show_progress_bar=True).tolist()

    vectors = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        vid = make_chunk_id(file_name, i)
        vectors.append({
            "id":     vid,
            "values": emb,
            "metadata": {
                "source":      file_name,
                "doc_type":    doc_type,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "text":        chunk[:1000],
            }
        })

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        get_pine_index().upsert(
            vectors=vectors[i:i + batch_size],
            namespace=DOCS_NAMESPACE,
        )

    print(f"[ingestion] Done: {file_name} ({len(chunks)} chunks)")
    return {"file": file_name, "doc_type": doc_type, "chunks_stored": len(chunks)}


# ---------------------------------------------------------------------------
# Ingest all PDFs in folder
# ---------------------------------------------------------------------------

def ingest_all_documents(folder_path: str = DOCUMENTS_PATH) -> list[dict]:
    folder = Path(folder_path)
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for pdf in folder.rglob("*.pdf"):
        try:
            results.append(ingest_document(str(pdf)))
        except Exception as e:
            print(f"[ingestion] ERROR {pdf.name}: {e}")
            results.append({"file": pdf.name, "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# Delete a document
# ---------------------------------------------------------------------------

def delete_document(file_name: str) -> dict:
    try:
        results = get_pine_index().query(
            vector=[0.0] * 384,
            top_k=10000,
            filter={"source": {"$eq": file_name}},
            namespace=DOCS_NAMESPACE,
            include_metadata=False,
        )
        ids = [m["id"] for m in results["matches"]]

        if ids:
            get_pine_index().delete(ids=ids, namespace=DOCS_NAMESPACE)
            print(f"[ingestion] Deleted {len(ids)} vectors for: {file_name}")
        return {"file": file_name, "deleted": len(ids)}
    except Exception as e:
        print(f"[ingestion] Delete error: {e}")
        return {"file": file_name, "deleted": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# List ingested documents
# ---------------------------------------------------------------------------

def list_ingested_documents() -> list[dict]:
    try:
        stats = get_pine_index().describe_index_stats()
        ns    = stats.get("namespaces", {}).get(DOCS_NAMESPACE, {})
        total = ns.get("vector_count", 0)

        result = get_pine_index().query(
            vector=[0.0] * 384,
            top_k=min(total, 10000) if total > 0 else 1,
            namespace=DOCS_NAMESPACE,
            include_metadata=True,
        )

        seen = {}
        for m in result.get("matches", []):
            src  = m["metadata"].get("source", "unknown")
            dtype = m["metadata"].get("doc_type", "general")
            if src not in seen:
                seen[src] = {"source": src, "doc_type": dtype, "chunks": 0}
            seen[src]["chunks"] += 1

        return list(seen.values())
    except Exception as e:
        print(f"[ingestion] List error: {e}")
        return []
