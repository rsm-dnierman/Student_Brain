"""Tests for brain/parsers.py — file-type specific text extraction."""
import json
import pytest
from unittest.mock import MagicMock, patch


# ── parse_pdf ─────────────────────────────────────────────────────────────────

class TestParsePdf:
    def _mock_pdfplumber(self, pages: list[str]):
        mock_pages = [MagicMock(**{"extract_text.return_value": t}) for t in pages]
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = mock_pages
        return mock_pdf

    def test_returns_one_chunk_per_page(self):
        from brain.parsers import parse_pdf
        with patch("pdfplumber.open", return_value=self._mock_pdfplumber(["A", "B", "C"])):
            assert len(parse_pdf("fake.pdf")) == 3

    def test_chunk_text_matches_page_text(self):
        from brain.parsers import parse_pdf
        with patch("pdfplumber.open", return_value=self._mock_pdfplumber(["Hello world"])):
            assert parse_pdf("fake.pdf")[0]["text"] == "Hello world"

    def test_page_number_in_metadata(self):
        from brain.parsers import parse_pdf
        with patch("pdfplumber.open", return_value=self._mock_pdfplumber(["First", "Second"])):
            chunks = parse_pdf("fake.pdf")
        assert chunks[0]["metadata"]["page"] == 1
        assert chunks[1]["metadata"]["page"] == 2

    def test_skips_empty_pages(self):
        from brain.parsers import parse_pdf
        with patch("pdfplumber.open",
                   return_value=self._mock_pdfplumber(["Real", "", "   ", "More"])):
            assert len(parse_pdf("fake.pdf")) == 2

    def test_returns_empty_list_for_blank_pdf(self):
        from brain.parsers import parse_pdf
        with patch("pdfplumber.open", return_value=self._mock_pdfplumber(["", "  "])):
            assert parse_pdf("fake.pdf") == []


# ── parse_notebook ────────────────────────────────────────────────────────────

class TestParseNotebook:
    def _write_notebook(self, tmp_path, cells):
        path = str(tmp_path / "test.ipynb")
        with open(path, "w") as f:
            json.dump({"cells": cells, "nbformat": 4, "nbformat_minor": 5}, f)
        return path

    def _code(self, src, outputs=None):
        return {"cell_type": "code", "source": [src], "outputs": outputs or []}

    def _md(self, src):
        return {"cell_type": "markdown", "source": [src], "outputs": []}

    def test_one_chunk_per_non_empty_cell(self, tmp_path):
        from brain.parsers import parse_notebook
        path = self._write_notebook(tmp_path, [self._md("# Intro"), self._code("x=1"), self._md("Text")])
        assert len(parse_notebook(path)) == 3

    def test_skips_empty_cells(self, tmp_path):
        from brain.parsers import parse_notebook
        path = self._write_notebook(tmp_path, [self._code(""), self._md("  "), self._code("print('hi')")])
        assert len(parse_notebook(path)) == 1

    def test_cell_type_in_metadata(self, tmp_path):
        from brain.parsers import parse_notebook
        path = self._write_notebook(tmp_path, [self._code("x=1"), self._md("# Title")])
        types = [c["metadata"]["cell_type"] for c in parse_notebook(path)]
        assert "code" in types and "markdown" in types

    def test_cell_index_in_metadata(self, tmp_path):
        from brain.parsers import parse_notebook
        path = self._write_notebook(tmp_path, [self._code("a=1"), self._code("b=2")])
        chunks = parse_notebook(path)
        assert chunks[0]["metadata"]["cell_index"] == 0
        assert chunks[1]["metadata"]["cell_index"] == 1

    def test_code_output_appended(self, tmp_path):
        from brain.parsers import parse_notebook
        cell = {"cell_type": "code", "source": ["print('hi')"],
                "outputs": [{"output_type": "stream", "text": ["hi\n"]}]}
        path = self._write_notebook(tmp_path, [cell])
        text = parse_notebook(path)[0]["text"]
        assert "Output:" in text and "hi" in text

    def test_output_truncated_to_500_chars(self, tmp_path):
        from brain.parsers import parse_notebook
        cell = {"cell_type": "code", "source": ["pass"],
                "outputs": [{"output_type": "stream", "text": ["x" * 1000]}]}
        path = self._write_notebook(tmp_path, [cell])
        # source + "Output:\n" + 500 chars max → well under 600
        assert len(parse_notebook(path)[0]["text"]) < 600


# ── parse_text ────────────────────────────────────────────────────────────────

class TestParseText:
    def _write(self, tmp_path, content):
        p = str(tmp_path / "page.txt")
        open(p, "w").write(content)
        return p

    def test_empty_file_returns_empty_list(self, tmp_path):
        from brain.parsers import parse_text
        assert parse_text(self._write(tmp_path, "")) == []

    def test_short_file_is_single_chunk(self, tmp_path):
        from brain.parsers import parse_text
        chunks = parse_text(self._write(tmp_path, "# Overview\n\nShort description here."))
        assert len(chunks) == 1
        assert "Overview" in chunks[0]["text"]

    def test_splits_long_sections_at_headings(self, tmp_path):
        from brain.parsers import parse_text
        # Each section is ~1010 chars — combined (2020) exceeds the 1500 merge threshold
        section_body = "word " * 200  # 1000 chars
        content = f"# Section A\n{section_body}\n# Section B\n{section_body}"
        chunks = parse_text(self._write(tmp_path, content))
        combined = " ".join(c["text"] for c in chunks)
        assert len(chunks) >= 2
        assert "Section A" in combined
        assert "Section B" in combined

    def test_merges_short_sections(self, tmp_path):
        from brain.parsers import parse_text
        # Three tiny sections — all fit under 1500 together → merged into 1 chunk
        content = "# A\nShort.\n# B\nShort.\n# C\nShort."
        chunks = parse_text(self._write(tmp_path, content))
        assert len(chunks) == 1

    def test_content_preserved(self, tmp_path):
        from brain.parsers import parse_text
        chunks = parse_text(self._write(tmp_path, "# RAG\n\nRetrieval-Augmented Generation."))
        assert "Retrieval-Augmented Generation" in " ".join(c["text"] for c in chunks)
