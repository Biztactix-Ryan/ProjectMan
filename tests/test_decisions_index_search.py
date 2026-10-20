"""Decisions in the index, in search and in ``pm_get`` (US-PM-63-8).

Story US-PM-63, criterion 3: "pm_get, pm_search and the index include
decisions, and INDEX.md lists open decisions".

Every test runs against a tmp_path-isolated store; nothing here touches the
real ``.project``.
"""

import hashlib
import math

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.indexer import build_index, index_is_stale, write_index
from projectman.search import keyword_search, keyword_search_with_skipped


def _decisions(store):
    """Three decisions: one open, one answered, one withdrawn."""
    store.create_story("A story", "A description long enough to pass")
    store.create_decision(
        "Which queue backend?",
        "We need a queue. Redis is already deployed on the cluster.",
        priority="must",
        blocks=["US-TST-1"],
        options=[{"label": "redis"}, {"label": "sqs"}],
        recommendation="redis",
    )
    store.create_decision("Ship on Fridays?", "The release train question.")
    store.update_decision("DEC-TST-2", status="answered", answer="no")
    store.create_decision("Rename the CLI?", "Bikeshed about the binary name.")
    store.update_decision("DEC-TST-3", status="withdrawn")


def _write_malformed(store):
    store.decisions_dir.mkdir(parents=True, exist_ok=True)
    path = store.decisions_dir / "DEC-TST-9.md"
    path.write_text("---\nid: DEC-TST-9\ntitle: [unclosed\n---\nbroken body\n")
    return path


# ─── Index rows ──────────────────────────────────────────────────


class TestIndexEntries:
    def test_index_rows_include_decisions(self, store):
        _decisions(store)
        index = build_index(store)
        rows = {e.id: e for e in index.entries if e.type == "decision"}
        assert set(rows) == {"DEC-TST-1", "DEC-TST-2", "DEC-TST-3"}
        assert rows["DEC-TST-1"].title == "Which queue backend?"
        assert rows["DEC-TST-1"].status == "open"
        assert rows["DEC-TST-2"].status == "answered"
        assert rows["DEC-TST-3"].status == "withdrawn"
        assert index.decision_count == 3

    def test_decisions_do_not_move_points(self, store):
        store.create_story("A story", "A description long enough to pass", points=3)
        before = build_index(store)
        store.create_decision("Q?", "ctx")
        after = build_index(store)
        assert (after.total_points, after.completed_points) == (
            before.total_points,
            before.completed_points,
        )
        assert after.story_count == before.story_count

    def test_index_yaml_carries_decision_rows(self, store):
        _decisions(store)
        write_index(store)
        data = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        ids = [e["id"] for e in data["entries"] if e["type"] == "decision"]
        assert ids == ["DEC-TST-1", "DEC-TST-2", "DEC-TST-3"]
        assert data["decision_count"] == 3

    def test_decision_rows_ordered_by_number(self, store):
        store.decisions_dir.mkdir(parents=True, exist_ok=True)
        for n in (10, 2, 1):
            store.create_decision(f"Question {n}?", "ctx")
        # Allocation is sequential; rename to force a 1/2/10 spread.
        (store.decisions_dir / "DEC-TST-3.md").rename(
            store.decisions_dir / "DEC-TST-10.md"
        )
        text = (store.decisions_dir / "DEC-TST-10.md").read_text()
        (store.decisions_dir / "DEC-TST-10.md").write_text(
            text.replace("id: DEC-TST-3", "id: DEC-TST-10")
        )
        ids = [e.id for e in build_index(store).entries if e.type == "decision"]
        assert ids == ["DEC-TST-1", "DEC-TST-2", "DEC-TST-10"]

    def test_malformed_decision_does_not_break_index(self, store):
        _decisions(store)
        _write_malformed(store)
        index = build_index(store)
        ids = {e.id for e in index.entries if e.type == "decision"}
        assert ids == {"DEC-TST-1", "DEC-TST-2", "DEC-TST-3"}
        write_index(store)  # must not raise
        assert "DEC-TST-9" not in (store.project_dir / "INDEX.md").read_text()

    def test_new_decision_makes_index_stale(self, store):
        import os

        store.create_story("A story", "A description long enough to pass")
        write_index(store)
        index_mtime = (store.project_dir / "index.yaml").stat().st_mtime_ns
        store.create_decision("Q?", "ctx")
        path = store.decisions_dir / "DEC-TST-1.md"
        os.utime(path, ns=(index_mtime + 10**9, index_mtime + 10**9))
        assert index_is_stale(store)


