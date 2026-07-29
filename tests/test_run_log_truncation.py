"""Run-log notes are truncated server-side, never rejected.

The bug this covers: ``store.update`` used to raise on a note over 1024
characters, and it raised *after* ``status`` had been staged — so "mark this
task done, here is my note" failed as a single unit and a caller that only
checks ``is_error`` silently dropped the completion.  Truncation must never
cost the caller the status/outcome write.
"""

import re

import pytest

from projectman.store import RUN_LOG_NOTE_LIMIT, truncate_run_log_note

MARKER_RE = re.compile(r"\.\.\.\[truncated (\d+) chars\]$")


@pytest.fixture
def task(store):
    """A story with one task, ready to be updated."""
    store.create_story("Story", "Body")
    store.create_task("US-TST-1", "Task one", "Do it")
    return "US-TST-1-1"


class TestTruncateHelper:
    """Pure-function behaviour of the truncation helper."""

    def test_none_passes_through(self):
        assert truncate_run_log_note(None) == (None, False, 0)

    def test_empty_passes_through(self):
        assert truncate_run_log_note("") == ("", False, 0)

    def test_short_note_untouched(self):
        assert truncate_run_log_note("hello") == ("hello", False, 0)

    def test_exactly_at_limit_untouched(self):
        note = "x" * RUN_LOG_NOTE_LIMIT
        out, truncated, dropped = truncate_run_log_note(note)
        assert out == note
        assert truncated is False
        assert dropped == 0

    def test_one_over_limit_truncates(self):
        note = "x" * (RUN_LOG_NOTE_LIMIT + 1)
        out, truncated, dropped = truncate_run_log_note(note)
        assert truncated is True
        assert len(out) <= RUN_LOG_NOTE_LIMIT
        assert MARKER_RE.search(out)

    def test_marker_states_the_true_dropped_count(self):
        note = "x" * (RUN_LOG_NOTE_LIMIT * 3)
        out, truncated, dropped = truncate_run_log_note(note)
        match = MARKER_RE.search(out)
        assert match, f"no marker in {out[-60:]!r}"
        # The number in the marker is the real count of dropped characters.
        assert int(match.group(1)) == dropped
        assert len(out) - len(match.group(0)) + dropped == len(note)

    @pytest.mark.parametrize(
        "extra", [1, 2, 9, 10, 11, 99, 100, 101, 999, 1000, 1001, 12345, 999_999]
    )
    def test_stored_length_never_exceeds_cap(self, extra):
        """Total stored length (content + marker) must respect the cap.

        The digit count of N feeds back into the marker length, so lengths
        that straddle a power of ten are where a naive implementation
        overflows the cap by one character.
        """
        note = "x" * (RUN_LOG_NOTE_LIMIT + extra)
        out, truncated, dropped = truncate_run_log_note(note)
        assert truncated is True
        assert len(out) <= RUN_LOG_NOTE_LIMIT
        match = MARKER_RE.search(out)
        assert int(match.group(1)) == dropped == len(note) - (len(out) - len(match.group(0)))

    def test_kept_prefix_is_the_head_of_the_original(self):
        note = "BEGIN-" + ("y" * (RUN_LOG_NOTE_LIMIT + 500))
        out, _, _ = truncate_run_log_note(note)
        assert out.startswith("BEGIN-")

    def test_tiny_cap_falls_back_to_hard_cut(self):
        out, truncated, dropped = truncate_run_log_note("abcdefghij", limit=4)
        assert out == "abcd"
        assert truncated is True
        assert dropped == 6

    def test_zero_cap(self):
        assert truncate_run_log_note("abc", limit=0) == ("", True, 3)


