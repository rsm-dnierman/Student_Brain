"""Tests for brain/retrieval.py — BM25 + RRF + re-ranking."""
import pickle
import pytest
from unittest.mock import MagicMock, patch

FAKE_EMBEDDING = [0.1] * 1536


# ── RRF ───────────────────────────────────────────────────────────────────────
class TestRRF:
    def test_merges_two_ranked_lists(self):
        from brain.retrieval import rrf_fuse
        result = rrf_fuse([["a", "b", "c"], ["b", "c", "d"]])
        assert result.index("b") < result.index("a")

    def test_returns_all_unique_ids(self):
        from brain.retrieval import rrf_fuse
        assert set(rrf_fuse([["a","b"],["c","d"]])) == {"a","b","c","d"}

    def test_single_list_preserves_order(self):
        from brain.retrieval import rrf_fuse
        ids = ["x","y","z"]
        assert rrf_fuse([ids]) == ids

    def test_empty_lists_returns_empty(self):
        from brain.retrieval import rrf_fuse
        assert rrf_fuse([[],[]]) == []

    def test_item_in_both_lists_ranks_first(self):
        from brain.retrieval import rrf_fuse
        # "b" appears in both → should beat "a" (only in list1)
        result = rrf_fuse([["a","b"], ["b"]])
        assert result[0] == "b"


# ── BM25 index ────────────────────────────────────────────────────────────────
class TestBM25Index:
    def test_build_saves_pickle(self, tmp_path):
        from brain.retrieval import build_bm25_index
        import chromadb

        db_path = str(tmp_path / "chroma_db")
        col = chromadb.PersistentClient(path=db_path)\
                      .get_or_create_collection("student_brain")
        col.add(ids=["1","2"],
                documents=["RAG is retrieval augmented generation",
                           "Uplift modeling measures treatment effect"],
                metadatas=[{"course":"A"},{"course":"B"}],
                embeddings=[FAKE_EMBEDDING, [0.2]*1536])

        build_bm25_index(db_path)

        pkl_path = str(tmp_path / "chroma_db" / "bm25_index.pkl")
        assert __import__("os").path.exists(pkl_path)
        with open(pkl_path,"rb") as f:
            idx = pickle.load(f)
        assert "bm25" in idx and len(idx["ids"]) == 2

    def test_load_returns_none_if_missing(self, tmp_path):
        from brain.retrieval import load_bm25_index
        assert load_bm25_index(str(tmp_path / "nonexistent")) is None

    def test_bm25_scores_relevant_doc_higher(self, tmp_path):
        from brain.retrieval import build_bm25_index, load_bm25_index
        import chromadb

        db_path = str(tmp_path / "chroma_db")
        col = chromadb.PersistentClient(path=db_path)\
                      .get_or_create_collection("student_brain")

        # BM25Okapi IDF = log((N-freq+0.5)/(freq+0.5)). With N=2,freq=1 → log(1)=0.
        # Add a 3rd neutral doc so term frequencies give non-zero IDF for query terms.
        doc_rag     = ("retrieval augmented generation vector search embedding "
                       "semantic similarity rag pipeline context chunks") * 4
        doc_sql     = ("structured query language joins tables relational database "
                       "select where group by primary key foreign key index") * 4
        doc_neutral = ("business analytics marketing customer segmentation "
                       "revenue profit loss forecasting budget stakeholder") * 4

        col.add(ids=["1","2","3"], documents=[doc_rag, doc_sql, doc_neutral],
                metadatas=[{"course":"A"},{"course":"B"},{"course":"C"}],
                embeddings=[FAKE_EMBEDDING, [0.2]*1536, [0.3]*1536])

        build_bm25_index(db_path)
        idx = load_bm25_index(db_path)

        scores = idx["bm25"].get_scores(["retrieval","augmented","vector","semantic"])
        assert scores[0] > 0,    "RAG doc should have positive score for retrieval terms"
        assert scores[0] > scores[1], "RAG doc should outscore SQL doc on retrieval query"


# ── Re-ranking ────────────────────────────────────────────────────────────────
CHUNKS = [
    {"text":"Uplift modeling measures the incremental effect of treatment.",
     "source":"a.pdf","course":"A","filename":"a.pdf","file_type":"pdf","page":"1","score":0.9},
    {"text":"SQL is used to query relational databases.",
     "source":"b.pdf","course":"B","filename":"b.pdf","file_type":"pdf","page":"2","score":0.7},
]

class TestRerank:
    def test_returns_same_length(self):
        from brain.retrieval import rerank
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.9, 0.3]
        with patch("brain.retrieval._reranker_cache", mock_ce):
            assert len(rerank("uplift", CHUNKS)) == 2

    def test_reorders_by_cross_encoder_score(self):
        from brain.retrieval import rerank
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.3, 0.95]   # second chunk wins
        with patch("brain.retrieval._reranker_cache", mock_ce):
            result = rerank("SQL databases", CHUNKS)
        assert result[0]["source"] == "b.pdf"

    def test_falls_back_when_predict_raises(self):
        """If the reranker throws for any reason, original order is preserved."""
        from brain.retrieval import rerank
        import brain.retrieval as r_mod
        mock_ce = MagicMock()
        mock_ce.predict.side_effect = RuntimeError("model error")
        original = r_mod._reranker_cache
        r_mod._reranker_cache = mock_ce
        try:
            result = rerank("anything", CHUNKS)
            assert result == CHUNKS
        finally:
            r_mod._reranker_cache = original

    def test_empty_input_returns_empty(self):
        from brain.retrieval import rerank
        assert rerank("query", []) == []
