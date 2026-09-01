"""Ranking-identity and performance tests for the vectorised EmbeddingStore.search().

No fastembed model is ever loaded: vectors are written straight into the sqlite
`embeddings` table and the query vector comes from the stub model helper.
"""

import os
import sqlite3
import time

import pytest

from test_embeddings import _make_store, _skip_no_numpy

_skip_bench = pytest.mark.skipif(
    bool(os.environ.get("PROJECTMAN_SKIP_BENCH")),
    reason="PROJECTMAN_SKIP_BENCH set -- timing-sensitive benchmark disabled",
)


def _random_unit_vectors(n, dim, seed):
    import numpy as np

    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs


def _old_search(rows, matrix, query_vec, top_k):
    """Reference implementation of the pre-vectorisation per-row scoring loop.

    Deliberately conservative: it scores rows that have *already* been decoded
    into ``matrix``, so it measures only the per-row ``np.dot`` + full sort. The
    real pre-sprint search() also opened a fresh connection and ran
    ``_decode_vector`` (struct.unpack) on every blob on *every* query, which is
    far more expensive. Benchmarks built on this helper therefore under-state
    the speedup; ``_pre_sprint_search`` below is the faithful end-to-end
    reference.
    """
    import numpy as np

    from projectman.embeddings import EmbeddingResult

    results = []
    for (row_id, title, item_type), stored_vec in zip(rows, matrix):
        score = np.dot(query_vec, stored_vec)
        results.append(
            EmbeddingResult(id=row_id, title=title, type=item_type, score=float(score))
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _pre_sprint_search(emb, query, top_k):
    """Faithful copy of search() as it stood before the vectorisation sprint.

    Fresh connect + SELECT of every vector blob + per-row struct.unpack decode
    + per-row np.dot + full sort, on every single query. Kept here purely as
    the benchmark baseline; it must never be imported by production code.
    """
    import numpy as np

    from projectman.embeddings import EmbeddingResult

    query_vec = next(emb.model.embed([query]))

    conn = sqlite3.connect(str(emb.db_path))
    rows = conn.execute("SELECT id, title, type, vector FROM embeddings").fetchall()
    conn.close()

    results = []
    for row_id, title, item_type, blob in rows:
        stored_vec = emb._decode_vector(blob)
        score = np.dot(query_vec, stored_vec)
        results.append(
            EmbeddingResult(id=row_id, title=title, type=item_type, score=float(score))
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


@_skip_no_numpy
class TestVectorisedRankingIdentity:
    """search() must return exactly what the old per-row loop returned."""

    @pytest.mark.parametrize("top_k", [1, 5, 10, 199, 200, 250])
    def test_matches_old_loop_for_fixed_seed(self, tmp_project, top_k):
        import numpy as np

        vecs = _random_unit_vectors(200, 32, seed=20260822)
        query = _random_unit_vectors(1, 32, seed=99)[0]
        emb = _make_store(
            tmp_project, [v.tolist() for v in vecs], query_vector=query.tolist()
        )

        new_results = emb.search("q", top_k=top_k)

        matrix, rows = emb._load_matrix()
        old_results = _old_search(rows, matrix, np.asarray(query, dtype=np.float32), top_k)

        assert [r.id for r in new_results] == [r.id for r in old_results]
        assert [r.title for r in new_results] == [r.title for r in old_results]
        assert [r.type for r in new_results] == [r.type for r in old_results]
        for new, old in zip(new_results, old_results):
            assert new.score == pytest.approx(old.score, abs=1e-6)
            assert isinstance(new.score, float)

    def test_ties_keep_row_order(self, tmp_project):
        """Duplicate vectors score identically; row order must break the tie."""
        vec = [1.0, 0.0, 0.0, 0.0]
        emb = _make_store(tmp_project, [vec] * 6, query_vector=vec)

        assert [r.id for r in emb.search("q", top_k=3)] == [
            "US-TST-1",
            "US-TST-2",
            "US-TST-3",
        ]

    def test_top_k_zero_and_negative_return_empty(self, tmp_project):
        vecs = _random_unit_vectors(5, 8, seed=7)
        emb = _make_store(tmp_project, [v.tolist() for v in vecs])

        assert emb.search("q", top_k=0) == []
        assert emb.search("q", top_k=-1) == []

    def test_top_k_larger_than_index_returns_all(self, tmp_project):
        vecs = _random_unit_vectors(4, 8, seed=11)
        emb = _make_store(tmp_project, [v.tolist() for v in vecs])

        assert len(emb.search("q", top_k=99)) == 4

    def test_scoring_makes_at_most_one_python_level_dot_call(
        self, tmp_project, monkeypatch
    ):
        """Cosine similarity must be one whole-index product, not one dot per row.

        Deterministic counterpart to the timing benchmark below (which is
        skippable via PROJECTMAN_SKIP_BENCH): spies on every python-level numpy
        dot entry point and asserts a 200-row search uses at most one of them.
        """
        import numpy as np

        vecs = _random_unit_vectors(200, 32, seed=20260822)
        query = _random_unit_vectors(1, 32, seed=99)[0]
        emb = _make_store(
            tmp_project, [v.tolist() for v in vecs], query_vector=query.tolist()
        )
        emb.search("warm", top_k=5)  # build the cache outside the counted window

        calls = {"n": 0}
        for name in ("dot", "matmul", "inner", "vdot", "tensordot"):
            real = getattr(np, name)

            def counting(*args, _real=real, **kwargs):
                calls["n"] += 1
                return _real(*args, **kwargs)

            monkeypatch.setattr(np, name, counting)

        results = emb.search("q", top_k=5)

        assert len(results) == 5
        assert calls["n"] <= 1, (
            f"200-row search made {calls['n']} python-level dot calls; cosine "
            "similarity must be one vectorised product, not a per-row loop"
        )


@_skip_no_numpy
@_skip_bench
@pytest.mark.benchmark
class TestVectorisedSearchBenchmark:
    def test_at_least_10x_faster_than_loop_for_1000_items(self, tmp_project):
        import numpy as np

        n, dim, top_k, reps = 1000, 384, 10, 15
        vecs = _random_unit_vectors(n, dim, seed=1234)
        query = _random_unit_vectors(1, dim, seed=4321)[0]
        emb = _make_store(
            tmp_project, [v.tolist() for v in vecs], query_vector=query.tolist()
        )

        # Warm the cached matrix so neither timing measures sqlite I/O or decoding.
        emb.search("warm", top_k=top_k)
        matrix, rows = emb._load_matrix()
        assert matrix.shape == (n, dim)
        query_vec = np.asarray(query, dtype=np.float32)

        def _time(fn):
            best = float("inf")
            for _ in range(reps):
                start = time.perf_counter()
                fn()
                best = min(best, time.perf_counter() - start)
            return best

        old_time = _time(lambda: _old_search(rows, matrix, query_vec, top_k))
        new_time = _time(lambda: emb.search("q", top_k=top_k))

        # Sanity: both formulations agree on the ranking being timed.
        assert [r.id for r in emb.search("q", top_k=top_k)] == [
            r.id for r in _old_search(rows, matrix, query_vec, top_k)
        ]

        speedup = old_time / new_time
        assert speedup >= 10.0, (
            f"expected >=10x speedup for {n} items, got {speedup:.1f}x "
            f"(old {old_time * 1e6:.1f}us vs new {new_time * 1e6:.1f}us)"
        )

    def test_at_least_10x_faster_than_pre_sprint_search_for_1000_items(self, tmp_project):
        """End-to-end: new search() vs a faithful copy of the pre-sprint search.

        Unlike the test above, the baseline here pays what the old code really
        paid per query -- a fresh sqlite connection, a SELECT of all 1000
        vector blobs, and a struct.unpack decode of each one -- so this is the
        honest measurement of the "10x+ improvement for 1000-item projects"
        criterion.
        """
        n, dim, top_k = 1000, 384, 10
        vecs = _random_unit_vectors(n, dim, seed=1234)
        query = _random_unit_vectors(1, dim, seed=4321)[0]
        emb = _make_store(
            tmp_project, [v.tolist() for v in vecs], query_vector=query.tolist()
        )
        emb.search("warm", top_k=top_k)  # cache build is a one-off, not per-query

        def _time(fn, reps):
            best = float("inf")
            for _ in range(reps):
                start = time.perf_counter()
                fn()
                best = min(best, time.perf_counter() - start)
            return best

        # Few reps for the slow baseline keeps the whole test well under 2s.
        old_time = _time(lambda: _pre_sprint_search(emb, "q", top_k), 3)
        new_time = _time(lambda: emb.search("q", top_k=top_k), 15)

        # Sanity: both formulations agree on the ranking being timed.
        assert [r.id for r in emb.search("q", top_k=top_k)] == [
            r.id for r in _pre_sprint_search(emb, "q", top_k)
        ]

        speedup = old_time / new_time
        assert speedup >= 10.0, (
            f"expected >=10x speedup for {n} items, got {speedup:.1f}x "
            f"(pre-sprint {old_time * 1e6:.1f}us vs new {new_time * 1e6:.1f}us)"
        )
