from sentence_transformers import CrossEncoder
from config import RERANKER_MODEL, TOP_K_AFTER_RERANK

# Global variable to hold the model once loaded
_reranker_model = None

def get_reranker():
    """Lazy-loads the reranker model only when needed."""
    global _reranker_model
    if _reranker_model is None:
        print(f"[reranker] Lazy loading reranker model: {RERANKER_MODEL}")
        _reranker_model = CrossEncoder(RERANKER_MODEL, max_length=512)
    return _reranker_model


def rerank_chunks(query: str, chunks: list[dict], top_k: int = TOP_K_AFTER_RERANK) -> list[dict]:
    """
    Rerank retrieved chunks using a cross-encoder model.
    """
    if not chunks:
        return []

    reranker = get_reranker()

    # Build (query, chunk_text) pairs for the cross-encoder
    pairs = [(query, chunk["text"]) for chunk in chunks]

    # Score each pair — higher = more relevant
    scores = reranker.predict(pairs)

    # Attach reranker score to each chunk
    for chunk, score in zip(chunks, scores):
        chunk["reranker_score"] = round(float(score), 4)

    # Sort by reranker score and return top_k
    ranked = sorted(chunks, key=lambda c: c["reranker_score"], reverse=True)
    return ranked[:top_k]