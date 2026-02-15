"""Tests for embedding store -- skipped if sentence-transformers not available."""

import pytest

try:
    from sentence_transformers import SentenceTransformer
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

from projectman.store import Store


@pytest.mark.skipif(not HAS_EMBEDDINGS, reason="sentence-transformers not installed")
class TestEmbeddingStore:
    def test_index_and_search(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        store.create_story("Authentication system", "Login and signup")
        store.create_story("Database migration", "Schema updates")

        emb = EmbeddingStore(tmp_project / ".project")
        emb.reindex_all(store)

        results = emb.search("login auth", top_k=5)
        assert len(results) > 0
        assert results[0].id == "US-TST-1"  # Auth story should rank first

    def test_skip_unchanged(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        store.create_story("Test", "Content")

        emb = EmbeddingStore(tmp_project / ".project")
        emb.index_item("US-TST-1", "Test", "story", "Content")
        # Second call should skip (same hash)
        emb.index_item("US-TST-1", "Test", "story", "Content")
