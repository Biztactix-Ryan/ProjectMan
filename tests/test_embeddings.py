"""Tests for embedding store -- skipped if fastembed not available."""

import sqlite3

import pytest

try:
    from fastembed import TextEmbedding
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

from projectman.store import Store

try:
    import numpy  # noqa: F401
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

_skip_no_fastembed = pytest.mark.skipif(not HAS_EMBEDDINGS, reason="fastembed not installed")
_skip_no_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed")


@_skip_no_fastembed
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


@_skip_no_fastembed
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


@_skip_no_fastembed
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


    def test_reindex_includes_tags_in_embedding_text(self, tmp_project):
        """Tags should be included in the embedding content for semantic relevance."""
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        store.create_story("API Gateway", "Route management", tags=["backend", "infrastructure"])

        emb = EmbeddingStore(tmp_project / ".project")
        emb.reindex_all(store)

        # Verify the content hash reflects the tags — re-indexing without tags
        # would produce a different hash
        conn = sqlite3.connect(str(tmp_project / ".project" / "embeddings.db"))
        row = conn.execute(
            "SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)
        ).fetchone()
        conn.close()
        hash_with_tags = row[0]

        # Index same item WITHOUT tags — hash should differ
        emb.index_item("US-TST-1", "API Gateway", "story", "Route management")
        conn = sqlite3.connect(str(tmp_project / ".project" / "embeddings.db"))
        row = conn.execute(
            "SELECT content_hash FROM embeddings WHERE id = ?", ("US-TST-1",)
        ).fetchone()
        conn.close()
        hash_without_tags = row[0]

        assert hash_with_tags != hash_without_tags, "Tags should change the embedding content"

    def test_reindex_tags_improve_search_relevance(self, tmp_project):
        """A story tagged with relevant terms should rank higher in search."""
        from projectman.embeddings import EmbeddingStore
        store = Store(tmp_project)
        # Story with 'security' tag but generic title/body
        store.create_story("Module A", "Generic module description", tags=["security", "auth"])
        # Story without security tag
        store.create_story("Module B", "Another generic module description")

        emb = EmbeddingStore(tmp_project / ".project")
        emb.reindex_all(store)

        results = emb.search("security authentication")
        # The tagged story should rank first
        assert results[0].id == "US-TST-1"


@_skip_no_fastembed
class TestBuildContent:
    """Tests for _build_content — skipped along with embeddings module."""

    def test_build_content_with_tags(self):
        from projectman.embeddings import EmbeddingStore
        result = EmbeddingStore._build_content("body text", ["api", "backend"])
        assert "tags:" in result
        assert "api" in result
        assert "backend" in result
        assert "body text" in result

    def test_build_content_without_tags(self):
        from projectman.embeddings import EmbeddingStore
        result = EmbeddingStore._build_content("body text", [])
        assert result == "body text"
        assert "tags:" not in result


@_skip_no_fastembed
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


# --- Cached vector matrix (US-PRJ-38-5) -------------------------------------
# These tests never load a sentence-transformers model: vectors are written
# straight into SQLite and a stub model supplies the query vector.

class _StubModel:
    """Stands in for fastembed's TextEmbedding without loading any model."""

    def __init__(self, vector):
        self.vector = vector
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        import numpy as np
        for _ in texts:
            yield np.asarray(self.vector, dtype=np.float32)


