"""Tests for embedding store -- skipped if fastembed not available."""

import sqlite3

import pytest

try:
    from fastembed import TextEmbedding
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

from projectman.store import Store

pytestmark = pytest.mark.skipif(not HAS_EMBEDDINGS, reason="fastembed not installed")


class TestEmbeddingIndex:
    def test_index_creates_db(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        proj_dir = tmp_project / ".project"
        emb = EmbeddingStore(proj_dir)
        emb.index_item("US-TST-1", "Test Story", "story", "Some content")
        assert (proj_dir / "embeddings.db").exists()

    def test_index_stores_metadata(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        proj_dir = tmp_project / ".project"
        emb = EmbeddingStore(proj_dir)
        emb.index_item("US-TST-1", "Auth System", "story", "Login flow")

        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        row = conn.execute("SELECT id, title, type FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()
        conn.close()
        assert row == ("US-TST-1", "Auth System", "story")

    def test_index_stores_vector_blob(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        proj_dir = tmp_project / ".project"
        emb = EmbeddingStore(proj_dir)
        emb.index_item("US-TST-1", "Test", "story", "Content")

        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        row = conn.execute("SELECT vector FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()
        conn.close()
        assert row[0] is not None
        assert len(row[0]) > 0

    def test_skip_unchanged_content(self, tmp_project):
        """Second index call with identical content should not re-encode."""
        from projectman.embeddings import EmbeddingStore
        proj_dir = tmp_project / ".project"
        emb = EmbeddingStore(proj_dir)

        emb.index_item("US-TST-1", "Test", "story", "Content")
        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        hash1 = conn.execute("SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()[0]
        conn.close()

        # Same content again — should skip
        emb.index_item("US-TST-1", "Test", "story", "Content")
        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        hash2 = conn.execute("SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()[0]
        conn.close()
        assert hash1 == hash2

    def test_update_changed_content(self, tmp_project):
        """Changed content should re-encode and update the hash."""
        from projectman.embeddings import EmbeddingStore
        proj_dir = tmp_project / ".project"
        emb = EmbeddingStore(proj_dir)

        emb.index_item("US-TST-1", "Test", "story", "Original content")
        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        hash1 = conn.execute("SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()[0]
        conn.close()

        emb.index_item("US-TST-1", "Test", "story", "Updated content")
        conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
        hash2 = conn.execute("SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)).fetchone()[0]
        conn.close()
        assert hash1 != hash2


class TestEmbeddingSearch:
    def test_search_returns_results(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        emb.index_item("US-TST-1", "Authentication", "story", "User login and signup system")
        emb.index_item("US-TST-2", "Database", "story", "PostgreSQL schema migrations")

        results = emb.search("login auth")
        assert len(results) == 2
        assert all(hasattr(r, "score") for r in results)

    def test_search_ranks_relevant_first(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        emb.index_item("US-TST-1", "Authentication system", "story", "User login signup password reset")
        emb.index_item("US-TST-2", "Database migration", "story", "Schema updates and table creation")
        emb.index_item("US-TST-3", "CSS styling", "story", "Colors fonts layout responsive design")

        results = emb.search("user authentication login")
        assert results[0].id == "US-TST-1"

    def test_search_empty_index(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        results = emb.search("anything")
        assert results == []

    def test_search_respects_top_k(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        for i in range(5):
            emb.index_item(f"US-TST-{i+1}", f"Story {i+1}", "story", f"Content for story {i+1}")

        results = emb.search("story", top_k=2)
        assert len(results) == 2

    def test_search_scores_are_bounded(self, tmp_project):
        """Cosine similarity of normalized vectors should be in [-1, 1]."""
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        emb.index_item("US-TST-1", "Test story", "story", "Some test content here")

        results = emb.search("test")
        assert len(results) == 1
        assert -1.0 <= results[0].score <= 1.0

    def test_search_result_fields(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        emb = EmbeddingStore(tmp_project / ".project")
        emb.index_item("US-TST-1", "My Title", "task", "Description")

        results = emb.search("title")
        assert results[0].id == "US-TST-1"
        assert results[0].title == "My Title"
        assert results[0].type == "task"
        assert isinstance(results[0].score, float)


class TestReindexAll:
    def test_reindex_indexes_stories_and_tasks(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        store.create_story("Auth Story", "Login system")
        store.create_task("US-TST-1", "Implement login", "Build the login page")

        emb = EmbeddingStore(tmp_project / ".project")
        emb.reindex_all(store)

        conn = sqlite3.connect(str(tmp_project / ".project" / "embeddings.db"))
        count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        conn.close()
        assert count == 2

    def test_reindex_then_search(self, tmp_project):
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        store.create_story("Payment processing", "Stripe integration for checkout")
        store.create_story("Email notifications", "SendGrid transactional emails")
        store.create_task("US-TST-1", "Setup Stripe SDK", "Install and configure Stripe")

        emb = EmbeddingStore(tmp_project / ".project")
        emb.reindex_all(store)

        results = emb.search("payment checkout stripe")
        # Payment story or Stripe task should rank above email
        top_ids = [r.id for r in results[:2]]
        assert "US-TST-1" in top_ids or "US-TST-1-1" in top_ids


class TestVectorRoundtrip:
    def test_encode_decode_preserves_values(self, tmp_project):
        """Vector encode/decode roundtrip should preserve values within float32 precision."""
        from projectman.embeddings import EmbeddingStore
        import numpy as np

        emb = EmbeddingStore(tmp_project / ".project")
        original = [0.1, 0.2, 0.3, -0.5, 0.99]
        blob = emb._encode_vector(original)
        decoded = emb._decode_vector(blob)
        np.testing.assert_allclose(decoded, original, rtol=1e-6)