# ─── INDEX.md ────────────────────────────────────────────────────


class TestIndexMarkdown:
    def _section(self, store) -> str:
        text = (store.project_dir / "INDEX.md").read_text()
        assert "## Open decisions" in text
        return text.split("## Open decisions", 1)[1]

    def test_lists_only_open_decisions(self, store):
        _decisions(store)
        write_index(store)
        section = self._section(store)
        assert "[DEC-TST-1](decisions/DEC-TST-1.md)" in section
        assert "Which queue backend?" in section
        assert "must" in section
        assert "US-TST-1" in section
        assert "DEC-TST-2" not in section
        assert "DEC-TST-3" not in section
        assert "Ship on Fridays?" not in section
        assert "Rename the CLI?" not in section

    def test_counts_decisions(self, store):
        _decisions(store)
        write_index(store)
        assert "| Decisions | 3 |" in (store.project_dir / "INDEX.md").read_text()

    def test_empty_safe_without_decisions(self, store):
        store.create_story("A story", "A description long enough to pass")
        write_index(store)
        text = (store.project_dir / "INDEX.md").read_text()
        assert "| Decisions | 0 |" in text
        assert "_No open decisions._" in self._section(store)

    def test_empty_safe_on_a_bare_store(self, store):
        write_index(store)
        assert "_No open decisions._" in self._section(store)

    def test_no_open_decisions_when_all_closed(self, store):
        _decisions(store)
        store.update_decision("DEC-TST-1", status="withdrawn")
        write_index(store)
        assert "_No open decisions._" in self._section(store)

    def test_stable_across_rebuilds(self, store):
        _decisions(store)
        write_index(store)
        first = (store.project_dir / "INDEX.md").read_text()
        write_index(store)
        assert (store.project_dir / "INDEX.md").read_text() == first

    def test_pipe_in_question_does_not_break_the_table(self, store):
        store.create_decision("Use A | B?", "ctx")
        write_index(store)
        row = [l for l in self._section(store).splitlines() if "DEC-TST-1" in l][0]
        assert "Use A \\| B?" in row
        assert row.count(" | ") == 3


# ─── Keyword search ──────────────────────────────────────────────


class TestKeywordSearch:
    def test_finds_decision_by_question(self, store):
        _decisions(store)
        hits = keyword_search("queue backend", store.project_dir)
        assert [(h.id, h.type) for h in hits] == [("DEC-TST-1", "decision")]
        assert hits[0].score == 1.0

    def test_finds_decision_by_context(self, store):
        _decisions(store)
        hits = keyword_search("already deployed on the cluster", store.project_dir)
        assert [(h.id, h.type) for h in hits] == [("DEC-TST-1", "decision")]
        assert hits[0].score == 0.5

    def test_closed_decisions_are_still_searchable(self, store):
        _decisions(store)
        hits = keyword_search("release train", store.project_dir)
        assert [h.id for h in hits] == ["DEC-TST-2"]

    def test_malformed_decision_is_skipped_not_fatal(self, store):
        _decisions(store)
        _write_malformed(store)
        outcome = keyword_search_with_skipped("queue backend", store.project_dir)
        assert [h.id for h in outcome.results] == ["DEC-TST-1"]
        assert outcome.skipped == 1


# ─── Embeddings ──────────────────────────────────────────────────


class _FakeModel:
    """Deterministic bag-of-words embedder: no fastembed, no network."""

    DIM = 64

    def embed(self, texts):
        for text in texts:
            vec = [0.0] * self.DIM
            for word in text.lower().replace("?", " ").replace(".", " ").split():
                h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            yield [v / norm for v in vec]