class _RecordingSqlite:
    """Shim over the sqlite3 module that records every executed statement."""

    def __init__(self, real):
        self._real = real
        self.statements = []

    def connect(self, *args, **kwargs):
        return _RecordingConnection(self._real.connect(*args, **kwargs), self.statements)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _RecordingConnection:
    """Proxy around a sqlite3 connection that appends each SQL string to a list."""

    def __init__(self, conn, statements):
        self._conn = conn
        self._statements = statements

    def execute(self, sql, *args, **kwargs):
        self._statements.append(sql)
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _StubCursor:
    """Holds rows already drained from a real cursor."""

    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _InterleavingConnection:
    """Connection proxy that commits a write *after* the vector SELECT reads.

    Simulates another connection committing in the window between
    _load_matrix's vector SELECT and any fingerprint taken after it, which is
    the interleaving that makes a post-SELECT cache stamp unsafe.
    """

    def __init__(self, conn, hook, state):
        self._conn = conn
        self._hook = hook
        self._state = state

    def execute(self, sql, *args, **kwargs):
        if "vector" in sql and "FROM embeddings" in sql:
            rows = self._conn.execute(sql, *args, **kwargs).fetchall()
            if not self._state["fired"]:
                self._state["fired"] = True
                self._hook()
            return _StubCursor(rows)
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _make_store(tmp_project, vectors, query_vector=None):
    """Build an EmbeddingStore with rows inserted directly, no model involved."""
    from projectman.embeddings import EmbeddingStore

    proj_dir = tmp_project / ".project"
    emb = EmbeddingStore(proj_dir)
    conn = sqlite3.connect(str(proj_dir / "embeddings.db"))
    for i, vec in enumerate(vectors):
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (id, title, type, vector, content_hash)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"US-TST-{i+1}", f"Title {i+1}", "story", emb._encode_vector(vec), f"h{i}"),
        )
    conn.commit()
    conn.close()
    emb._invalidate_cache()
    emb._model = _StubModel(query_vector if query_vector is not None else vectors[0])
    return emb


