import json
import hashlib
import chromadb
from chromadb.config import Settings
from config import CHROMA_DB_PATH, CACHE_COLLECTION_NAME, CACHE_SIMILARITY_THRESHOLD

# ---------------------------------------------------------------------------
# Separate ChromaDB collection just for the cache
# ---------------------------------------------------------------------------

_client = chromadb.PersistentClient(
    path=CHROMA_DB_PATH,
    settings=Settings(anonymized_telemetry=False),
)
cache_collection = _client.get_or_create_collection(
    name=CACHE_COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)


def _make_cache_id(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()


def get_cached_answer(query: str, embedder) -> dict | None:
    """
    Check if a semantically similar question was answered before.

    Uses cosine similarity on the query embedding. If the closest cached
    question is above CACHE_SIMILARITY_THRESHOLD, return the cached answer.

    Returns:
        Cached result dict  (answer, citations, chunks_used, query)
        or None if no cache hit.
    """
    if cache_collection.count() == 0:
        return None

    query_embedding = embedder.encode(query).tolist()

    results = cache_collection.query(
        query_embeddings=[query_embedding],
        n_results=1,
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"][0]:
        return None

    distance = results["distances"][0][0]
    similarity = 1 - distance   # cosine distance → similarity

    if similarity >= CACHE_SIMILARITY_THRESHOLD:
        cached_data = json.loads(results["documents"][0][0])
        print(f"[cache] HIT — similarity {similarity:.3f} for: '{query[:60]}'")
        cached_data["cache_hit"] = True
        cached_data["cache_similarity"] = round(similarity, 4)
        return cached_data

    print(f"[cache] MISS — best similarity {similarity:.3f} for: '{query[:60]}'")
    return None


def save_to_cache(query: str, result: dict, embedder) -> None:
    """
    Save a query-answer pair to the semantic cache.

    Args:
        query:   The original student question.
        result:  The full result dict (answer, citations, etc.)
        embedder: The sentence transformer instance for embedding the query.
    """
    cache_id = _make_cache_id(query)
    query_embedding = embedder.encode(query).tolist()

    # Store the full result as JSON in the document field
    cache_doc = json.dumps({
        "answer":      result.get("answer", ""),
        "citations":   result.get("citations", []),
        "chunks_used": result.get("chunks_used", 0),
        "query":       query,
    })

    cache_collection.upsert(
        ids=[cache_id],
        embeddings=[query_embedding],
        documents=[cache_doc],
        metadatas=[{"original_query": query[:200]}],
    )
    print(f"[cache] Saved answer for: '{query[:60]}'")


def clear_cache() -> dict:
    """Delete all entries from the semantic cache."""
    count = cache_collection.count()
    if count > 0:
        all_ids = cache_collection.get()["ids"]
        cache_collection.delete(ids=all_ids)
    return {"cleared": count}


def cache_stats() -> dict:
    """Return basic cache statistics."""
    return {"cached_queries": cache_collection.count()}