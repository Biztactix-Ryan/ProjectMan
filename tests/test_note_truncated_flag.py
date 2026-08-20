"""Note-writing tools tell the caller, structurally, that a note was truncated.

US-PM-1-3.  Truncation is silent from the caller's point of view unless the
response says so, and an automated caller must not have to string-match the
note body to find out.  The contract under test:

* the ``updated`` payload is always present and unchanged;
* ``note_truncated: true`` plus the length fields appear *only* when a supplied
  note actually had to be truncated (absence means "stored whole") — normal
  responses stay small, because response bytes are a tracked cost for this epic;
* the flag can never be inherited from an earlier call.  ``Store`` instances are
  cached for the life of the process and ``Store.last_note_truncation`` is
  mutable per-instance state, so a later note-less update reporting a previous
  update's truncation is a real, reachable bug.

The rule is uniform across every tool that writes a run-log note — ``pm_update``,
``pm_release`` and ``pm_done_next`` — so ``TestDoneNext`` and ``TestRelease``
mirror the contract against the other two entry points.  ``pm_done_next`` is the
higher-traffic one and the riskiest: it keeps updating the Store *after* the
note is written (closing the parent story, claiming the next task), and each of
those updates resets the per-Store truncation record, so the record has to be
consumed immediately or the flag is silently lost.
"""

import re

import pytest
import yaml

from projectman.store import RUN_LOG_NOTE_LIMIT

MARKER_RE = re.compile(r"\.\.\.\[truncated (\d+) chars\]$")

TRUNCATION_KEYS = {
    "note_truncated",
    "note_original_length",
    "note_stored_length",
    "note_dropped_chars",
    "note_limit",
}


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Run server tools against a throwaway project with a cold store cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()


@pytest.fixture
def task():
    """A story with one task, ready to be updated."""
    from projectman.server import pm_create_story, pm_create_task

    pm_create_story("Story", "Body")
    pm_create_task("US-TST-1", "Task one", "Do it")
    return "US-TST-1-1"


def parse(result: str) -> dict:
    """Parse a pm_update response, failing loudly on an error string."""
    assert not result.startswith("error:"), result
    return yaml.safe_load(result)