class TestEmbeddings:
    def test_reindex_all_indexes_decisions(self, store):
        pytest.importorskip("numpy")
        import sqlite3

        from projectman.embeddings import EmbeddingStore

        _decisions(store)
        _write_malformed(store)
        emb = EmbeddingStore(store.project_dir)
        emb._model = _FakeModel()
        emb.reindex_all(store)

        conn = sqlite3.connect(str(emb.db_path))
        rows = dict(
            conn.execute("SELECT id, type FROM embeddings WHERE type = 'decision'")
        )
        conn.close()
        assert rows == {
            "DEC-TST-1": "decision",
            "DEC-TST-2": "decision",
            "DEC-TST-3": "decision",
        }

        hits = emb.search("redis already deployed cluster queue", top_k=1)
        assert hits[0].id == "DEC-TST-1"
        assert hits[0].type == "decision"
        emb.close()

    def test_create_decision_indexes_embedding(self, store):
        from unittest.mock import patch

        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.create_decision("Which queue?", "Redis is deployed.")
        mock_index.assert_called_once_with(
            "DEC-TST-1", "Which queue?", "decision", "Redis is deployed."
        )

    def test_update_decision_reindexes_on_text_change_only(self, store):
        from unittest.mock import patch

        store.create_decision("Which queue?", "Redis is deployed.")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.update_decision("DEC-TST-1", priority="must")
            mock_index.assert_not_called()
            store.update_decision("DEC-TST-1", body="New context.")
            mock_index.assert_called_once_with(
                "DEC-TST-1", "Which queue?", "decision", "New context."
            )

    def test_index_embedding_accepts_decisions(self, store, monkeypatch):
        import sys
        import types

        calls = []

        class _Recorder:
            def __init__(self, project_dir):
                pass

            def index_item(self, *args):
                calls.append(args)

        fake = types.ModuleType("projectman.embeddings")
        fake.EmbeddingStore = _Recorder
        monkeypatch.setitem(sys.modules, "projectman.embeddings", fake)
        store._index_embedding("DEC-TST-1", "Q?", "decision", "ctx")
        assert calls == [("DEC-TST-1", "Q?", "decision", "ctx")]


# ─── pm_get / pm_search tools ────────────────────────────────────


@pytest.fixture
def server_store(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()
    store = Store(tmp_project)
    _decisions(store)
    yield store
    clear_all_caches()
    _store_cache.clear()


class TestTools:
    def test_pm_get_returns_frontmatter_and_body(self, server_store):
        from projectman.server import pm_get

        data = yaml.safe_load(pm_get("DEC-TST-1"))
        assert data["id"] == "DEC-TST-1"
        assert data["title"] == "Which queue backend?"
        assert data["status"] == "open"
        assert data["priority"] == "must"
        assert data["blocks"] == ["US-TST-1"]
        assert data["recommendation"] == "redis"
        assert [o["label"] for o in data["options"]] == ["redis", "sqs"]
        assert "Redis is already deployed" in data["body"]

    def test_pm_get_respects_fields(self, server_store):
        from projectman.server import pm_get

        data = yaml.safe_load(pm_get("DEC-TST-2", fields="status,answer"))
        assert data == {"id": "DEC-TST-2", "status": "answered", "answer": "no"}

    def test_pm_get_unknown_field_names_decision_keys(self, server_store):
        from projectman.server import pm_get

        with pytest.raises(ToolError) as exc:
            pm_get("DEC-TST-1", fields="acceptance_criteria")
        assert "recommendation" in str(exc.value)

    def test_pm_get_mixed_ids(self, server_store):
        from projectman.server import pm_get

        items = yaml.safe_load(pm_get("US-TST-1,DEC-TST-1,DEC-TST-404", fields="title"))
        assert items[0] == {"id": "US-TST-1", "title": "A story"}
        assert items[1] == {"id": "DEC-TST-1", "title": "Which queue backend?"}
        assert items[2]["id"] == "DEC-TST-404"
        assert "error" in items[2]

    def test_pm_get_missing_decision_is_not_found(self, server_store):
        from projectman.server import pm_get

        with pytest.raises(ToolError) as exc:
            pm_get("DEC-TST-404")
        assert "not found" in str(exc.value).lower()

    def test_pm_search_finds_decision(self, server_store):
        from projectman.server import pm_search

        data = yaml.safe_load(pm_search("queue backend"))
        assert [(r["id"], r["type"]) for r in data["results"]] == [
            ("DEC-TST-1", "decision")
        ]

    def test_pm_search_survives_malformed_decision(self, server_store):
        from projectman.server import pm_search

        _write_malformed(server_store)
        data = yaml.safe_load(pm_search("cluster"))
        assert [r["id"] for r in data["results"]] == ["DEC-TST-1"]
        assert data["skipped"] == 1