@_skip_no_numpy
class TestCachedVectorMatrix:
    def test_construction_and_index_item_stay_lazy(self, tmp_project, monkeypatch):
        """Nothing builds the matrix until the first search().

        Constructing the store and writing a row through index_item() must not
        read the vector column at all; the cache stays empty until a search
        asks for it, and only then is it built.
        """
        from projectman import embeddings as embeddings_module
        from projectman.embeddings import EmbeddingStore

        recorder = _RecordingSqlite(embeddings_module.sqlite3)
        monkeypatch.setattr(embeddings_module, "sqlite3", recorder)

        emb = EmbeddingStore(tmp_project / ".project")
        assert emb._matrix is None and emb._rows is None and emb._cache_stamp is None

        emb._model = _StubModel([0.1, 0.2, 0.3, 0.4])
        emb.index_item("US-TST-1", "Title 1", "story", "content")
        assert emb._matrix is None and emb._rows is None and emb._cache_stamp is None

        def vector_selects():
            return [s for s in recorder.statements if "SELECT" in s and "vector" in s]

        assert vector_selects() == [], (
            f"no vector SELECT may run before the first search, got {vector_selects()}"
        )

        emb.search("anything")
        assert emb._matrix is not None and emb._matrix.shape == (1, 4)
        assert emb._cache_stamp is not None
        assert len(vector_selects()) == 1

    def test_matrix_shape_and_dtype(self, tmp_project):
        import numpy as np

        vectors = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8], [0.9, 1.0, 1.1, 1.2]]
        emb = _make_store(tmp_project, vectors)

        emb.search("anything")

        assert emb._matrix is not None
        assert emb._matrix.shape == (3, 4)
        assert emb._matrix.dtype == np.float32
        assert emb._rows == [
            ("US-TST-1", "Title 1", "story"),
            ("US-TST-2", "Title 2", "story"),
            ("US-TST-3", "Title 3", "story"),
        ]
        np.testing.assert_allclose(emb._matrix, np.array(vectors, dtype=np.float32))

    def test_vectors_decoded_once_across_two_searches(self, tmp_project, monkeypatch):
        import numpy as np

        from projectman import embeddings as embeddings_module

        vectors = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
        emb = _make_store(tmp_project, vectors)

        calls = {"n": 0}
        real_frombuffer = np.frombuffer

        def counting_frombuffer(*args, **kwargs):
            calls["n"] += 1
            return real_frombuffer(*args, **kwargs)

        monkeypatch.setattr(embeddings_module.np, "frombuffer", counting_frombuffer)

        emb.search("first")
        after_first = calls["n"]
        emb.search("second")

        assert after_first == 1, "cache build should decode all blobs in one np.frombuffer call"
        assert calls["n"] == after_first, "second search must not re-decode vectors"

    def test_per_row_decoder_never_used_during_search(self, tmp_project, monkeypatch):
        """The batched np.frombuffer replaces the legacy per-row struct decoder."""
        vectors = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8], [0.9, 1.0, 1.1, 1.2]]
        emb = _make_store(tmp_project, vectors)

        calls = {"n": 0}
        real_decode = emb._decode_vector

        def counting_decode(blob):
            calls["n"] += 1
            return real_decode(blob)

        monkeypatch.setattr(emb, "_decode_vector", counting_decode)

        emb.search("first")
        emb.search("second")

        assert calls["n"] == 0, "search must not decode vectors row-by-row"

    def test_second_search_reads_no_vectors_from_sqlite(self, tmp_project, monkeypatch):
        """A warm search may run the cheap staleness check, but never re-reads vectors.

        The staleness fingerprint (US-PRJ-38-7) costs one COUNT(*) per search,
        so the assertion is "no SELECT touching the vector column" rather than
        "no SQLite statements at all".
        """
        from projectman import embeddings as embeddings_module

        vectors = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
        emb = _make_store(tmp_project, vectors)

        recorder = _RecordingSqlite(embeddings_module.sqlite3)
        monkeypatch.setattr(embeddings_module, "sqlite3", recorder)

        emb.search("first")
        first_vector_reads = [s for s in recorder.statements if "vector" in s]
        recorder.statements.clear()
        emb.search("second")
        second_vector_reads = [s for s in recorder.statements if "vector" in s]

        assert len(first_vector_reads) == 1
        assert second_vector_reads == [], "second search must not re-read the vector column"
        assert all(
            "COUNT(*)" in stmt for stmt in recorder.statements
        ), f"warm search should only run the fingerprint check, got {recorder.statements}"

    def test_empty_index_returns_empty_and_caches_empty_matrix(self, tmp_project):
        from projectman.embeddings import EmbeddingStore

        emb = EmbeddingStore(tmp_project / ".project")
        emb._model = _StubModel([0.0, 0.0, 0.0, 0.0])

        assert emb.search("anything") == []
        assert emb._matrix is not None
        assert emb._matrix.shape[0] == 0
        assert emb._rows == []

    def test_search_output_matches_manual_scoring(self, tmp_project):
        import numpy as np

        vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0]]
        query = [0.0, 1.0, 0.0, 0.0]
        emb = _make_store(tmp_project, vectors, query_vector=query)

        results = emb.search("q")
        expected = sorted(
            [
                (f"US-TST-{i+1}", float(np.dot(np.array(query, dtype=np.float32), np.array(v, dtype=np.float32))))
                for i, v in enumerate(vectors)
            ],
            key=lambda p: p[1],
            reverse=True,
        )
        assert [(r.id, r.score) for r in results] == expected

    def test_index_item_invalidates_cache(self, tmp_project, monkeypatch):
        vectors = [[0.1, 0.2, 0.3, 0.4]]
        emb = _make_store(tmp_project, vectors)

        emb.search("warm")
        assert emb._matrix is not None

        emb._model = _StubModel([0.9, 0.8, 0.7, 0.6])
        emb.index_item("US-TST-9", "New", "task", "fresh content")
        assert emb._matrix is None and emb._rows is None

        results = emb.search("again")
        assert emb._matrix.shape == (2, 4)
        assert {r.id for r in results} == {"US-TST-1", "US-TST-9"}

    def test_second_store_sees_rows_written_by_first(self, tmp_project):
        """A warm store picks up an INSERT made by another EmbeddingStore instance."""
        from projectman.embeddings import EmbeddingStore

        vectors = [[0.1, 0.2, 0.3, 0.4]]
        store_a = _make_store(tmp_project, vectors)
        store_a.search("warm")
        assert store_a._matrix.shape == (1, 4)

        store_b = EmbeddingStore(tmp_project / ".project")
        store_b._model = _StubModel([0.9, 0.8, 0.7, 0.6])
        store_b.index_item("US-TST-9", "New", "task", "fresh content")

        results = store_a.search("again")
        assert store_a._matrix.shape == (2, 4)
        assert {r.id for r in results} == {"US-TST-1", "US-TST-9"}

    def test_second_store_row_update_is_seen(self, tmp_project):
        """An in-place UPDATE by another connection is picked up.

        Row count and file size are unchanged by such an update, so detection
        rests on SQLite's data_version counter; see
        EmbeddingStore._fingerprint.
        """
        import numpy as np

        vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
        store_a = _make_store(tmp_project, vectors, query_vector=[1.0, 0.0, 0.0, 0.0])
        first = store_a.search("q")
        assert first[0].id == "US-TST-1"
        assert first[0].score == pytest.approx(1.0)

        # Another connection rewrites row 1's vector in place (same row count).
        conn = sqlite3.connect(str(tmp_project / ".project" / "embeddings.db"))
        conn.execute(
            "UPDATE embeddings SET vector = ?, content_hash = ? WHERE id = ?",
            (store_a._encode_vector([0.0, 0.0, 1.0, 0.0]), "changed", "US-TST-1"),
        )
        conn.commit()
        conn.close()

        second = store_a.search("q")
        by_id = {r.id: r.score for r in second}
        assert by_id["US-TST-1"] == pytest.approx(0.0), "stale vector served after update"
        np.testing.assert_allclose(store_a._matrix[0], [0.0, 0.0, 1.0, 0.0])

    def test_warm_cache_reused_when_db_unchanged(self, tmp_project):
        """The fingerprint check must not rebuild the cache spuriously."""
        vectors = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
        emb = _make_store(tmp_project, vectors)

        emb.search("first")
        matrix_id = id(emb._matrix)
        rows_id = id(emb._rows)
        emb.search("second")
        emb.search("third")

        assert id(emb._matrix) == matrix_id
        assert id(emb._rows) == rows_id

    def test_reindex_all_invalidates_cache(self, tmp_project):
        vectors = [[0.1, 0.2, 0.3, 0.4]]
        emb = _make_store(tmp_project, vectors)
        emb.search("warm")
        assert emb._matrix is not None

        class _EmptyStore:
            def list_stories(self):
                return []

            def list_tasks(self):
                return []

        emb.reindex_all(_EmptyStore())
        assert emb._matrix is None and emb._rows is None and emb._cache_stamp is None

    def test_write_landing_after_vector_select_is_not_baked_in_as_current(
        self, tmp_project, monkeypatch
    ):
        """The cache stamp must describe the rows we loaded, not a later state.

        The vector SELECT and the fingerprint query are separate read
        transactions, so another connection can commit between them. This test
        forces the worst-case interleaving deterministically: a proxy around
        the read connection lets the vector SELECT run and drains its rows,
        then commits an INSERT from a *second* EmbeddingStore before handing
        the (pre-insert) rows back to _load_matrix.

        With the stamp taken after the SELECT, that commit would be recorded as
        "current" while the matrix lacks its row, and the next search would
        happily serve the stale cache. With the pre-SELECT stamp the mismatch
        is detected and the matrix is rebuilt.
        """
        from projectman.embeddings import EmbeddingStore

        vectors = [[0.1, 0.2, 0.3, 0.4]]
        store_a = _make_store(tmp_project, vectors)

        store_b = EmbeddingStore(tmp_project / ".project")
        store_b._model = _StubModel([0.9, 0.8, 0.7, 0.6])

        state = {"fired": False}

        def interleaved_write():
            store_b.index_item("US-TST-9", "New", "task", "fresh content")

        real_conn = store_a._read_connection()
        proxy = _InterleavingConnection(real_conn, interleaved_write, state)
        monkeypatch.setattr(store_a, "_read_connection", lambda: proxy)

        first = store_a.search("first")
        assert state["fired"], "interleaved write never ran; test would prove nothing"
        # The matrix was built from rows read before the insert landed.
        assert store_a._matrix.shape == (1, 4)
        assert {r.id for r in first} == {"US-TST-1"}

        # The stamp recorded must be the pre-SELECT one, so this search rebuilds.
        second = store_a.search("second")
        assert store_a._matrix.shape == (2, 4)
        assert {r.id for r in second} == {"US-TST-1", "US-TST-9"}, (
            "cache served stale rows: the fingerprint stored at build time "
            "described a database state the matrix never contained"
        )
