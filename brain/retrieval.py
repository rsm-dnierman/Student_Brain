"""
Hybrid retrieval: BM25 keyword search + vector similarity, fused with
Reciprocal Rank Fusion (RRF), then optionally re-ranked with a cross-encoder.

BM25 index is built at ingest time and persisted alongside ChromaDB.
"""
import os
import pickle
from typing import Optional

BM25_PATH_SUFFIX = "bm25_index.pkl"
RERANKER_MODEL   = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker_cache  = None   # module-level — loaded once, reused across calls


# ── BM25 index helpers ────────────────────────────────────────────────────────

def build_bm25_index(db_path: str) -> None:
    """Load all documents from ChromaDB and build + save a BM25 index."""
    from rank_bm25 import BM25Okapi
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    col    = client.get_or_create_collection("student_brain")
    data   = col.get(include=["documents", "metadatas"])

    ids       = data["ids"]
    docs      = data["documents"]
    metadatas = data["metadatas"]

    tokenized = [d.lower().split() for d in docs]
    bm25      = BM25Okapi(tokenized)

    index = {"bm25": bm25, "ids": ids, "docs": docs, "metadatas": metadatas}
    pkl_path = os.path.join(db_path, BM25_PATH_SUFFIX)
    with open(pkl_path, "wb") as f:
        pickle.dump(index, f)


def load_bm25_index(db_path: str) -> Optional[dict]:
    pkl_path = os.path.join(db_path, BM25_PATH_SUFFIX)
    if not os.path.exists(pkl_path):
        return None
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """
    Combine multiple ranked ID lists into a single ranking via RRF.
    Higher score = more relevant.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


# ── Hybrid retrieve ───────────────────────────────────────────────────────────

def hybrid_retrieve(
    query: str,
    q_embedding: list[float],
    db_path: str,
    top_k: int = 8,
    course_filter: Optional[str] = None,
) -> list[dict]:
    """
    1. Vector search via ChromaDB
    2. BM25 keyword search
    3. Fuse rankings with RRF
    4. Return top_k merged results as dicts
    """
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    col    = client.get_or_create_collection("student_brain")

    if col.count() == 0:
        return []

    where = {"course": {"$eq": course_filter}} if course_filter else None

    # ── Vector search ──
    vec_kwargs = dict(
        query_embeddings=[q_embedding],
        n_results=min(top_k * 2, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    if where:
        vec_kwargs["where"] = where

    vec_results = col.query(**vec_kwargs)
    vec_ids  = vec_results["ids"][0]
    vec_docs = {rid: (doc, meta, dist) for rid, doc, meta, dist in zip(
        vec_ids,
        vec_results["documents"][0],
        vec_results["metadatas"][0],
        vec_results["distances"][0],
    )}

    # ── BM25 search ──
    bm25_ids: list[str] = []
    bm25_index = load_bm25_index(db_path)
    if bm25_index:
        import numpy as np
        tokenized_q = query.lower().split()
        scores      = bm25_index["bm25"].get_scores(tokenized_q)
        # Filter by course if requested
        if course_filter:
            for i, meta in enumerate(bm25_index["metadatas"]):
                if meta.get("course") != course_filter:
                    scores[i] = -1
        top_idx = np.argsort(scores)[::-1][: top_k * 2]
        bm25_ids = [bm25_index["ids"][i] for i in top_idx if scores[i] > 0]

    # ── RRF fusion ──
    fused_ids = rrf_fuse([vec_ids, bm25_ids]) if bm25_ids else vec_ids
    fused_ids = fused_ids[:top_k]

    # ── Build result dicts ──
    # Fetch any IDs that came from BM25 but not vector search
    extra_ids = [rid for rid in fused_ids if rid not in vec_docs]
    if extra_ids and bm25_index:
        for i, bid in enumerate(bm25_index["ids"]):
            if bid in extra_ids:
                vec_docs[bid] = (
                    bm25_index["docs"][i],
                    bm25_index["metadatas"][i],
                    0.5,  # placeholder distance for BM25-only hits
                )

    results = []
    for rid in fused_ids:
        if rid not in vec_docs:
            continue
        doc, meta, dist = vec_docs[rid]
        results.append({
            "text":      doc,
            "source":    meta.get("source", "unknown"),
            "course":    meta.get("course", ""),
            "filename":  meta.get("filename", ""),
            "file_type": meta.get("file_type", ""),
            "page":      meta.get("page", ""),
            "score":     round(1 - dist, 3),
        })

    return results


# ── Cross-encoder re-ranking ──────────────────────────────────────────────────

def rerank(query: str, chunks: list[dict]) -> list[dict]:
    """
    Re-rank chunks using a cross-encoder. Falls back to original order
    if sentence-transformers is not available.
    """
    global _reranker_cache

    if not chunks:
        return chunks

    try:
        from sentence_transformers import CrossEncoder
        import numpy as np

        if _reranker_cache is None:
            _reranker_cache = CrossEncoder(RERANKER_MODEL)

        pairs  = [(query, c["text"]) for c in chunks]
        scores = _reranker_cache.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked]

    except Exception:
        return chunks  # graceful fallback
