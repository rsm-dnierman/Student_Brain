"""
Query the student brain.

Two entry points:
  query_brain()        — blocking, returns dict with answer + sources
  query_brain_stream() — returns (sources, generator) for streaming UIs
"""
from typing import Iterator, Optional

from .ingest import embed_texts, get_collection
from .retrieval import hybrid_retrieve, rerank

SYSTEM_PROMPT = """You are a helpful student assistant for an MSBA program at UC San Diego's Rady School of Management.

Answer questions using ONLY the provided course material context.
Cite every claim with [1], [2], etc. matching the numbered sources.
If the context does not contain enough information to answer fully, say so clearly.
Keep answers well-structured and concise."""


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        label = c["source"]
        if c.get("page"):
            label += f" (page {c['page']})"
        parts.append(f"[{i}] {label}\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def _history_messages(history: list[dict]) -> list[dict]:
    """Convert chat history to Claude message format (last 6 turns)."""
    messages = []
    for turn in history[-6:]:
        role    = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


def _retrieve(
    question: str,
    openai_api_key: str,
    db_path: str,
    top_k: int,
    course_filter: Optional[str],
) -> list[dict]:
    col = get_collection(db_path)
    if col.count() == 0:
        return []
    q_embedding = embed_texts([question], openai_api_key)[0]
    chunks      = hybrid_retrieve(question, q_embedding, db_path,
                                  top_k=top_k, course_filter=course_filter)
    return rerank(question, chunks)


# ── Blocking query ────────────────────────────────────────────────────────────

def query_brain(
    question: str,
    openai_api_key: str,
    anthropic_api_key: str,
    db_path: str = "./chroma_db",
    top_k: int = 8,
    model: str = "claude-sonnet-4-6",
    history: Optional[list[dict]] = None,
    course_filter: Optional[str] = None,
) -> dict:
    import anthropic

    chunks = _retrieve(question, openai_api_key, db_path, top_k, course_filter)

    if not chunks:
        return {
            "answer":  "The knowledge base is empty. Please index your courses first.",
            "sources": [],
        }

    context  = _build_context(chunks)
    messages = _history_messages(history or [])
    messages.append({
        "role":    "user",
        "content": f"Course material context:\n\n{context}\n\nQuestion: {question}",
    })

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    resp   = client.messages.create(
        model=model, max_tokens=1500, system=SYSTEM_PROMPT, messages=messages,
    )

    return {"answer": resp.content[0].text, "sources": chunks}


# ── Streaming query ───────────────────────────────────────────────────────────

def query_brain_stream(
    question: str,
    openai_api_key: str,
    anthropic_api_key: str,
    db_path: str = "./chroma_db",
    top_k: int = 8,
    model: str = "claude-sonnet-4-6",
    history: Optional[list[dict]] = None,
    course_filter: Optional[str] = None,
) -> tuple[list[dict], Iterator[str]]:
    """
    Returns (sources, text_stream).
    Retrieve sources first (fast), then stream Claude's answer token-by-token.
    """
    import anthropic

    chunks = _retrieve(question, openai_api_key, db_path, top_k, course_filter)

    if not chunks:
        def _empty():
            yield "The knowledge base is empty. Please index your courses first."
        return [], _empty()

    context  = _build_context(chunks)
    messages = _history_messages(history or [])
    messages.append({
        "role":    "user",
        "content": f"Course material context:\n\n{context}\n\nQuestion: {question}",
    })

    def _stream() -> Iterator[str]:
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        with client.messages.stream(
            model=model, max_tokens=1500, system=SYSTEM_PROMPT, messages=messages,
        ) as stream:
            yield from stream.text_stream

    return chunks, _stream()
