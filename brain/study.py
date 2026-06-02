"""
Study tools: generate flashcards, quizzes, and module summaries from
retrieved course content via Claude.
"""
from dataclasses import dataclass, field


@dataclass
class Flashcard:
    front: str
    back: str


@dataclass
class QuizQuestion:
    question: str
    options: list[str]
    answer: str   # one of the options
    explanation: str


def _context_for_topic(
    topic: str,
    db_path: str,
    top_k: int = 12,
    course_filter: str = None,
) -> tuple[list[dict], str]:
    """Retrieve chunks for a topic and build a context string."""
    from .ingest import embed_texts
    from .retrieval import hybrid_retrieve, rerank

    q_emb  = embed_texts([topic])[0]
    chunks = hybrid_retrieve(topic, q_emb, db_path, top_k=top_k,
                             course_filter=course_filter)
    chunks = rerank(topic, chunks)

    context_parts = []
    for i, c in enumerate(chunks, 1):
        label = c["source"]
        if c.get("page"):
            label += f" (page {c['page']})"
        context_parts.append(f"[{i}] {label}\n{c['text']}")

    return chunks, "\n\n---\n\n".join(context_parts)


def generate_flashcards(
    topic: str,
    anthropic_api_key: str,
    db_path: str,
    model: str = "claude-sonnet-4-6",
    n: int = 10,
    course_filter: str = None,
) -> tuple[list[Flashcard], list[dict]]:
    """Return (flashcards, source_chunks)."""
    import anthropic, json

    sources, context = _context_for_topic(topic, db_path, course_filter=course_filter)

    prompt = f"""Based on the following course material, generate {n} flashcards about: {topic}

{context}

Return a JSON array of objects with keys "front" (question/term) and "back" (answer/definition).
Return ONLY the JSON array, no explanation."""

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    resp   = client.messages.create(model=model, max_tokens=2000,
                                    messages=[{"role": "user", "content": prompt}])
    raw    = resp.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        raw = raw.rsplit("```", 1)[0]

    cards = [Flashcard(**c) for c in json.loads(raw)]
    return cards, sources


def generate_quiz(
    topic: str,
    anthropic_api_key: str,
    db_path: str,
    model: str = "claude-sonnet-4-6",
    n: int = 5,
    course_filter: str = None,
) -> tuple[list[QuizQuestion], list[dict]]:
    """Return (quiz_questions, source_chunks)."""
    import anthropic, json

    sources, context = _context_for_topic(topic, db_path, course_filter=course_filter)

    prompt = f"""Based on the following course material, generate {n} multiple-choice questions about: {topic}

{context}

Return a JSON array. Each object must have:
  "question": str
  "options": list of 4 strings (A, B, C, D options, without the letter prefix)
  "answer": the correct option string (must exactly match one of the options)
  "explanation": one-sentence explanation of why the answer is correct

Return ONLY the JSON array."""

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    resp   = client.messages.create(model=model, max_tokens=2500,
                                    messages=[{"role": "user", "content": prompt}])
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        raw = raw.rsplit("```", 1)[0]

    questions = [QuizQuestion(**q) for q in json.loads(raw)]
    return questions, sources


def summarize_module(
    module_topic: str,
    anthropic_api_key: str,
    db_path: str,
    model: str = "claude-sonnet-4-6",
    course_filter: str = None,
) -> tuple[str, list[dict]]:
    """Return (summary_markdown, source_chunks)."""
    import anthropic

    sources, context = _context_for_topic(module_topic, db_path,
                                          top_k=15, course_filter=course_filter)

    prompt = f"""Summarize the following course material about: {module_topic}

{context}

Write a structured summary in markdown with:
- **Key Concepts** (bullet list)
- **Main Takeaways** (3-5 sentences)
- **Important Terms** (short definitions)

Be concise but complete. Cite sources as [1], [2], etc."""

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    resp   = client.messages.create(model=model, max_tokens=1500,
                                    messages=[{"role": "user", "content": prompt}])
    return resp.content[0].text, sources
