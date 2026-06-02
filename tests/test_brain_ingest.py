"""Tests for brain/ingest.py — embedding and ChromaDB upsert."""
import os
import pytest
from unittest.mock import MagicMock, patch

FAKE_EMBEDDING = [0.1] * 1536


def _fake_embed(texts, api_key=None):
    return [FAKE_EMBEDDING[:] for _ in texts]


def _fake_bm25(db_path):
    pass  # no-op — don't need a real BM25 index in most tests


class TestEmbedTexts:
    def test_calls_openai_with_correct_model(self):
        from brain.ingest import embed_texts
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=FAKE_EMBEDDING)])
        with patch("openai.OpenAI", return_value=mock_client):
            embed_texts(["hello"], "sk-test")
        assert mock_client.embeddings.create.call_args.kwargs["model"] == "text-embedding-3-small"

    def test_returns_one_embedding_per_text(self):
        from brain.ingest import embed_texts
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=FAKE_EMBEDDING) for _ in range(3)])
        with patch("openai.OpenAI", return_value=mock_client):
            result = embed_texts(["a","b","c"], "sk-test")
        assert len(result) == 3

    def test_batches_large_inputs(self):
        from brain.ingest import embed_texts
        mock_client = MagicMock()
        mock_client.embeddings.create.side_effect = lambda model, input: MagicMock(
            data=[MagicMock(embedding=FAKE_EMBEDDING) for _ in input])
        texts = [f"t{i}" for i in range(250)]
        with patch("openai.OpenAI", return_value=mock_client):
            result = embed_texts(texts, "sk-test")
        assert mock_client.embeddings.create.call_count == 3
        assert len(result) == 250


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
            ingest_courses(courses_dir, "sk-test",
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
            ingest_courses(str(tmp_path/"Courses"), "sk-test",
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
            ingest_courses(str(tmp_path/"Courses"), "sk-test", db_path=db_path)
        meta = get_collection(db_path).get(include=["metadatas"])["metadatas"][0]
        assert meta["course"] == "MGTA495"
        assert meta["file_type"] == "txt"

    def test_returns_total_chunk_count(self, tmp_path):
        from brain.ingest import ingest_courses
        courses_dir = self._setup(tmp_path)
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            count = ingest_courses(courses_dir, "sk-test", db_path=str(tmp_path/"db"))
        assert count > 0

    def test_upsert_is_idempotent(self, tmp_path):
        from brain.ingest import ingest_courses
        courses_dir = self._setup(tmp_path)
        db_path = str(tmp_path/"chroma_db")
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            c1 = ingest_courses(courses_dir, "sk-test", db_path=db_path)
            c2 = ingest_courses(courses_dir, "sk-test", db_path=db_path)
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
            ingest_courses(str(tmp_path/"Courses"), "sk-test",
                           db_path=str(tmp_path/"db"), log=logs.append)
        assert any("parse error" in m or "✗" in m for m in logs)
        assert any("good.txt" in m for m in logs)

    def test_saves_last_indexed_timestamp(self, tmp_path):
        from brain.ingest import ingest_courses, get_last_indexed
        courses_dir = self._setup(tmp_path)
        db_path = str(tmp_path/"chroma_db")
        with patch("brain.ingest.embed_texts", side_effect=_fake_embed), \
             patch(self._BM25_PATCH, side_effect=_fake_bm25):
            ingest_courses(courses_dir, "sk-test", db_path=db_path)
        assert get_last_indexed(db_path) is not None
