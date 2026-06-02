"""Tests for brain/query.py — retrieval and Claude answering.

Patching strategy (after refactor):
  - brain.query._retrieve      — mock the entire retrieval pipeline
  - brain.query.embed_texts    — for empty-collection test
  - brain.query.get_collection — for empty-collection test
  - anthropic.Anthropic        — mock Claude responses
"""
import pytest
from unittest.mock import MagicMock, patch

FAKE_ANSWER = "RAG stands for Retrieval-Augmented Generation [1]."

FAKE_CHUNKS = [{
    "text":      "RAG uses vector search to retrieve relevant documents.",
    "source":    "MGTA495/module07/module07-RAG.pdf",
    "course":    "MGTA495",
    "filename":  "module07-RAG.pdf",
    "file_type": "pdf",
    "page":      "3",
    "score":     0.88,
}]


def _mock_anthropic(answer=FAKE_ANSWER):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=answer)]
    )
    return client


class TestQueryBrain:
    def _run(self, question="What is RAG?", chunks=None, answer=FAKE_ANSWER,
             model="claude-sonnet-4-6"):
        from brain.query import query_brain
        with patch("brain.query._retrieve", return_value=chunks if chunks is not None else FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(answer)):
            return query_brain(question, "sk-a", "/tmp/db",
                               top_k=5, model=model)

    def test_returns_answer_string(self):
        result = self._run()
        assert isinstance(result["answer"], str) and len(result["answer"]) > 0

    def test_returns_sources_list(self):
        assert len(self._run()["sources"]) > 0

    def test_source_has_required_fields(self):
        src = self._run()["sources"][0]
        for f in ("text", "source", "course", "filename", "score"):
            assert f in src, f"Missing: {f}"

    def test_score_preserved_from_retrieval(self):
        assert self._run()["sources"][0]["score"] == pytest.approx(0.88, abs=0.01)

    def test_score_between_0_and_1(self):
        for src in self._run()["sources"]:
            assert 0.0 <= src["score"] <= 1.0

    def test_empty_retrieval_returns_graceful_message(self):
        result = self._run(chunks=[])
        assert "empty" in result["answer"].lower() or "index" in result["answer"].lower()
        assert result["sources"] == []

    def test_claude_receives_numbered_context(self):
        from brain.query import query_brain
        mock_client = _mock_anthropic()
        with patch("brain.query._retrieve", return_value=FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=mock_client):
            query_brain("What is RAG?", "sk-a", "/tmp/db")
        content = mock_client.messages.create.call_args.kwargs["messages"][-1]["content"]
        assert "[1]" in content

    def test_claude_receives_the_question(self):
        from brain.query import query_brain
        mock_client = _mock_anthropic()
        with patch("brain.query._retrieve", return_value=FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=mock_client):
            query_brain("Explain uplift modeling", "sk-a", "/tmp/db")
        content = mock_client.messages.create.call_args.kwargs["messages"][-1]["content"]
        assert "Explain uplift modeling" in content

    def test_page_number_in_source(self):
        assert self._run()["sources"][0]["page"] == "3"

    def test_uses_specified_model(self):
        from brain.query import query_brain
        mock_client = _mock_anthropic()
        with patch("brain.query._retrieve", return_value=FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=mock_client):
            query_brain("Q?", "sk-a", "/tmp/db", model="claude-haiku-4-5-20251001")
        assert mock_client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_history_passed_to_claude(self):
        from brain.query import query_brain
        mock_client = _mock_anthropic()
        history = [{"role": "user", "content": "Prior question"},
                   {"role": "assistant", "content": "Prior answer"}]
        with patch("brain.query._retrieve", return_value=FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=mock_client):
            query_brain("Follow-up?", "sk-a", "/tmp/db", history=history)
        messages = mock_client.messages.create.call_args.kwargs["messages"]
        # History turns should appear before the final user turn
        assert len(messages) >= 3

    def test_stream_returns_sources_and_generator(self):
        from brain.query import query_brain_stream

        def _fake_text_stream():
            yield "Hello "
            yield "world"

        mock_client  = MagicMock()
        mock_ctx     = MagicMock()
        mock_ctx.__enter__ = lambda s: s
        mock_ctx.__exit__  = MagicMock(return_value=False)
        mock_ctx.text_stream = _fake_text_stream()
        mock_client.messages.stream.return_value = mock_ctx

        # Consume the stream while the mock is still active
        with patch("brain.query._retrieve", return_value=FAKE_CHUNKS), \
             patch("anthropic.Anthropic", return_value=mock_client):
            sources, stream = query_brain_stream("Q?", "sk-a", "/tmp/db")
            full = "".join(stream)   # consume inside the patch context

        assert sources == FAKE_CHUNKS
        assert full == "Hello world"
