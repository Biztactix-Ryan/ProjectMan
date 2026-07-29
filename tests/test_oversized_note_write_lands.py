"""An oversized run-log note truncates; the status write still lands.

US-PM-1-4 — acceptance criteria 1 and 3 of US-PM-1:

1. "Oversized notes are truncated server-side with a visible marker rather
   than rejected"
3. "The status and outcome portion of the write always lands regardless of
   note length"

``tests/test_run_log_truncation.py`` pins the helper and ``Store.update``;
``tests/test_note_truncated_flag.py`` pins the response *flag*.  This module
covers what neither does, and what the criteria actually claim:

* the whole path a real caller uses — ``pm_update`` in, ``pm_run_log`` out —
  returns a normal, non-error response for a note of any size;
* the write is **durable**: re-read from disk through a brand new ``Store``
  (and again through raw frontmatter, bypassing ``Store`` entirely) the status,
  the outcome and the truncated note are all still there.  An assertion against
  the object ``update`` just returned proves nothing about the write landing;
* the marker is present, visible and arithmetically honest about what it drop-
  ped;
* every item type that takes a note — task, story and epic — behaves the same;
* a combined write (status + points + assignee + depends_on + tags) alongside
  an oversized note lands *every* field, not just status.

NOTE (port forward): ``pm_done_next`` does not exist in this checkout.  It is
the higher-traffic note-bearing entry point upstream; mirror this module
against it when these changes are ported onto a newer main.
"""

import re

import frontmatter
import pytest
import yaml

from projectman.store import RUN_LOG_NOTE_LIMIT

MARKER_RE = re.compile(r"\.\.\.\[truncated (\d+) chars\]$")

# Well over the limit in every direction a caller could plausibly land on.
OVERSIZED = RUN_LOG_NOTE_LIMIT * 4


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Run the real MCP tools against a throwaway project with a cold cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()
    yield
    _store_cache.clear()
    _cache.clear()


@pytest.fixture
def task():
    from projectman.server import pm_create_story, pm_create_task

    pm_create_story("Story", "Body")
    pm_create_task("US-TST-1", "Task one", "Do it")
    return "US-TST-1-1"


def ok(result: str) -> dict:
    """Parse a tool response, asserting it is not an error in any form.

    Criterion 3 is about the write landing *without looking like a failure*:
    the MCP layer signals failure by returning a string starting with
    ``error:`` (see ``pm_update``'s except arm), so a truncation that produced
    one would be indistinguishable from a rejection to a caller that only
    checks ``is_error``.
    """
    assert isinstance(result, str)
    assert not result.startswith("error:"), result
    assert "error" not in result.lower().split("\n")[0], result
    payload = yaml.safe_load(result)
    assert isinstance(payload, dict), result
    assert "error" not in payload, result
    return payload


def run_log(item_id: str) -> list[dict]:
    """Read the run log back through the MCP tool, most recent first."""
    import json

    from projectman.server import pm_run_log

    raw = pm_run_log(item_id)
    assert not raw.startswith("error:"), raw
    return json.loads(raw)


def assert_marked_truncation(stored: str, original: str) -> int:
    """Assert *stored* is *original*, clamped, with an honest marker.

    Returns the dropped-character count stated by the marker.
    """
    assert len(stored) <= RUN_LOG_NOTE_LIMIT, f"stored {len(stored)} chars"
    match = MARKER_RE.search(stored)
    assert match, f"no truncation marker: ...{stored[-80:]!r}"
    dropped = int(match.group(1))
    kept = stored[: -len(match.group(0))]
    # The marker is honest: kept content + dropped == what the caller sent.
    assert len(kept) + dropped == len(original)
    # And the kept part really is the head of the caller's note.
    assert kept == original[: len(kept)]
    assert dropped > 0
    return dropped