class TestNoteFits:
    """A note that fits must not add anything to the response."""

    def test_short_note_reports_nothing(self, task):
        from projectman.server import pm_update

        payload = parse(pm_update(task, outcome="success", note="all done"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_note_exactly_at_limit_reports_nothing(self, task):
        from projectman.server import pm_update

        note = "x" * RUN_LOG_NOTE_LIMIT
        payload = parse(pm_update(task, outcome="success", note=note))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_one_over_limit_does_report(self, task):
        """The boundary is exclusive — limit+1 is the first truncating length."""
        from projectman.server import pm_update

        note = "x" * (RUN_LOG_NOTE_LIMIT + 1)
        payload = parse(pm_update(task, outcome="success", note=note))
        assert payload["note_truncated"] is True

    def test_updated_payload_still_present(self, task):
        from projectman.server import pm_update

        payload = parse(pm_update(task, status="done", outcome="success", note="ok"))
        assert payload["updated"]["status"] == "done"


class TestNoNote:
    """No note supplied means no truncation reporting, ever."""

    def test_status_only_update_reports_nothing(self, task):
        from projectman.server import pm_update

        payload = parse(pm_update(task, status="in-progress"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_field_only_update_reports_nothing(self, task):
        from projectman.server import pm_update

        payload = parse(pm_update(task, points=3))
        assert TRUNCATION_KEYS.isdisjoint(payload)


class TestNoteTruncated:
    """An oversized note reports the flag and the true lengths."""

    @pytest.fixture
    def oversized(self, task):
        from projectman.server import pm_update

        self_note = "y" * (RUN_LOG_NOTE_LIMIT + 500)
        result = pm_update(task, status="done", outcome="success", note=self_note)
        return self_note, parse(result)

    def test_flag_is_true(self, oversized):
        _, payload = oversized
        assert payload["note_truncated"] is True

    def test_flag_is_a_real_boolean_not_prose(self, oversized):
        _, payload = oversized
        assert isinstance(payload["note_truncated"], bool)

    def test_original_length_is_the_length_the_caller_sent(self, oversized):
        note, payload = oversized
        assert payload["note_original_length"] == len(note)
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 500

    def test_stored_length_is_within_the_limit(self, oversized):
        _, payload = oversized
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT

    def test_dropped_chars_accounts_for_every_lost_character(self, oversized, task):
        """``dropped_chars`` counts original characters lost, not marker bytes.

        The stored note is ``<kept prefix>...[truncated N chars]``, so the marker
        is part of ``stored_length`` but was never part of the caller's note.
        The invariant is on the *content*: kept + dropped == original.
        """
        from projectman.server import pm_run_log

        note, payload = oversized
        log = yaml.safe_load(pm_run_log(task))
        entries = log["run_log"] if isinstance(log, dict) else log
        stored = entries[-1]["note"]

        marker = MARKER_RE.search(stored)
        assert marker, stored
        assert int(marker.group(1)) == payload["note_dropped_chars"]

        kept = stored[: -len(marker.group(0))]
        assert kept == note[: len(kept)]
        assert len(kept) + payload["note_dropped_chars"] == payload[
            "note_original_length"
        ]

    def test_limit_is_reported(self, oversized):
        _, payload = oversized
        assert payload["note_limit"] == RUN_LOG_NOTE_LIMIT

    def test_status_write_still_landed(self, oversized):
        """The whole point: truncation never costs the caller the status write."""
        _, payload = oversized
        assert payload["updated"]["status"] == "done"

    def test_reported_stored_length_matches_the_persisted_note(self, oversized, task):
        from projectman.server import pm_run_log

        _, payload = oversized
        log = yaml.safe_load(pm_run_log(task))
        entries = log["run_log"] if isinstance(log, dict) else log
        stored = entries[-1]["note"]
        assert len(stored) == payload["note_stored_length"]


class TestStaleness:
    """``last_note_truncation`` must never leak from one call into the next.

    It lives on the Store, and ``_store_cache`` hands the *same* Store back to
    every call in the process, so without an explicit guard the second call
    below would happily re-report the first call's truncation.
    """

    @pytest.fixture
    def after_truncation(self, task):
        """Perform one truncating update, and assert it did truncate."""
        from projectman.server import pm_update

        note = "z" * (RUN_LOG_NOTE_LIMIT + 42)
        payload = parse(pm_update(task, outcome="success", note=note))
        assert payload["note_truncated"] is True
        return task

    def test_later_update_with_no_note_is_clean(self, after_truncation):
        from projectman.server import pm_update

        payload = parse(pm_update(after_truncation, status="review"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_later_update_with_a_short_note_is_clean(self, after_truncation):
        from projectman.server import pm_update

        payload = parse(pm_update(after_truncation, outcome="success", note="brief"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_later_update_on_a_different_item_is_clean(self, after_truncation):
        from projectman.server import pm_update

        payload = parse(pm_update("US-TST-1", status="active"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_same_store_instance_is_reused_across_calls(self, after_truncation):
        """Guards the premise: if this stops holding the staleness risk changes."""
        from projectman.server import _store

        assert _store() is _store()

    def test_record_is_consumed_from_the_store(self, after_truncation):
        """The record is cleared on read, so nothing downstream can re-read it."""
        from projectman.server import _store

        assert _store().last_note_truncation is None

    def test_helper_ignores_a_stale_record_when_no_note_was_sent(self, task):
        """Direct guard test: the record is only read when *this* call sent a note.

        ``Store.update`` happens to reset the record on entry, so the end-to-end
        tests above pass either way; this pins the guard itself, which is what
        holds if any path ever leaves a record behind without reaching that reset.
        """
        from projectman.server import _note_truncation_fields, _store

        store = _store()
        store.last_note_truncation = {
            "truncated": True,
            "original_length": 9999,
            "stored_length": RUN_LOG_NOTE_LIMIT,
            "dropped_chars": 9999 - RUN_LOG_NOTE_LIMIT,
            "limit": RUN_LOG_NOTE_LIMIT,
        }
        assert _note_truncation_fields(store, None) == {}

    def test_helper_consumes_the_record_so_it_reports_once(self, task):
        from projectman.server import _note_truncation_fields, _store

        store = _store()
        store.last_note_truncation = {
            "truncated": True,
            "original_length": 5000,
            "stored_length": RUN_LOG_NOTE_LIMIT,
            "dropped_chars": 5000 - RUN_LOG_NOTE_LIMIT,
            "limit": RUN_LOG_NOTE_LIMIT,
        }
        first = _note_truncation_fields(store, "a note")
        assert first["note_truncated"] is True
        assert first["note_original_length"] == 5000
        assert _note_truncation_fields(store, "a note") == {}

    def test_repeated_truncations_report_their_own_lengths(self, task):
        from projectman.server import pm_update

        first = parse(
            pm_update(task, outcome="success", note="a" * (RUN_LOG_NOTE_LIMIT + 10))
        )
        second = parse(
            pm_update(task, outcome="success", note="b" * (RUN_LOG_NOTE_LIMIT + 900))
        )
        assert first["note_original_length"] == RUN_LOG_NOTE_LIMIT + 10
        assert second["note_original_length"] == RUN_LOG_NOTE_LIMIT + 900


READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture
def two_tasks():
    """An active story with two ready tasks, so ``pm_done_next`` has a next."""
    from projectman.server import pm_create_story, pm_create_task, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "Task one", READY_BODY, points=1)
    pm_create_task("US-TST-1", "Task two", READY_BODY, points=1)
    return "US-TST-1-1", "US-TST-1-2"


class TestDoneNext:
    """``pm_done_next`` reports truncation on the same terms as ``pm_update``.

    It is the higher-traffic note-bearing entry point, and the one where the
    record is easiest to lose: the completion write is followed by more Store
    updates (story close, next-task claim) that each reset it.
    """

    @pytest.fixture
    def truncated(self, two_tasks):
        from projectman.server import pm_done_next

        first, _ = two_tasks
        note = "d" * (RUN_LOG_NOTE_LIMIT + 700)
        return note, parse(pm_done_next(first, note=note))

    def test_flag_is_true(self, truncated):
        _, payload = truncated
        assert payload["note_truncated"] is True

    def test_every_field_is_reported(self, truncated):
        note, payload = truncated
        assert TRUNCATION_KEYS <= set(payload), sorted(TRUNCATION_KEYS - set(payload))
        assert payload["note_original_length"] == len(note)
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT
        assert payload["note_limit"] == RUN_LOG_NOTE_LIMIT

    def test_completion_still_landed(self, truncated):
        """The whole point: truncation never costs the caller the completion."""
        _, payload = truncated
        assert payload["completed"]["status"] == "done"

    def test_flag_survives_the_next_task_claim(self, truncated, two_tasks):
        """The claim runs more Store updates after the note was written.

        Reading the record late — after the grab — would return the grab's own
        empty record instead, and the flag would vanish on exactly the busiest
        path.  This pins that the reported truncation belongs to *this* note.
        """
        _, payload = truncated
        assert payload["next"]["task"]["id"] == two_tasks[1]
        assert payload["note_truncated"] is True

    def test_flag_survives_closing_the_parent_story(self, task):
        """A lone task closes its story, which is another post-note update."""
        from projectman.server import pm_done_next

        note = "e" * (RUN_LOG_NOTE_LIMIT + 3)
        payload = parse(pm_done_next(task, note=note))
        assert payload["story_closed"] == "US-TST-1"
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == len(note)

    def test_reported_stored_length_matches_the_persisted_note(self, truncated, two_tasks):
        from projectman.server import pm_run_log

        _, payload = truncated
        entries = yaml.safe_load(pm_run_log(two_tasks[0]))
        entries = entries["run_log"] if isinstance(entries, dict) else entries
        stored = entries[-1]["note"]
        assert MARKER_RE.search(stored), stored[-60:]
        assert len(stored) == payload["note_stored_length"]

    def test_note_that_fits_reports_nothing(self, two_tasks):
        from projectman.server import pm_done_next

        payload = parse(pm_done_next(two_tasks[0], note="all done"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_note_exactly_at_limit_reports_nothing(self, two_tasks):
        from projectman.server import pm_done_next

        payload = parse(pm_done_next(two_tasks[0], note="x" * RUN_LOG_NOTE_LIMIT))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_one_char_over_the_limit_does_report(self, two_tasks):
        """The boundary is exclusive here too — limit+1 is the first truncation."""
        from projectman.server import pm_done_next

        note = "x" * (RUN_LOG_NOTE_LIMIT + 1)
        payload = parse(pm_done_next(two_tasks[0], note=note))
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 1
        assert payload["note_dropped_chars"] > 0

    def test_a_very_large_note_reports_correctly(self, two_tasks):
        """A note orders of magnitude over the cap still reconciles.

        The dropped count is six digits wide here, which is what makes the
        marker's own width feed back into the arithmetic.
        """
        from projectman.server import pm_done_next, pm_run_log

        note = "x" * 100_000
        payload = parse(pm_done_next(two_tasks[0], note=note))
        assert TRUNCATION_KEYS <= set(payload), sorted(TRUNCATION_KEYS - set(payload))
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == 100_000
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT
        assert payload["completed"]["status"] == "done"

        entries = yaml.safe_load(pm_run_log(two_tasks[0]))
        entries = entries["run_log"] if isinstance(entries, dict) else entries
        stored = entries[-1]["note"]
        marker = MARKER_RE.search(stored)
        assert marker, stored[-60:]
        assert len(stored) == payload["note_stored_length"]
        assert int(marker.group(1)) == payload["note_dropped_chars"]
        kept = stored[: -len(marker.group(0))]
        assert len(kept) + payload["note_dropped_chars"] == 100_000

    def test_no_note_reports_nothing(self, two_tasks):
        from projectman.server import pm_done_next

        payload = parse(pm_done_next(two_tasks[0]))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_flag_is_reported_when_nothing_follows(self, two_tasks):
        """The expected-negative response must still carry the flag.

        `no_next_task` rebuilds the response dict; a rebuild that dropped the
        truncation fields would lose them only on this branch.
        """
        from projectman.server import pm_done_next

        first, second = two_tasks
        parse(pm_done_next(first, note="first"))
        payload = parse(pm_done_next(second, note="f" * (RUN_LOG_NOTE_LIMIT + 11)))
        assert payload["next"] is None
        assert payload["status"] == "no_next_task"
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 11

    def test_later_call_does_not_inherit_the_flag(self, truncated, two_tasks):
        from projectman.server import pm_update

        payload = parse(pm_update(two_tasks[1], status="review"))
        assert TRUNCATION_KEYS.isdisjoint(payload)


class TestRelease:
    """``pm_release`` takes a note too, so it reports on the same terms."""

    @pytest.fixture
    def held(self, task):
        from projectman.server import pm_update

        pm_update(task, assignee="claude", status="in-progress")
        return task

    def test_flag_is_true_and_complete(self, held):
        from projectman.server import pm_release

        note = "r" * (RUN_LOG_NOTE_LIMIT + 250)
        payload = parse(pm_release(held, note=note))
        assert TRUNCATION_KEYS <= set(payload), sorted(TRUNCATION_KEYS - set(payload))
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == len(note)
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT
        assert payload["note_limit"] == RUN_LOG_NOTE_LIMIT

    def test_release_still_landed(self, held):
        from projectman.server import pm_release

        payload = parse(pm_release(held, note="r" * (RUN_LOG_NOTE_LIMIT + 250)))
        assert payload["released"]["from_assignee"] == "claude"
        assert payload["released"]["task"]["assignee"] is None
        assert payload["released"]["task"]["status"] == "todo"

    def test_note_that_fits_reports_nothing(self, held):
        from projectman.server import pm_release

        payload = parse(pm_release(held, note="handing it back"))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_note_exactly_at_limit_reports_nothing(self, held):
        """At the cap, absence is how the contract spells "stored whole"."""
        from projectman.server import pm_release

        payload = parse(pm_release(held, note="x" * RUN_LOG_NOTE_LIMIT))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_one_char_over_the_limit_does_report(self, held):
        from projectman.server import pm_release

        payload = parse(pm_release(held, note="x" * (RUN_LOG_NOTE_LIMIT + 1)))
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 1
        assert payload["note_dropped_chars"] > 0

    def test_a_very_large_note_reports_correctly(self, held):
        from projectman.server import pm_release, pm_run_log

        payload = parse(pm_release(held, note="x" * 100_000))
        assert TRUNCATION_KEYS <= set(payload), sorted(TRUNCATION_KEYS - set(payload))
        assert payload["note_original_length"] == 100_000
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT
        assert payload["released"]["task"]["status"] == "todo"

        entries = yaml.safe_load(pm_run_log(held))
        entries = entries["run_log"] if isinstance(entries, dict) else entries
        stored = entries[-1]["note"]
        marker = MARKER_RE.search(stored)
        assert marker, stored[-60:]
        assert len(stored) == payload["note_stored_length"]
        assert int(marker.group(1)) == payload["note_dropped_chars"]

    def test_no_note_reports_nothing(self, held):
        from projectman.server import pm_release

        payload = parse(pm_release(held))
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_a_refused_release_reports_nothing(self, held):
        """A guarded release that loses writes nothing, so it truncates nothing."""
        from projectman.server import pm_release

        payload = parse(
            pm_release(
                held,
                note="z" * (RUN_LOG_NOTE_LIMIT + 5),
                expected_assignee="someone-else",
            )
        )
        assert payload["status"] == "not_holder"
        assert TRUNCATION_KEYS.isdisjoint(payload)

    def test_later_call_does_not_inherit_the_flag(self, held):
        from projectman.server import pm_release, pm_update

        parse(pm_release(held, note="r" * (RUN_LOG_NOTE_LIMIT + 30)))
        assert TRUNCATION_KEYS.isdisjoint(parse(pm_update(held, points=3)))


class TestResponseSize:
    """The non-truncated response must not grow — response bytes are tracked."""

    def test_note_that_fits_costs_no_extra_bytes(self, task):
        from projectman.server import pm_update

        # ``outcome`` is held constant: it is echoed back as ``run_log``, so
        # dropping it from the control would measure that echo rather than the
        # note.  The note is the only thing that differs between the two calls.
        with_note = pm_update(task, status="done", outcome="success", note="ok")
        without_note = pm_update(task, status="done", outcome="success")
        assert len(with_note) == len(without_note)
