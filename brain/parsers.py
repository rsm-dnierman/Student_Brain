"""
Parse course files into chunks of text with metadata.

Each parser returns a list of dicts:
  {"text": str, "metadata": dict}

Supported: PDF, Jupyter notebook (.ipynb), plain text (.txt)
"""
import json


def parse_pdf(path: str) -> list[dict]:
    """Extract text page-by-page. Each page becomes one chunk."""
    import pdfplumber

    chunks = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append({"text": text, "metadata": {"page": i + 1}})
    return chunks


def parse_notebook(path: str) -> list[dict]:
    """
    Extract each non-empty cell as a chunk.
    Code cells include up to 500 chars of output so context is self-contained.
    """
    with open(path) as f:
        nb = json.load(f)

    chunks = []
    for i, cell in enumerate(nb.get("cells", [])):
        cell_type = cell.get("cell_type", "code")
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue

        text = source
        if cell_type == "code":
            output_lines = []
            for out in cell.get("outputs", []):
                raw = out.get("text") or out.get("data", {}).get("text/plain", [])
                if isinstance(raw, list):
                    raw = "".join(raw)
                if raw:
                    output_lines.append(raw[:500])
            if output_lines:
                text += "\n\nOutput:\n" + "\n".join(output_lines)

        chunks.append({
            "text": text,
            "metadata": {"cell_index": i, "cell_type": cell_type},
        })
    return chunks


def parse_text(path: str) -> list[dict]:
    """
    Split markdown-style text into sections at heading boundaries.
    Merge consecutive short sections so each chunk has enough context.
    """
    with open(path) as f:
        content = f.read().strip()

    if not content:
        return []

    # Split into sections at markdown headings
    raw_sections: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        if line.startswith("#") and current:
            raw_sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        raw_sections.append("\n".join(current))

    # Merge short sections (< 200 chars) into the next one, cap at ~1500 chars
    chunks = []
    buffer = ""
    for section in raw_sections:
        section = section.strip()
        if not section:
            continue
        if buffer and len(buffer) + len(section) < 1500:
            buffer += "\n\n" + section
        else:
            if buffer:
                chunks.append({"text": buffer, "metadata": {}})
            buffer = section
    if buffer:
        chunks.append({"text": buffer, "metadata": {}})

    return chunks