class TestEndToEndThroughTheToolLayer:
    """pm_update, the surface a real caller touches — not Store.update."""

    @pytest.fixture
    def sent(self, task):
        from projectman.server import pm_update

        note = "e2e " + ("x" * OVERSIZED)
        payload = ok(pm_update(task, status="done", outcome="success", note=note))
        return note, payload

    def test_response_is_not_an_error(self, sent):
        # ``ok`` already asserted it; keep the criterion visible as its own test.
        _, payload = sent
        assert "updated" in payload

    def test_item_reaches_the_new_status(self, sent):
        _, payload = sent
        assert payload["updated"]["status"] == "done"

    def test_the_run_log_entry_exists(self, sent, task):
        entries = run_log(task)
        assert len(entries) == 1

    def test_the_run_log_entry_carries_the_outcome_and_status(self, sent, task):
        entry = run_log(task)[0]
        assert entry["outcome"] == "success"
        assert entry["status"] == "done"

    def test_the_stored_note_is_truncated_with_a_visible_marker(self, sent, task):
        note, _ = sent
        stored = run_log(task)[0]["note"]
        assert_marked_truncation(stored, note)

    def test_the_marker_count_matches_the_reported_dropped_chars(self, sent, task):
        note, payload = sent
        stored = run_log(task)[0]["note"]
        dropped = assert_marked_truncation(stored, note)
        assert dropped == payload["note_dropped_chars"]
        assert payload["note_original_length"] == len(note)


class TestDurability:
    """The write must survive the process — re-read it from disk."""

    @pytest.fixture
    def written(self, task):
        from projectman.server import pm_update

        note = "durable " + ("d" * OVERSIZED)
        ok(pm_update(task, status="done", outcome="success", note=note))
        return note

    @pytest.fixture
    def cold_store(self, tmp_project):
        """A Store that has never seen this project, with every cache dropped."""
        from projectman.server import _store_cache
        from projectman.store import Store, _cache, _cache_mtimes

        _store_cache.clear()
        _cache.clear()
        _cache_mtimes.clear()
        return Store(tmp_project)

    def test_status_persisted(self, written, cold_store, task):
        meta, _ = cold_store.get_task(task)
        assert meta.status.value == "done"

    def test_status_persisted_in_the_raw_file(self, written, tmp_project, task):
        """Bypass Store entirely — the bug was the file never being written."""
        post = frontmatter.load(str(tmp_project / ".project" / "tasks" / f"{task}.md"))
        assert post.metadata["status"] == "done"

    def test_outcome_persisted(self, written, cold_store, task):
        entries = cold_store.get_run_log(task)
        assert len(entries) == 1
        assert entries[0].outcome.value == "success"
        assert entries[0].status == "done"

    def test_truncated_note_persisted(self, written, cold_store, task):
        stored = cold_store.get_run_log(task)[0].note
        assert_marked_truncation(stored, written)

    def test_no_untruncated_note_reached_the_disk(self, written, tmp_project, task):
        """Nothing anywhere on disk holds the full oversized note."""
        raw = (tmp_project / ".project" / "logs" / f"{task}.jsonl").read_text()
        assert "d" * (RUN_LOG_NOTE_LIMIT + 1) not in raw


class TestExtremeLengths:
    """Criterion 3 says "regardless of note length" — so test the extremes."""

    @pytest.mark.parametrize("size", [RUN_LOG_NOTE_LIMIT + 1, 40_000, 100_000])
    def test_status_write_lands_for_any_note_length(self, task, size):
        from projectman.server import pm_update

        note = "n" * size
        payload = ok(pm_update(task, status="done", outcome="success", note=note))

        assert payload["updated"]["status"] == "done"
        entry = run_log(task)[0]
        assert entry["outcome"] == "success"
        assert entry["status"] == "done"
        assert_marked_truncation(entry["note"], note)

    def test_note_exactly_at_the_limit_is_stored_untouched(self, task):
        from projectman.server import pm_update

        note = "b" * RUN_LOG_NOTE_LIMIT
        payload = ok(pm_update(task, status="done", outcome="success", note=note))

        assert payload["updated"]["status"] == "done"
        stored = run_log(task)[0]["note"]
        assert stored == note
        assert MARKER_RE.search(stored) is None
        assert "truncated" not in stored

    def test_a_hundred_thousand_char_note_costs_only_the_note(self, task):
        """The surplus is dropped; nothing else about the write is affected."""
        from projectman.server import pm_update

        payload = ok(
            pm_update(task, status="review", points=3, outcome="partial", note="q" * 100_000)
        )
        assert payload["updated"]["status"] == "review"
        assert payload["updated"]["points"] == 3


