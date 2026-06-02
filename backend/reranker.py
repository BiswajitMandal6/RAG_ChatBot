from sentence_transformers import CrossEncoder
from config import RERANKER_MODEL, TOP_K_AFTER_RERANK

print(f"[reranker] Loading reranker model: {RERANKER_MODEL}")
reranker = CrossEncoder(RERANKER_MODEL, max_length=512)


def rerank_chunks(query: str, chunks: list[dict], top_k: int = TOP_K_AFTER_RERANK) -> list[dict]:
    """
    Rerank retrieved chunks using a cross-encoder model.

    Unlike embedding similarity (which encodes query and chunk separately),
    a cross-encoder reads the query AND chunk together — much more accurate.

    Args:
        query:   The original student question.
        chunks:  List of chunk dicts from vector search (each has 'text', 'source', etc.)
        top_k:   How many top chunks to keep after reranking.

    Returns:
        Top-k chunks sorted by reranker score descending.
    """
    if not chunks:
        return []

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