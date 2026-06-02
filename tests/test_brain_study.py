"""Tests for brain/study.py — flashcard, quiz, and summary generation."""
import json
import pytest
from unittest.mock import MagicMock, patch

FAKE_EMBEDDING = [0.1] * 1536
FAKE_CHUNKS = [{"text": "RAG retrieves relevant docs.", "source": "a.pdf",
                "course": "A", "filename": "a.pdf", "file_type": "pdf",
                "page": "1", "score": 0.9}]


def _mock_retrieve(chunks=None):
    """Patch _context_for_topic to avoid real network/DB calls."""
    context = "\n".join(f"[{i+1}] {c['source']}\n{c['text']}"
                        for i, c in enumerate(chunks or FAKE_CHUNKS))
    return chunks or FAKE_CHUNKS, context


def _mock_anthropic(text):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=text)])
    return client


class TestGenerateFlashcards:
    CARDS_JSON = json.dumps([
        {"front": "What is RAG?", "back": "Retrieval-Augmented Generation"},
        {"front": "What does BM25 stand for?", "back": "Best Match 25"},
    ])

    def test_returns_flashcard_objects(self):
        from brain.study import generate_flashcards, Flashcard
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.CARDS_JSON)):
            cards, sources = generate_flashcards("RAG", "sk-o", "sk-a", "/tmp/db")
        assert all(isinstance(c, Flashcard) for c in cards)

    def test_correct_number_of_cards(self):
        from brain.study import generate_flashcards
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.CARDS_JSON)):
            cards, _ = generate_flashcards("RAG", "sk-o", "sk-a", "/tmp/db", n=2)
        assert len(cards) == 2

    def test_strips_markdown_fences(self):
        from brain.study import generate_flashcards
        fenced = f"```json\n{self.CARDS_JSON}\n```"
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(fenced)):
            cards, _ = generate_flashcards("RAG", "sk-o", "sk-a", "/tmp/db")
        assert len(cards) == 2

    def test_returns_source_chunks(self):
        from brain.study import generate_flashcards
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.CARDS_JSON)):
            _, sources = generate_flashcards("RAG", "sk-o", "sk-a", "/tmp/db")
        assert isinstance(sources, list)
        assert len(sources) > 0

    def test_card_has_front_and_back(self):
        from brain.study import generate_flashcards
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.CARDS_JSON)):
            cards, _ = generate_flashcards("RAG", "sk-o", "sk-a", "/tmp/db")
        assert cards[0].front == "What is RAG?"
        assert "Retrieval" in cards[0].back


class TestGenerateQuiz:
    QUIZ_JSON = json.dumps([{
        "question": "What does RAG stand for?",
        "options": ["Random Access Generation","Retrieval-Augmented Generation",
                    "Recurrent Attention Graph","Ranked Association Grid"],
        "answer": "Retrieval-Augmented Generation",
        "explanation": "RAG combines retrieval with generation.",
    }])

    def test_returns_quiz_question_objects(self):
        from brain.study import generate_quiz, QuizQuestion
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.QUIZ_JSON)):
            questions, _ = generate_quiz("RAG", "sk-o", "sk-a", "/tmp/db")
        assert all(isinstance(q, QuizQuestion) for q in questions)

    def test_question_has_four_options(self):
        from brain.study import generate_quiz
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.QUIZ_JSON)):
            questions, _ = generate_quiz("RAG", "sk-o", "sk-a", "/tmp/db")
        assert len(questions[0].options) == 4

    def test_answer_is_one_of_the_options(self):
        from brain.study import generate_quiz
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.QUIZ_JSON)):
            questions, _ = generate_quiz("RAG", "sk-o", "sk-a", "/tmp/db")
        for q in questions:
            assert q.answer in q.options


class TestSummarizeModule:
    SUMMARY = "## Key Concepts\n- RAG\n- Embeddings\n\n## Main Takeaways\nRAG improves LLMs [1]."

    def test_returns_markdown_string(self):
        from brain.study import summarize_module
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.SUMMARY)):
            summary, _ = summarize_module("RAG", "sk-o", "sk-a", "/tmp/db")
        assert isinstance(summary, str)
        assert len(summary) > 10

    def test_returns_source_chunks(self):
        from brain.study import summarize_module
        with patch("brain.study._context_for_topic", return_value=_mock_retrieve()), \
             patch("anthropic.Anthropic", return_value=_mock_anthropic(self.SUMMARY)):
            _, sources = summarize_module("RAG", "sk-o", "sk-a", "/tmp/db")
        assert isinstance(sources, list)


class TestRatings:
    def test_log_and_retrieve(self, tmp_path):
        from brain.ratings import log_rating, get_ratings
        import brain.ratings as r_mod
        original = r_mod.RATINGS_FILE
        r_mod.RATINGS_FILE = str(tmp_path / "ratings.jsonl")
        try:
            log_rating("What is RAG?", "RAG is...", "up", [{"source": "a.pdf"}])
            log_rating("What is BM25?", "BM25 is...", "down", [])
            ratings = get_ratings()
            assert len(ratings) == 2
            assert ratings[0]["rating"] == "up"
            assert ratings[1]["rating"] == "down"
        finally:
            r_mod.RATINGS_FILE = original

    def test_summary_counts(self, tmp_path):
        from brain.ratings import log_rating, rating_summary
        import brain.ratings as r_mod
        original = r_mod.RATINGS_FILE
        r_mod.RATINGS_FILE = str(tmp_path / "ratings.jsonl")
        try:
            log_rating("Q1", "A1", "up",   [])
            log_rating("Q2", "A2", "up",   [])
            log_rating("Q3", "A3", "down", [])
            s = rating_summary()
            assert s["total"] == 3
            assert s["up"]    == 2
            assert s["down"]  == 1
        finally:
            r_mod.RATINGS_FILE = original

    def test_empty_file_returns_empty_list(self, tmp_path):
        from brain.ratings import get_ratings
        import brain.ratings as r_mod
        original = r_mod.RATINGS_FILE
        r_mod.RATINGS_FILE = str(tmp_path / "nonexistent.jsonl")
        try:
            assert get_ratings() == []
        finally:
            r_mod.RATINGS_FILE = original