class TestEveryItemTypeThatTakesANote:
    """Tasks, stories and epics all route through the same Store.update."""

    @pytest.fixture
    def items(self):
        from projectman.server import pm_create_epic, pm_create_story, pm_create_task

        ok(pm_create_epic("Epic", "Vision"))
        ok(pm_create_story("Story", "Body"))
        ok(pm_create_task("US-TST-1", "Task one", "Do it"))
        return {
            "task": ("US-TST-1-1", "done"),
            "story": ("US-TST-1", "active"),
            "epic": ("EPIC-TST-1", "active"),
        }

    @pytest.mark.parametrize("kind", ["task", "story", "epic"])
    def test_oversized_note_never_costs_the_status_write(self, items, kind):
        from projectman.server import pm_update

        item_id, target = items[kind]
        note = f"{kind}: " + ("m" * OVERSIZED)

        payload = ok(pm_update(item_id, status=target, outcome="success", note=note))

        assert payload["updated"]["status"] == target
        assert payload["note_truncated"] is True

        entries = run_log(item_id)
        assert len(entries) == 1, f"no run-log entry for {kind}"
        assert entries[0]["outcome"] == "success"
        assert entries[0]["status"] == target
        assert_marked_truncation(entries[0]["note"], note)


class TestCombinedWriteLandsEveryField:
    """Not just status — the whole update has to survive the oversized note."""

    @pytest.fixture
    def two_tasks(self):
        from projectman.server import pm_create_story, pm_create_task

        pm_create_story("Story", "Body")
        pm_create_task("US-TST-1", "Task one", "Do it")
        pm_create_task("US-TST-1", "Task two", "Do it too")
        return "US-TST-1-1", "US-TST-1-2"

    @pytest.fixture
    def written(self, two_tasks):
        from projectman.server import pm_update

        first, second = two_tasks
        note = "combined " + ("c" * OVERSIZED)
        payload = ok(
            pm_update(
                second,
                status="review",
                points=5,
                assignee="claude",
                depends_on=first,
                tags="backend,mvp",
                outcome="partial",
                note=note,
            )
        )
        return second, first, note, payload

    def test_every_field_is_in_the_response(self, written):
        second, first, _, payload = written
        updated = payload["updated"]
        assert updated["status"] == "review"
        assert updated["points"] == 5
        assert updated["assignee"] == "claude"
        assert updated["depends_on"] == [first]
        assert updated["tags"] == ["backend", "mvp"]

    def test_every_field_survives_a_cold_re_read(self, written, tmp_project):
        from projectman.server import _store_cache
        from projectman.store import Store, _cache, _cache_mtimes

        second, first, _, _ = written
        _store_cache.clear()
        _cache.clear()
        _cache_mtimes.clear()

        meta, _body = Store(tmp_project).get_task(second)
        assert meta.status.value == "review"
        assert meta.points == 5
        assert meta.assignee == "claude"
        assert meta.depends_on == [first]
        assert meta.tags == ["backend", "mvp"]

    def test_the_run_log_entry_landed_too(self, written):
        second, _, note, _ = written
        entry = run_log(second)[0]
        assert entry["outcome"] == "partial"
        assert entry["status"] == "review"
        assert_marked_truncation(entry["note"], note)
