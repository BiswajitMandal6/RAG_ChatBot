import json
from groq import Groq
from config import (
    GROQ_API_KEY, LLM_MODEL,
    TOP_K_RESULTS, TOP_K_AFTER_RERANK, QUERY_EXPANSIONS,
    DOCS_NAMESPACE,
)
from ingestion import get_embedder, pine_index
from reranker import rerank_chunks
from semantic_cache import get_cached_answer, save_to_cache

groq_client = Groq(api_key=GROQ_API_KEY)


# ---------------------------------------------------------------------------
# Query expansion
# ---------------------------------------------------------------------------

EXPANSION_PROMPT = """You are a query expansion assistant for a college document search system.
Given a student's question, generate {n} alternative ways to ask the same question.
Return ONLY a JSON array of strings, no explanation, no markdown.
Example: ["alternative 1", "alternative 2", "alternative 3"]
Student question: {query}"""


def expand_query(query: str, n: int = QUERY_EXPANSIONS) -> list[str]:
    try:
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user",
                       "content": EXPANSION_PROMPT.format(query=query, n=n)}],
            temperature=0.4,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        alts = json.loads(raw)
        if isinstance(alts, list):
            queries = [query] + [q for q in alts if q != query]
            print(f"[rag] Expanded to {len(queries)} queries")
            return queries[:n + 1]
    except Exception as e:
        print(f"[rag] Query expansion failed: {e}")
    return [query]


# ---------------------------------------------------------------------------
# Multi-query vector search via Pinecone
# ---------------------------------------------------------------------------

def retrieve_chunks(queries: list[str], top_k: int = TOP_K_RESULTS,
                    doc_type_filter: str = None) -> list[dict]:
    seen  = {}
    filter_dict = {"doc_type": {"$eq": doc_type_filter}} if doc_type_filter else None

    for q in queries:
        q_emb = embedder.encode(q).tolist()
        results = pine_index.query(
            vector=q_emb,
            top_k=top_k,
            namespace=DOCS_NAMESPACE,
            include_metadata=True,
            filter=filter_dict,
        )
        for match in results.get("matches", []):
            text  = match["metadata"].get("text", "")
            score = round(match["score"], 4)
            if text not in seen or score > seen[text]["score"]:
                seen[text] = {
                    "text":      text,
                    "source":    match["metadata"].get("source", "unknown"),
                    "doc_type":  match["metadata"].get("doc_type", "general"),
                    "chunk_index": match["metadata"].get("chunk_index", 0),
                    "score":     score,
                }

    chunks = list(seen.values())
    print(f"[rag] Retrieved {len(chunks)} unique chunks")
    return chunks


# ---------------------------------------------------------------------------
# Build context
# ---------------------------------------------------------------------------

def build_context(chunks: list[dict]) -> tuple[str, list[dict]]:
    parts     = []
    citations = []
    for i, chunk in enumerate(chunks, 1):
        score = chunk.get("reranker_score", chunk.get("score", 0))
        parts.append(
            f"[Source {i}: {chunk['source']} | Type: {chunk['doc_type']} | Score: {score}]\n"
            f"{chunk['text']}"
        )
        citations.append({
            "index":    i,
            "source":   chunk["source"],
            "doc_type": chunk["doc_type"],
            "score":    score,
        })
    return "\n\n---\n\n".join(parts), citations


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful college assistant chatbot. Answer student questions
using only the provided context from college documents and web pages.
Rules:
- Answer based ONLY on the provided context.
- If context lacks information, say so clearly.
- Mention which document your answer comes from.
- Be concise, clear, and student-friendly.
"""


def generate_answer(query: str, context: str) -> str:
    resp = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# Main RAG pipeline
# ---------------------------------------------------------------------------

def rag_query(query: str, doc_type_filter: str = None) -> dict:
    if not query.strip():
        return {"answer": "Please ask a question.", "citations": [],
                "chunks_used": 0, "query": query,
                "cache_hit": False, "expanded_queries": []}

    # 1. Cache check
    cached = get_cached_answer(query, embedder)
    if cached:
        return cached

    # 2. Query expansion
    from config import QUERY_EXPANSIONS, ENABLE_RERANKING
    expanded = expand_query(query) if QUERY_EXPANSIONS > 0 else [query]

    # 3. Retrieve
    chunks = retrieve_chunks(expanded, top_k=TOP_K_RESULTS,
                             doc_type_filter=doc_type_filter)
    if not chunks:
        return {"answer": "I couldn't find relevant information for your question.",
                "citations": [], "chunks_used": 0, "query": query,
                "cache_hit": False, "expanded_queries": expanded}

    # 4. Rerank
    if ENABLE_RERANKING:
        reranked = rerank_chunks(query, chunks, top_k=TOP_K_AFTER_RERANK)
    else:
        # If reranking is disabled, use top_k_after_rerank from the initial retrieval
        reranked = chunks[:TOP_K_AFTER_RERANK]

    # 5. Build context
    context, citations = build_context(reranked)

    # 6. Generate
    answer = generate_answer(query, context)

    result = {
        "answer":           answer,
        "citations":        citations,
        "chunks_used":      len(reranked),
        "query":            query,
        "cache_hit":        False,
        "expanded_queries": expanded,
    }

    # 7. Cache
    save_to_cache(query, result, embedder)

    return result