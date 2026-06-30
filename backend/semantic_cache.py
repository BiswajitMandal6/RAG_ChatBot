import json
import hashlib
from config import PINECONE_INDEX, CACHE_NAMESPACE, CACHE_SIMILARITY_THRESHOLD
from pinecone import Pinecone
from config import PINECONE_API_KEY
from ingestion import get_embedder

_pc = None
_pine_index = None

def get_cache_index():
    global _pc, _pine_index
    if _pine_index is None:
        print(f"[cache] Lazy loading Pinecone index: {PINECONE_INDEX}")
        _pc = Pinecone(api_key=PINECONE_API_KEY)
        _pine_index = _pc.Index(PINECONE_INDEX)
    return _pine_index


def _cache_id(query: str) -> str:
    return "cache_" + hashlib.md5(query.strip().lower().encode()).hexdigest()


def get_cached_answer(query: str, embedder=None) -> dict | None:
    try:
        # Use the provided embedder or fetch the lazy-loaded one
        actual_embedder = embedder if embedder else get_embedder()
        q_emb = actual_embedder.encode(query).tolist()
        results = get_cache_index().query(
            vector=q_emb,
            top_k=1,
            namespace=CACHE_NAMESPACE,
            include_metadata=True,
        )
        matches = results.get("matches", [])
        if not matches:
            return None

        score = matches[0]["score"]
        if score >= CACHE_SIMILARITY_THRESHOLD:
            print(f"[cache] HIT — similarity {score:.3f}")
            data = json.loads(matches[0]["metadata"].get("payload", "{}"))
            data["cache_hit"]        = True
            data["cache_similarity"] = round(score, 4)
            return data

        print(f"[cache] MISS — best similarity {score:.3f}")
    except Exception as e:
        print(f"[cache] get error: {e}")
    return None


def save_to_cache(query: str, result: dict, embedder=None) -> None:
    try:
        actual_embedder = embedder if embedder else get_embedder()
        cid   = _cache_id(query)
        q_emb = actual_embedder.encode(query).tolist()
        payload = json.dumps({
            "answer":      result.get("answer", ""),
            "citations":    result.get("citations", []),
            "chunks_used": result.get("chunks_used", 0),
            "query":       query,
        })
        get_cache_index().upsert(
            vectors=[{
                "id":     cid,
                "values": q_emb,
                "metadata": {
                    "original_query": query[:200],
                    "payload":        payload,
                }
            }],
            namespace=CACHE_NAMESPACE,
        )
        print(f"[cache] Saved: '{query[:60]}'")
    except Exception as e:
        print(f"[cache] save error: {e}")


def clear_cache() -> dict:
    try:
        get_cache_index().delete(delete_all=True, namespace=CACHE_NAMESPACE)
        return {"cleared": True}
    except Exception as e:
        return {"cleared": False, "error": str(e)}


def cache_stats() -> dict:
    try:
        stats = get_cache_index().describe_index_stats()
        count = stats.get("namespaces", {}).get(CACHE_NAMESPACE, {}).get("vector_count", 0)
        return {"cached_queries": count}
    except Exception:
        return {"cached_queries": 0}
