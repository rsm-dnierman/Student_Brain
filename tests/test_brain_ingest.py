"""Tests for brain/ingest.py — embedding and ChromaDB upsert."""
import os
import pytest
from unittest.mock import MagicMock, patch

FAKE_EMBEDDING = [0.1] * 384


def _fake_embed(texts):
    return [FAKE_EMBEDDING[:] for _ in texts]


def _fake_bm25(db_path):
    pass  # no-op — don't need a real BM25 index in most tests


class TestEmbedTexts:
    def test_returns_one_embedding_per_text(self):
        from brain.ingest import embed_texts
        with patch("brain.ingest._get_embedder", return_value=MagicMock(
            encode=lambda texts, show_progress_bar: MagicMock(tolist=lambda: [FAKE_EMBEDDING for _ in texts])
        )):
            result = embed_texts(["a", "b", "c"])
        assert len(result) == 3

    def test_returns_list_of_floats(self):
        from brain.ingest import embed_texts
        import numpy as np
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([FAKE_EMBEDDING])
        with patch("brain.ingest._get_embedder", return_value=mock_embedder):
            result = embed_texts(["hello"])
        assert isinstance(result, list)
        assert isinstance(result[0], list)

    def test_uses_local_model(self):
        from brain.ingest import EMBED_MODEL
        assert "MiniLM" in EMBED_MODEL or "mpnet" in EMBED_MODEL or "minilm" in EMBED_MODEL.lower()


class TestIngestCourses:
    def _setup(self, tmp_path):
        d = tmp_path / "Courses" / "MGTA455" / "module01"
        d.mkdir(parents=True)
        (d / "notes.txt").write_text("# Module 01\n\nIntro to customer analytics.")
        return str(tmp_path / "Courses")

    # build_bm25_index is imported inside ingest_courses(), so patch at source
    _BM25_PATCH = "brain.retrieval.build_bm25_index"

    def test_indexes_text_files(self, tmp_path):
        from brain.ingest import ingest_courses
        courses_dir = self._setup(tmp_path)
        logs = []
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(courses_dir,
                           db_path=str(tmp_path/"db"), log=logs.append)
        assert any("notes.txt" in m for m in logs)
        assert any("chunk" in m for m in logs)

    def test_skips_non_parseable_files(self, tmp_path):
        from brain.ingest import ingest_courses
        d = tmp_path / "Courses" / "course"
        d.mkdir(parents=True)
        (d/"data.xlsx").write_bytes(b"fake")
        (d/"archive.zip").write_bytes(b"fake")
        logs = []
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(str(tmp_path/"Courses"),
                           db_path=str(tmp_path/"db"), log=logs.append)
        assert not any("xlsx" in m for m in logs)

    def test_metadata_stored_with_chunk(self, tmp_path):
        from brain.ingest import ingest_courses, get_collection
        d = tmp_path / "Courses" / "MGTA495"
        d.mkdir(parents=True)
        (d/"notes.txt").write_text("# AI\n\nArtificial intelligence overview.")
        db_path = str(tmp_path/"chroma_db")
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(str(tmp_path/"Courses"), db_path=db_path)
        meta = get_collection(db_path).get(include=["metadatas"])["metadatas"][0]
        assert meta["course"] == "MGTA495"
        assert meta["file_type"] == "txt"

    def test_returns_total_chunk_count(self, tmp_path):
        from brain.ingest import ingest_courses
        courses_dir = self._setup(tmp_path)
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            count = ingest_courses(courses_dir, db_path=str(tmp_path/"db"))
        assert count > 0

    def test_upsert_is_idempotent(self, tmp_path):
        from brain.ingest import ingest_courses
        courses_dir = self._setup(tmp_path)
        db_path = str(tmp_path/"chroma_db")
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            c1 = ingest_courses(courses_dir, db_path=db_path)
            c2 = ingest_courses(courses_dir, db_path=db_path)
        assert c1 == c2

    def test_logs_parse_error_and_continues(self, tmp_path):
        from brain.ingest import ingest_courses
        d = tmp_path / "Courses" / "course"
        d.mkdir(parents=True)
        (d/"bad.pdf").write_bytes(b"not a pdf")
        (d/"good.txt").write_text("# Good\n\nThis is fine content here.")
        logs = []
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(str(tmp_path/"Courses"),
                           db_path=str(tmp_path/"db"), log=logs.append)
        assert any("parse error" in m or "✗" in m for m in logs)
        assert any("good.txt" in m for m in logs)

    def test_saves_last_indexed_timestamp(self, tmp_path):
        from brain.ingest import ingest_courses, get_last_indexed
        courses_dir = self._setup(tmp_path)
        db_path = str(tmp_path/"chroma_db")
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(courses_dir, db_path=db_path)
        assert get_last_indexed(db_path) is not None
