"""
Ingest course files into ChromaDB + build BM25 index.

Pipeline:
  Courses/ → parse file → chunks → embed (OpenAI) → upsert ChromaDB → build BM25
"""
import json
import os
from datetime import datetime

import chromadb

from .parsers import parse_pdf, parse_notebook, parse_text

COLLECTION_NAME = "student_brain"
EMBED_MODEL     = "text-embedding-3-small"
LAST_INDEX_FILE = "last_indexed.json"

PARSEABLE = {
    ".pdf":   parse_pdf,
    ".ipynb": parse_notebook,
    ".txt":   parse_text,
}


def get_collection(db_path: str) -> chromadb.Collection:
    client = chromadb.PersistentClient(path=db_path)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def embed_texts(texts: list[str], api_key: str) -> list[list[float]]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), 100):
        batch = texts[i : i + 100]
        resp  = client.embeddings.create(model=EMBED_MODEL, input=batch)
        all_embeddings.extend(item.embedding for item in resp.data)
    return all_embeddings


def _save_last_indexed(db_path: str) -> None:
    path = os.path.join(db_path, LAST_INDEX_FILE)
    os.makedirs(db_path, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"indexed_at": datetime.now().isoformat()}, f)


def get_last_indexed(db_path: str) -> datetime | None:
    path = os.path.join(db_path, LAST_INDEX_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return datetime.fromisoformat(data["indexed_at"])


def new_files_since_last_index(courses_dir: str, db_path: str) -> list[str]:
    """Return relative paths of files newer than the last index run."""
    last = get_last_indexed(db_path)
    if last is None:
        return []
    new_files = []
    for root, _, files in os.walk(courses_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in PARSEABLE:
                continue
            fpath = os.path.join(root, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime > last:
                new_files.append(os.path.relpath(fpath, courses_dir))
    return new_files


def ingest_courses(
    courses_dir: str,
    openai_api_key: str,
    db_path: str = "./chroma_db",
    log=print,
    anthropic_api_key: str = None,   # optional: enables vision fallback for image PDFs
) -> int:
    from .retrieval import build_bm25_index

    collection  = get_collection(db_path)
    total_files = 0

    for root, _dirs, files in os.walk(courses_dir):
        for fname in sorted(files):
            ext    = os.path.splitext(fname)[1].lower()
            parser = PARSEABLE.get(ext)
            if parser is None:
                continue

            fpath    = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, courses_dir)
            parts    = rel_path.split(os.sep)
            course   = parts[0] if parts else "unknown"

            log(f"Parsing {rel_path}…")
            try:
                raw_chunks = parser(fpath)
            except Exception as e:
                log(f"  ✗ parse error: {e}")
                continue

            # Vision fallback: if PDF pages extracted < 100 chars, use Claude vision
            if ext == ".pdf" and anthropic_api_key:
                raw_chunks = _vision_fallback(fpath, raw_chunks, anthropic_api_key, log)

            if not raw_chunks:
                log("  (empty — skipped)")
                continue

            texts = [c["text"] for c in raw_chunks]
            try:
                embeddings = embed_texts(texts, openai_api_key)
            except Exception as e:
                if "429" in str(e) or "insufficient_quota" in str(e):
                    log("  ✗ embedding error: OpenAI quota exceeded — add credits at platform.openai.com/settings/billing and re-index.")
                else:
                    log(f"  ✗ embedding error: {e}")
                continue

            ids, docs, metas, embeds = [], [], [], []
            for j, (chunk, emb) in enumerate(zip(raw_chunks, embeddings)):
                chunk_id = f"{rel_path}::chunk_{j}"
                meta = {
                    "source":    rel_path,
                    "course":    course,
                    "file_type": ext.lstrip("."),
                    "filename":  fname,
                    **{k: str(v) for k, v in chunk.get("metadata", {}).items()},
                }
                ids.append(chunk_id)
                docs.append(chunk["text"])
                metas.append(meta)
                embeds.append(emb)

            collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeds)
            log(f"  ✓ {fname}: {len(ids)} chunks")
            total_files += 1

    # Rebuild BM25 from everything in ChromaDB
    log("\nBuilding BM25 index…")
    try:
        build_bm25_index(db_path)
        log("  ✓ BM25 index ready")
    except Exception as e:
        log(f"  ✗ BM25 error: {e}")

    _save_last_indexed(db_path)

    total_chunks = collection.count()
    log(f"\nDone — {total_files} files, {total_chunks:,} total chunks.")
    return total_chunks


def _vision_fallback(
    pdf_path: str,
    raw_chunks: list[dict],
    anthropic_api_key: str,
    log,
) -> list[dict]:
    """
    For any PDF page where pdfplumber extracted < 80 chars, re-extract
    using Claude's vision API (rendered page image → text).
    """
    import base64
    import fitz  # PyMuPDF
    import anthropic

    doc    = fitz.open(pdf_path)
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    result = list(raw_chunks)

    for i, chunk in enumerate(result):
        if len(chunk["text"]) >= 80:
            continue   # pdfplumber got enough text
        page_num = chunk["metadata"].get("page", i + 1) - 1
        try:
            page  = doc[page_num]
            pix   = page.get_pixmap(dpi=120)
            b64   = base64.b64encode(pix.tobytes("png")).decode()
            resp  = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text",
                     "text": "Extract all text from this slide. Include every bullet, "
                             "heading, label, and describe any charts or diagrams briefly."},
                ]}],
            )
            vision_text = resp.content[0].text.strip()
            if vision_text:
                result[i] = {"text": vision_text, "metadata": chunk["metadata"]}
                log(f"    👁 vision extraction on page {page_num + 1}")
        except Exception as e:
            log(f"    ✗ vision page {page_num + 1}: {e}")

    return result
