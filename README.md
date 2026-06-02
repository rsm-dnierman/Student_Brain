# Student Brain

A Streamlit app that scrapes your MSBA course materials, indexes them into a local vector database, and lets you chat with them using Claude — with every answer cited back to the source.

## How it works

```
Course sites → Scrapers → Courses/ → Ingest → ChromaDB + BM25 → Hybrid retrieval → Claude → cited answer
```

1. **Scrape** — pull files from Canvas, Django-based course sites, or any URL
2. **Index** — parse PDFs/notebooks/text → chunk → embed (OpenAI) → store in ChromaDB, build BM25 index
3. **Chat** — questions are retrieved via hybrid search (vector + BM25), reranked, then sent to Claude with citations

## Setup

**Prerequisites:** Python 3.11+, an OpenAI API key (embeddings), an Anthropic API key (Claude answers)

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys (or enter them in the app UI):

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
CANVAS_ACCESS_TOKEN=...       # optional, for Canvas scraping
```

## Running the app

```bash
streamlit run scraper_app.py
```

The app walks you through four steps:

| Step | What happens |
|------|-------------|
| 📥 Data Sources | Add Canvas, Django course sites, or generic URLs |
| 🗃️ Scrape & Preview | Download files into `Courses/` |
| 🔑 AI Setup | Enter OpenAI + Anthropic keys, index files into ChromaDB |
| 🧠 Student Brain | Chat with your course materials |

The **Brain Chat** page (`pages/1_Brain_Chat.py`) is also available directly for re-indexing and chatting once you've already scraped.

## Supported file types

| Format | Parser |
|--------|--------|
| PDF | pdfplumber (text) + Claude vision fallback for image-based slides |
| Jupyter notebooks (`.ipynb`) | Cell-by-cell extraction |
| Plain text | Direct chunking |

## Project structure

```
scraper_app.py        # Main Streamlit app (4-step setup wizard)
pages/
  1_Brain_Chat.py     # Standalone chat interface
brain/
  ingest.py           # File parsing, embedding, ChromaDB upsert, BM25 build
  parsers.py          # PDF / notebook / text parsers
  retrieval.py        # Hybrid retrieval (vector + BM25) and reranking
  query.py            # RAG query logic (blocking + streaming)
  ratings.py          # Answer feedback/ratings
  study.py            # Study mode helpers
scrapers/
  canvas.py           # Canvas LMS scraper (uses API token)
  django.py           # Django-based course site scraper
  generic.py          # Generic URL scraper
  utils.py            # Shared scraper utilities
tests/                # pytest test suite
Courses/              # Downloaded course files (gitignored)
chroma_db/            # Local vector store (gitignored)
```

## Running tests

```bash
pytest
```

## Notes

- `Courses/` and `chroma_db/` are gitignored — they stay local only.
- The vision fallback (PDF pages with < 80 chars of extracted text) uses `claude-haiku-4-5` to OCR slide images via PyMuPDF.
- Retrieval uses cosine similarity (ChromaDB) fused with BM25, then cross-encoder reranking, so keyword-heavy queries still surface the right chunks.