class TestUpdateTruncatesNotes:
    def test_note_at_the_cap_is_stored_whole(self, store, task):
        note = "x" * RUN_LOG_NOTE_LIMIT
        store.update(task, outcome="info", note=note)

        entries = store.get_run_log(task)
        assert len(entries) == 1
        assert entries[0].note == note
        assert store.last_note_truncation["truncated"] is False

    def test_note_just_over_the_cap_is_truncated(self, store, task):
        note = "x" * (RUN_LOG_NOTE_LIMIT + 1)
        store.update(task, outcome="info", note=note)

        stored = store.get_run_log(task)[0].note
        assert len(stored) <= RUN_LOG_NOTE_LIMIT
        assert MARKER_RE.search(stored)

    def test_note_well_over_the_cap_is_truncated_with_marker(self, store, task):
        note = "z" * 50_000
        store.update(task, outcome="info", note=note)

        stored = store.get_run_log(task)[0].note
        assert len(stored) <= RUN_LOG_NOTE_LIMIT
        match = MARKER_RE.search(stored)
        assert match, "truncation marker missing"
        assert int(match.group(1)) == 50_000 - (len(stored) - len(match.group(0)))

    def test_oversized_note_does_not_raise(self, store, task):
        # The old behaviour. Guard against any regression to raising.
        store.update(task, outcome="info", note="q" * 100_000)

    def test_none_note_writes_no_note(self, store, task):
        store.update(task, status="in-progress")
        assert store.get_run_log(task) == []
        assert store.last_note_truncation is None

    def test_empty_note_is_stored_as_empty(self, store, task):
        store.update(task, outcome="info", note="")

        entries = store.get_run_log(task)
        assert len(entries) == 1
        assert entries[0].note == ""
        assert store.last_note_truncation["truncated"] is False

    def test_truncation_fact_is_available_internally(self, store, task):
        """US-PM-1-3 surfaces this to the caller; it must exist by then."""
        note = "x" * (RUN_LOG_NOTE_LIMIT + 2000)
        store.update(task, outcome="info", note=note)

        record = store.last_note_truncation
        assert record["truncated"] is True
        assert record["original_length"] == len(note)
        assert record["limit"] == RUN_LOG_NOTE_LIMIT
        assert record["stored_length"] <= RUN_LOG_NOTE_LIMIT
        assert record["dropped_chars"] > 0

    def test_truncation_record_resets_between_calls(self, store, task):
        store.update(task, outcome="info", note="x" * (RUN_LOG_NOTE_LIMIT + 10))
        assert store.last_note_truncation["truncated"] is True

        store.update(task, outcome="info", note="short")
        assert store.last_note_truncation["truncated"] is False


class TestAtomicity:
    """The actual bug: an oversized note must not take the status write with it."""

    def test_oversized_note_still_lands_the_status_change(self, store, task):
        meta = store.update(task, status="done", outcome="success", note="x" * 40_000)

        assert meta.status.value == "done"
        # And it is durable, not just in the returned object.
        reloaded, _ = store.get_task(task)
        assert reloaded.status.value == "done"

    def test_oversized_note_still_lands_the_outcome(self, store, task):
        store.update(task, status="done", outcome="success", note="y" * 40_000)

        entries = store.get_run_log(task)
        assert len(entries) == 1
        assert entries[0].outcome.value == "success"
        assert entries[0].status == "done"

    def test_oversized_note_still_lands_other_fields(self, store, task):
        store.update(
            task,
            status="review",
            points=5,
            assignee="claude",
            outcome="partial",
            note="w" * 20_000,
        )

        reloaded, _ = store.get_task(task)
        assert reloaded.status.value == "review"
        assert reloaded.points == 5
        assert reloaded.assignee == "claude"

    def test_a_note_alone_never_blocks_a_completion(self, store, task):
        """Simulates the non-interactive caller that checks is_error and moves on.

        Before the fix this raised, the file was never written, and the task
        stayed 'todo' while the caller believed it had reported completion.
        """
        raised = None
        try:
            store.update(task, status="done", outcome="success", note="d" * 9_999)
        except Exception as exc:  # pragma: no cover - only on regression
            raised = exc

        assert raised is None, f"update raised {raised!r}"
        reloaded, _ = store.get_task(task)
        assert reloaded.status.value == "done"
