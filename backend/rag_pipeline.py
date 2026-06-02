from groq import Groq
from config import (
    GROQ_API_KEY,
    LLM_MODEL,
    TOP_K_RESULTS,
    TOP_K_AFTER_RERANK,
    QUERY_EXPANSIONS,
)

# Re-use already-loaded embedder and collection from ingestion
from ingestion import embedder, collection
from reranker import rerank_chunks
from semantic_cache import get_cached_answer, save_to_cache

groq_client = Groq(api_key=GROQ_API_KEY)


# ---------------------------------------------------------------------------
# Step 1: Query expansion
# ---------------------------------------------------------------------------

EXPANSION_PROMPT = """You are a query expansion assistant for a college document search system.
Given a student's question, generate {n} alternative ways to ask the same question.
These alternatives should use different words but mean the same thing.
They should help find relevant content in syllabus, lecture notes, question papers, and timetables.

Return ONLY a JSON array of strings, no explanation, no markdown.
Example output: ["alternative 1", "alternative 2", "alternative 3"]

Student question: {query}"""


def expand_query(query: str, n: int = QUERY_EXPANSIONS) -> list[str]:
    try:
        response = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": EXPANSION_PROMPT.format(query=query, n=n)}],
            temperature=0.4,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json
        alternatives = json.loads(raw)
        if isinstance(alternatives, list):
            queries = [query] + [q for q in alternatives if q != query]
            print(f"[query_expansion] {len(queries)} queries: {queries}")
            return queries[:n + 1]
    except Exception as e:
        print(f"[query_expansion] Failed, using original only: {e}")
    return [query]


# ---------------------------------------------------------------------------
# Step 2: Multi-query vector search with deduplication
# ---------------------------------------------------------------------------

def retrieve_chunks_multi(queries: list[str], top_k: int = TOP_K_RESULTS,
                          doc_type_filter: str = None) -> list[dict]:
    where_clause = {"doc_type": doc_type_filter} if doc_type_filter else None
    seen_texts = {}

    for q in queries:
        q_embedding = embedder.encode(q).tolist()
        results = collection.query(
            query_embeddings=[q_embedding],
            n_results=top_k,
            where=where_clause,
            include=["documents", "metadatas", "distances"],
        )
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            score = round(1 - dist, 4)
            if doc not in seen_texts or score > seen_texts[doc]["score"]:
                seen_texts[doc] = {
                    "text":        doc,
                    "source":      meta.get("source", "unknown"),
                    "doc_type":    meta.get("doc_type", "general"),
                    "chunk_index": meta.get("chunk_index", 0),
                    "score":       score,
                }

    chunks = list(seen_texts.values())
    print(f"[retrieval] {len(chunks)} unique chunks after multi-query dedup")
    return chunks


# ---------------------------------------------------------------------------
# Step 3: Build context
# ---------------------------------------------------------------------------

def build_context(chunks: list[dict]) -> tuple[str, list[dict]]:
    context_parts = []
    citations = []
    for i, chunk in enumerate(chunks, 1):
        reranker_score = chunk.get("reranker_score", chunk.get("score", 0))
        context_parts.append(
            f"[Source {i}: {chunk['source']} | Type: {chunk['doc_type']} | Score: {reranker_score}]\n"
            f"{chunk['text']}"
        )
        citations.append({
            "index":    i,
            "source":   chunk["source"],
            "doc_type": chunk["doc_type"],
            "score":    reranker_score,
        })
    return "\n\n---\n\n".join(context_parts), citations


# ---------------------------------------------------------------------------
# Step 4: Generate answer
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful college assistant chatbot. You answer student questions
using only the provided context from college documents (syllabus, lecture notes, question papers,
timetables, notices, lab manuals, and faculty information).

Rules:
- Answer based ONLY on the provided context. Do not use outside knowledge.
- If the context does not contain enough information to answer, say so clearly.
- Always mention which document your answer comes from (e.g. "According to the syllabus...").
- Be concise, clear, and student-friendly.
- If asked about topics outside the provided documents, politely redirect.
"""


def generate_answer(query: str, context: str) -> str:
    user_message = f"""Context from college documents:
{context}

---

Student question: {query}

Please answer the student's question based on the context above."""

    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def rag_query(query: str, doc_type_filter: str = None) -> dict:
    if not query.strip():
        return {"answer": "Please ask a question.", "citations": [], "chunks_used": 0,
                "query": query, "cache_hit": False, "expanded_queries": []}

    if collection.count() == 0:
        return {"answer": "No documents ingested yet. Please upload some college documents first.",
                "citations": [], "chunks_used": 0, "query": query,
                "cache_hit": False, "expanded_queries": []}

    # 1. Cache check
    cached = get_cached_answer(query, embedder)
    if cached:
        return cached

    # 2. Query expansion
    expanded_queries = expand_query(query)

    # 3. Multi-query search + dedup
    chunks = retrieve_chunks_multi(expanded_queries, top_k=TOP_K_RESULTS,
                                   doc_type_filter=doc_type_filter)

    if not chunks:
        return {"answer": "I couldn't find relevant information for your question.",
                "citations": [], "chunks_used": 0, "query": query,
                "cache_hit": False, "expanded_queries": expanded_queries}

    # 4. Rerank
    reranked = rerank_chunks(query, chunks, top_k=TOP_K_AFTER_RERANK)
    print(f"[reranker] Top scores: {[c['reranker_score'] for c in reranked]}")

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
        "expanded_queries": expanded_queries,
    }

    # 7. Save to cache
    save_to_cache(query, result, embedder)

    return result