"""Repairing tasks whose archive was recorded but lost from disk (US-PM-16-7).

Originally this suite pinned an *inference*: a done task whose last status
event moved it ``todo``/``blocked`` -> ``done`` changing only ``status`` was
assumed to be a pre-US-PM-16 archive and reverted to its prior status.
US-PM-17-6 rejected that rule — closing a task in a single write leaves a
byte-identical footprint — and US-PM-17-7 replaced it with a positive signal:
an activity event that explicitly wrote ``archived: true``.

So the tests below pin the new contract: identification needs a logged archive,
applying restores a status *only* when the archive event itself recorded one,
the old footprint is reported under ``needs_review`` and never written, plus
the dry-run default, idempotency, and this repo's real ``.project/`` data —
against a *copy*, never the live directory.

Completion itself is parametrized (US-PM-17-8).  Modelling it a single way is
what let the bug through, so every assertion that genuine completion is safe
takes the ``complete`` fixture and runs once per entry in
:data:`COMPLETION_PATHS` — through ``in-progress``, and closed in one write
from ``todo`` or from ``blocked``.
"""

import inspect
import json
import re
import shutil
from functools import partial
from pathlib import Path

import frontmatter
import pytest

from projectman import migrations
from projectman.migrations import (
    find_archived_as_done,
    format_report,
    migrate_archived_as_done,
    read_activity_log,
)
from projectman.store import Store, _cache


# ─── helpers ──────────────────────────────────────────────────────────


def _make_task(store, title="Task"):
    """Create a story (once) plus a task, returning the task id."""
    if not store.list_stories():
        store.create_story("Story", "Desc")
    tasks = store.list_tasks(story_id="US-TST-1")
    store.create_task("US-TST-1", title, "Desc")
    return f"US-TST-1-{len(tasks) + 1}"


def _new_task(store, title="Task", **kwargs):
    """Create the shared story once, then a task, returning its id."""
    if not store.list_stories():
        store.create_story("Story", "Desc")
    return store.create_task("US-TST-1", title, kwargs.pop("body", "Desc"), **kwargs).id


def _log_path(store):
    return store.project_dir / "activity.jsonl"


def _read_log(store):
    return [
        json.loads(line)
        for line in _log_path(store).read_text().splitlines()
        if line.strip()
    ]


def _write_log(store, entries):
    _log_path(store).write_text("".join(json.dumps(e) + "\n" for e in entries))
    _cache.clear()


def _status_entries(entries, task_id):
    return [
        e
        for e in entries
        if e.get("item_id") == task_id and "status" in (e.get("changes") or {})
    ]


def _archive_entries(entries, task_id):
    return [
        e
        for e in entries
        if e.get("item_id") == task_id and "archived" in (e.get("changes") or {})
    ]


def _set_archived_field(store, task_id, value):
    """Write the ``archived`` frontmatter key directly — no event is logged.

    This is the disk half of the only shape the migration may repair: a
    dropped write, a hand-edited or restored frontmatter, a bad merge.
    ``value=None`` removes the key entirely, as on a file written before the
    field existed.
    """
    path = store.tasks_dir / f"{task_id}.md"
    post = frontmatter.load(str(path))
    if value is None:
        post.metadata.pop("archived", None)
    else:
        post.metadata["archived"] = value
    path.write_text(frontmatter.dumps(post))
    _cache.clear()


def _legacy_archive(store, task_id, *, from_status=None, strip_field=True):
    """Reproduce the pre-US-PM-16 archive: update(status="done"), nothing else.

    This is *also* exactly what closing a task in one write looks like, which
    is why US-PM-17-6 stopped treating it as evidence.  Tasks built this way
    are never candidates; the most they can be is ``needs_review``.
    """
    if from_status is not None:
        store.update(task_id, status=from_status)
    store.update(task_id, status="done")
    if strip_field:
        _set_archived_field(store, task_id, None)
    return task_id


def _dropped_archive_flag(store, task_id, *, prior_status=None, strip_field=True):
    """The one repairable shape: the log records an archive, the file lost it.

    The task ends ``status: done`` on disk with no ``archived`` flag, while
    ``activity.jsonl`` carries an explicit ``archived: false -> true`` write.

    ``prior_status`` folds a status change into the archive event itself (what
    a dedicated archive event would record if archiving ever moved status),
    which is the only thing that licenses writing a status back.
    """
    if prior_status is not None:
        store.update(task_id, status=prior_status)
    store.update(task_id, status="done")
    store.archive(task_id)

    if prior_status is not None:
        entries = _read_log(store)
        # The archive event, not a separate update, is what took it to done.
        entries.remove(_status_entries(entries, task_id)[-1])
        for entry in _archive_entries(entries, task_id):
            entry["changes"]["status"] = {"before": prior_status, "after": "done"}
        _write_log(store, entries)

    _set_archived_field(store, task_id, None if strip_field else False)
    return task_id


#: Every way a task genuinely reaches ``done``, as the status writes it takes.
#:
#: The suite used to model completion one way only — ``_genuinely_complete``,
#: pick the task up then finish it — and that blind spot is what hid the bug
#: US-PM-17 exists to fix (US-PM-17-8 replaced it with this table).  A task
#: closed in one write from ``todo`` leaves a footprint the old rule treated
#: as an archive, so ``--apply`` un-completed it.  Both single-write forms are
#: routine (``pm_update(id, status="done")`` and ``pm_done_next`` on an
#: ungrabbed task both do it, from ``todo`` or from ``blocked``).
#:
#: Anywhere the suite asserts "genuine completion is safe", it takes the
#: ``complete`` fixture below and runs once per path rather than picking one.
COMPLETION_PATHS: dict[str, tuple[str, ...]] = {
    "via-in-progress": ("in-progress", "done"),
    "single-write": ("done",),
    "single-write-from-blocked": ("blocked", "done"),
}


def _complete(store, task_id, path):
    """Finish *task_id* by walking the status writes of *path*."""
    for status in COMPLETION_PATHS[path]:
        store.update(task_id, status=status)
    return task_id


def _reopen_and_complete(store, task_id, path):
    """Pick a *done* task back up and finish it again along *path*.

    A single-write close is only observable on a task that is not already
    done, so those paths are preceded by an explicit reopen to ``todo`` —
    which is what reopening actually looks like.  ``via-in-progress`` needs no
    such prefix: moving to ``in-progress`` is itself the reopen.
    """
    if COMPLETION_PATHS[path][0] != "in-progress":
        store.update(task_id, status="todo")
    return _complete(store, task_id, path)


def _complete_every_way(store, label="Real", make=None):
    """One genuinely finished task per completion path, keyed by path name."""
    make = make or _new_task
    return {
        path: _complete(store, make(store, f"{label} ({path})"), path)
        for path in COMPLETION_PATHS
    }


@pytest.fixture(params=list(COMPLETION_PATHS), ids=list(COMPLETION_PATHS))
def completion_path(request):
    """The name of one genuine completion path, once per path."""
    return request.param


@pytest.fixture
def complete(completion_path):
    """``complete(store, task_id)`` — finish a task along the current path."""
    return partial(_complete, path=completion_path)


@pytest.fixture
def reopen_and_complete(completion_path):
    """``reopen_and_complete(store, task_id)`` — re-finish along the current path."""
    return partial(_reopen_and_complete, path=completion_path)


def _task_meta(store, task_id):
    _cache.clear()
    meta, _ = store.get_task(task_id)
    return meta


def _snapshot(project_dir: Path) -> dict[str, bytes]:
    """Byte-for-byte contents of a tree.

    Read as bytes, not text: a project directory can hold binary files (the
    embeddings database, for one) that are not decodable as UTF-8, and this
    helper only ever compares snapshots for equality.
    """
    return {
        str(p.relative_to(project_dir)): p.read_bytes()
        for p in sorted(project_dir.rglob("*"))
        if p.is_file()
    }


# ─── identification ───────────────────────────────────────────────────


class TestIdentification:
    """A candidate is a logged archive whose file has lost the flag."""

    def test_finds_a_task_whose_archived_flag_was_lost(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [task_id]

    def test_records_the_status_the_archive_event_logged(self, store):
        task_id = _dropped_archive_flag(
            store, _make_task(store), prior_status="blocked"
        )
        (candidate,) = find_archived_as_done(store).candidates
        assert (candidate.task_id, candidate.prior_status) == (task_id, "blocked")

    def test_prior_status_is_none_when_the_archive_logged_no_status(self, store):
        """Today's ``Store.archive`` never touches status — so neither may we."""
        _dropped_archive_flag(store, _make_task(store))
        (candidate,) = find_archived_as_done(store).candidates
        assert candidate.prior_status is None

    def test_records_when_it_was_archived(self, store):
        _dropped_archive_flag(store, _make_task(store))
        (candidate,) = find_archived_as_done(store).candidates
        assert candidate.archived_at

    def test_finds_task_that_still_carries_archived_false(self, store):
        """The flag was reset rather than removed: same disagreement."""
        task_id = _dropped_archive_flag(store, _make_task(store), strip_field=False)
        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [task_id]

    def test_finds_several_at_once(self, store):
        first = _dropped_archive_flag(store, _make_task(store, "One"))
        second = _dropped_archive_flag(store, _make_task(store, "Two"))
        report = find_archived_as_done(store)
        assert sorted(c.task_id for c in report.candidates) == sorted([first, second])

    def test_reports_nothing_when_the_log_is_missing(self, store):
        _dropped_archive_flag(store, _make_task(store))
        (store.project_dir / "activity.jsonl").unlink()
        _cache.clear()
        assert find_archived_as_done(store).candidates == []

    def test_corrupt_log_lines_are_tolerated(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        log = store.project_dir / "activity.jsonl"
        log.write_text("not json at all\n\n" + log.read_text())
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_the_old_status_footprint_is_not_a_candidate(self, store):
        """US-PM-17: ``todo -> done`` in one write proves nothing either way."""
        _legacy_archive(store, _make_task(store))
        assert find_archived_as_done(store).candidates == []

    def test_the_old_status_footprint_is_reported_for_review(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        report = find_archived_as_done(store)
        assert [s.task_id for s in report.needs_review] == [task_id]
        reason = report.needs_review[0].reason
        assert "pm_archive" in reason
        assert "Store.archive" in reason

    def test_the_review_reason_cites_only_real_remedies(self, store):
        """US-PM-17-9: it used to point at a `projectman archive` that never existed."""
        from projectman.cli import cli

        _legacy_archive(store, _make_task(store))
        reason = find_archived_as_done(store).needs_review[0].reason
        cited = set(re.findall(r"projectman ([a-z][a-z-]+)", reason))
        assert cited <= set(cli.commands), (
            f"review reason cites commands that do not exist: "
            f"{sorted(cited - set(cli.commands))}"
        )

    def test_a_task_is_never_both_a_candidate_and_needing_review(self, store):
        _dropped_archive_flag(store, _make_task(store, "Lost flag"))
        _legacy_archive(store, _make_task(store, "Single write"))
        report = find_archived_as_done(store)
        assert {c.task_id for c in report.candidates}.isdisjoint(
            {s.task_id for s in report.needs_review}
        )


# ─── genuinely done work must be left alone ───────────────────────────


class TestGenuinelyDoneTasksAreUntouched:
    """The migration must never demote real completed work.

    Every assertion here that is about completion as such runs once per entry
    in :data:`COMPLETION_PATHS`; the tests that pin a *particular* path's
    report text keep their own bodies below.
    """

    def test_completion_is_not_a_candidate(self, store, complete):
        complete(store, _make_task(store))
        assert find_archived_as_done(store).candidates == []

    def test_completion_leaves_no_write_to_make(self, store, complete):
        """Not just un-flagged: an applied run writes nothing at all."""
        task_id = complete(store, _make_task(store))
        _cache.clear()
        path = store.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(store, apply=True)

        assert report.migrated == []
        assert path.read_bytes() == before
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_completion_from_review_is_not_a_candidate(self, store):
        task_id = _make_task(store)
        store.update(task_id, status="review")
        store.update(task_id, status="done")
        assert find_archived_as_done(store).candidates == []

    def test_single_write_completion_survives_an_applied_run(self, store):
        task_id = _make_task(store)
        store.update(task_id, status="done")
        _cache.clear()
        path = store.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        # Being reported for a human is allowed; being written is not.
        assert [s.task_id for s in report.needs_review] == [task_id]
        assert path.read_bytes() == before

    def test_single_write_completion_from_blocked_is_not_a_candidate(self, store):
        """``blocked`` is the other never-started status — same verdict."""
        task_id = _legacy_archive(store, _make_task(store), from_status="blocked")
        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]
        assert "blocked -> done" in report.needs_review[0].reason

    def test_single_write_completion_from_blocked_survives_an_applied_run(self, store):
        task_id = _legacy_archive(store, _make_task(store), from_status="blocked")
        _cache.clear()
        path = store.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert path.read_bytes() == before
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_completion_alongside_other_field_changes_is_not_a_candidate(
        self, store
    ):
        task_id = _make_task(store)
        store.update(task_id, status="done", assignee="claude")
        assert find_archived_as_done(store).candidates == []

    def test_genuine_completion_survives_an_applied_run(self, store, complete):
        """A real archive in the same project is repaired; this one is not."""
        done_id = complete(store, _make_task(store, "Real"))
        archived_id = _dropped_archive_flag(store, _make_task(store, "Archived"))
        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == [archived_id]
        meta = _task_meta(store, done_id)
        assert meta.status.value == "done"
        assert meta.archived is False

    def test_task_already_archived_under_new_semantics_is_skipped(self, store):
        """``archived: true`` is already an honest record — nothing to fix."""
        task_id = _make_task(store)
        store.update(task_id, status="done")
        store.archive(task_id)
        assert find_archived_as_done(store).candidates == []

    def test_non_done_tasks_are_never_examined(self, store):
        _make_task(store)
        report = find_archived_as_done(store)
        assert report.examined == 0
        assert report.candidates == []


# ─── the re-opened false positive ─────────────────────────────────────


class TestReopenedAfterTheArchive:
    """Archived, then picked back up: the archive is stale evidence.

    Re-applying the flag would drop delivered work out of the metrics — the
    same damage the migration exists to undo, pointed the other way.
    """

    def _reopen_and_finish(self, store, reopen_and_complete):
        """Archive the task, then finish it again — once per completion path."""
        task_id = _dropped_archive_flag(store, _make_task(store))
        return reopen_and_complete(store, task_id)

    def test_not_reported_as_a_candidate(self, store, reopen_and_complete):
        self._reopen_and_finish(store, reopen_and_complete)
        assert find_archived_as_done(store).candidates == []

    def test_reported_as_an_explicit_skip(self, store, reopen_and_complete):
        task_id = self._reopen_and_finish(store, reopen_and_complete)
        report = find_archived_as_done(store)
        assert [s.task_id for s in report.skipped] == [task_id]
        assert "after the archive" in report.skipped[0].reason

    def test_applied_run_leaves_it_done_and_unarchived(
        self, store, reopen_and_complete
    ):
        task_id = self._reopen_and_finish(store, reopen_and_complete)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "done"
        assert meta.archived is False

    def test_reopened_back_to_todo_is_also_skipped(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        store.update(task_id, status="todo")
        store.update(task_id, status="done")
        assert find_archived_as_done(store).candidates == []

    def test_a_legacy_footprint_reopened_and_finished_is_not_even_reported(
        self, store, reopen_and_complete
    ):
        """No signal and work continued: ordinary completion, nothing to say."""
        task_id = _legacy_archive(store, _make_task(store))
        reopen_and_complete(store, task_id)
        report = find_archived_as_done(store)
        assert report.candidates == []
        assert report.needs_review == []


# ─── an unarchive clears the signal ───────────────────────────────────


class TestUnarchiveClearsTheSignal:
    """The last explicit write to the flag wins."""

    def test_archive_then_unarchive_is_not_a_candidate(self, store):
        task_id = _make_task(store)
        store.update(task_id, status="done")
        store.archive(task_id)
        store.unarchive(task_id)
        assert find_archived_as_done(store).candidates == []

    def test_a_re_archive_after_an_unarchive_is_a_signal_again(self, store):
        task_id = _make_task(store)
        store.update(task_id, status="done")
        store.archive(task_id)
        store.unarchive(task_id)
        store.archive(task_id)
        _set_archived_field(store, task_id, None)
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]


# ─── unknowable prior status ──────────────────────────────────────────


class TestUnknowablePriorStatus:
    """Never invent a status the log does not record."""

    def _log_archive_without_before(self, store, task_id):
        entries = _read_log(store)
        for entry in entries:
            if entry["item_id"] == task_id and "status" in (entry.get("changes") or {}):
                entry["changes"]["status"]["before"] = None
        _write_log(store, entries)

    def test_footprint_without_a_prior_status_is_flagged_for_review(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        self._log_archive_without_before(store, task_id)
        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]

    def test_footprint_without_a_prior_status_is_left_untouched(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        self._log_archive_without_before(store, task_id)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "done"
        assert meta.archived is False

    def test_archive_event_with_an_unusable_status_is_flagged_for_review(self, store):
        """A signal whose status payload is junk writes nothing at all."""
        task_id = _dropped_archive_flag(store, _make_task(store))
        entries = _read_log(store)
        for entry in _archive_entries(entries, task_id):
            entry["changes"]["status"] = {"before": "wibble", "after": "done"}
        _write_log(store, entries)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]
        assert "invented" in report.needs_review[0].reason

    def test_archive_event_with_an_unusable_status_is_left_untouched(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        entries = _read_log(store)
        for entry in _archive_entries(entries, task_id):
            entry["changes"]["status"] = {"after": "done"}
        _write_log(store, entries)

        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)


# ─── dry run ──────────────────────────────────────────────────────────


class TestDryRunIsTheDefault:
    def test_find_writes_nothing(self, store):
        _dropped_archive_flag(store, _make_task(store))
        before = _snapshot(store.project_dir)
        find_archived_as_done(store)
        assert _snapshot(store.project_dir) == before

    def test_migrate_without_apply_writes_nothing(self, store):
        _dropped_archive_flag(store, _make_task(store))
        before = _snapshot(store.project_dir)
        report = migrate_archived_as_done(store)
        assert _snapshot(store.project_dir) == before
        assert report.applied is False
        assert report.migrated == []
        assert report.candidates

    def test_dry_run_appends_no_activity_entries(self, store):
        _dropped_archive_flag(store, _make_task(store))
        before = len(read_activity_log(store.project_dir))
        migrate_archived_as_done(store)
        assert len(read_activity_log(store.project_dir)) == before

    def test_dry_run_report_says_so(self, store):
        _dropped_archive_flag(store, _make_task(store))
        text = format_report(migrate_archived_as_done(store))
        assert "DRY RUN" in text
        assert "--apply" in text


# ─── applying ─────────────────────────────────────────────────────────


class TestApply:
    def test_sets_the_archived_flag(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        assert _task_meta(store, task_id).archived is True

    def test_leaves_the_status_alone_when_the_archive_logged_none(self, store):
        """The invariant: never out of ``done`` on inferred evidence."""
        task_id = _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        assert _task_meta(store, task_id).status.value == "done"

    def test_restores_the_status_the_archive_event_recorded(self, store):
        task_id = _dropped_archive_flag(
            store, _make_task(store), prior_status="blocked"
        )
        migrate_archived_as_done(store, apply=True)
        assert _task_meta(store, task_id).status.value == "blocked"

    def test_reports_what_it_migrated(self, store):
        task_id = _dropped_archive_flag(store, _make_task(store))
        report = migrate_archived_as_done(store, apply=True)
        assert report.applied is True
        assert report.migrated == [task_id]
        assert report.changed is True

    def test_migrated_task_drops_out_of_completion_metrics(self, store):
        """The whole point: abandoned work stops counting as delivered."""
        task_id = _dropped_archive_flag(store, _make_task(store))
        assert [t.id for t in store.list_tasks(status="done", archived=False)] == [
            task_id
        ]
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        assert store.list_tasks(status="done", archived=False) == []

    def test_index_reflects_the_migration(self, store):
        import yaml

        task_id = _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        index = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        entry = next(e for e in index["entries"] if e["id"] == task_id)
        assert entry["archived"] is True

    def test_nothing_under_needs_review_is_written(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        assert [s.task_id for s in report.needs_review] == [task_id]
        assert report.migrated == []
        assert _snapshot(store.tasks_dir) == before


# ─── idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_second_applied_run_finds_nothing(self, store):
        _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        second = migrate_archived_as_done(store, apply=True)
        assert second.candidates == []
        assert second.migrated == []

    def test_second_run_does_not_change_the_files(self, store):
        _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        tasks_before = _snapshot(store.tasks_dir)
        migrate_archived_as_done(store, apply=True)
        assert _snapshot(store.tasks_dir) == tasks_before

    def test_status_is_not_walked_back_twice(self, store):
        task_id = _dropped_archive_flag(
            store, _make_task(store), prior_status="blocked"
        )
        migrate_archived_as_done(store, apply=True)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "blocked"
        assert meta.archived is True

    def test_dry_run_after_apply_is_clean(self, store):
        _dropped_archive_flag(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        report = migrate_archived_as_done(store)
        assert report.candidates == []
        assert "no archived-as-done tasks found" in format_report(report)


# ─── a realistic multi-task project, built deterministically ──────────


class TestAgainstARealisticProject:
    """The identification rules against a project with mixed history.

    This class used to run against a *copy* of this repo's own ``.project/``
    directory and assert set-equality with a hardcoded pair of task ids.  That
    coupled a unit test to live project data: closing any unrelated task
    straight from ``todo`` to ``done`` added a candidate and broke the
    equality, which is exactly what happened when a ``/pm audit`` pass closed
    four stale placeholder tasks.  The fixture below reproduces the same
    *shape* of history without depending on data that legitimately changes.
    """

    @pytest.fixture
    def realistic(self, tmp_project):
        _cache.clear()
        store = Store(tmp_project)

        # Genuinely finished work, one task per completion path.  A realistic
        # project holds a mix, not five closes of the same shape — and the
        # single-write shapes are the ones the rejected rule acted on.
        self.by_path = _complete_every_way(store, "Real", make=_make_task)
        self.genuine = list(self.by_path.values())
        # Closed in a single write — the shape the old rule wrongly acted on.
        self.single_write = _legacy_archive(store, _make_task(store, "Single write"))
        # Logged archives whose files lost the flag: the repairable class.
        self.lost_flag = _dropped_archive_flag(store, _make_task(store, "Lost flag"))
        self.lost_flag_with_status = _dropped_archive_flag(
            store, _make_task(store, "Lost flag, logged status"), prior_status="blocked"
        )
        # Archived, then picked back up and finished — must be skipped.
        self.reopened = _dropped_archive_flag(store, _make_task(store, "Reopened"))
        store.update(self.reopened, status="in-progress")
        store.update(self.reopened, status="done")
        _cache.clear()
        return store

    REPAIRABLE = property(
        lambda self: {self.lost_flag, self.lost_flag_with_status}
    )

    def test_finds_exactly_the_lost_flags(self, realistic):
        report = find_archived_as_done(realistic)
        assert {c.task_id for c in report.candidates} == self.REPAIRABLE

    def test_only_the_logged_status_is_restored(self, realistic):
        report = find_archived_as_done(realistic)
        prior = {c.task_id: c.prior_status for c in report.candidates}
        assert prior[self.lost_flag] is None
        assert prior[self.lost_flag_with_status] == "blocked"

    def test_genuinely_done_tasks_are_left_alone(self, realistic):
        report = find_archived_as_done(realistic)
        flagged = {c.task_id for c in report.candidates}
        assert flagged.isdisjoint(self.genuine)
        assert report.examined > len(self.REPAIRABLE)

    def test_every_completion_path_survives_an_applied_run(self, realistic):
        """Named per path, so a failure says which close was demoted."""
        migrate_archived_as_done(realistic, apply=True)
        after = {
            path: (
                _task_meta(realistic, task_id).status.value,
                _task_meta(realistic, task_id).archived,
            )
            for path, task_id in self.by_path.items()
        }
        assert after == {path: ("done", False) for path in COMPLETION_PATHS}

    def test_the_single_write_close_is_reported_not_migrated(self, realistic):
        report = find_archived_as_done(realistic)
        assert self.single_write not in {c.task_id for c in report.candidates}
        assert self.single_write in {s.task_id for s in report.needs_review}

    def test_reopened_task_is_skipped_not_migrated(self, realistic):
        report = find_archived_as_done(realistic)
        assert self.reopened not in {c.task_id for c in report.candidates}
        assert self.reopened in {s.task_id for s in report.skipped}

    def test_apply_migrates_only_the_lost_flags(self, realistic):
        report = migrate_archived_as_done(realistic, apply=True)
        assert set(report.migrated) == self.REPAIRABLE
        _cache.clear()
        archived = {t.id for t in realistic.list_tasks(archived=True)}
        assert archived == self.REPAIRABLE

    def test_apply_moves_only_the_task_whose_status_was_logged(self, realistic):
        done_before = {t.id for t in realistic.list_tasks(status="done")}
        migrate_archived_as_done(realistic, apply=True)
        _cache.clear()
        done_after = {t.id for t in realistic.list_tasks(status="done")}
        assert done_before - done_after == {self.lost_flag_with_status}

    def test_apply_is_idempotent(self, realistic):
        migrate_archived_as_done(realistic, apply=True)
        assert migrate_archived_as_done(realistic, apply=True).migrated == []


# ─── this repository's real data, against a copy ──────────────────────


REAL_PROJECT = Path(__file__).resolve().parents[1] / ".project"


@pytest.mark.skipif(
    not (REAL_PROJECT / "activity.jsonl").exists(),
    reason="this repo's own .project/ data is not present",
)
class TestAgainstACopyOfThisProject:
    """Smoke-check the migration against real, messy project data.

    Deliberately makes no claim about *which* tasks are candidates — that set
    changes as the project is worked, and pinning it is what made the previous
    version of this class brittle.  What is asserted here is invariant: the
    live directory is never written, nothing leaves ``done`` unless the log
    said so, and everything under ``needs_review`` is left alone.
    """

    @pytest.fixture
    def real_copy(self, tmp_path):
        _cache.clear()
        shutil.copytree(REAL_PROJECT, tmp_path / ".project")
        return Store(tmp_path)

    def test_no_task_leaves_done_without_a_logged_status(self, real_copy):
        report = find_archived_as_done(real_copy)
        demoted = {c.task_id for c in report.candidates if c.prior_status is not None}
        done_before = {t.id for t in real_copy.list_tasks(status="done")}

        migrate_archived_as_done(real_copy, apply=True)
        _cache.clear()
        done_after = {t.id for t in real_copy.list_tasks(status="done")}
        assert done_before - done_after <= demoted

    def test_tasks_needing_review_are_never_written(self, real_copy):
        report = find_archived_as_done(real_copy)
        paths = [real_copy.tasks_dir / f"{s.task_id}.md" for s in report.needs_review]
        before = {p.name: p.read_bytes() for p in paths}

        migrate_archived_as_done(real_copy, apply=True)
        assert {p.name: p.read_bytes() for p in paths} == before

    def test_apply_is_idempotent_on_real_data(self, real_copy):
        migrate_archived_as_done(real_copy, apply=True)
        assert migrate_archived_as_done(real_copy, apply=True).migrated == []

    def test_settled_archives_are_neither_reported_nor_written(self, real_copy):
        """US-PM-17-3 — this repo's known legacy archives are handled.

        US-PM-1-1 and US-PM-2-1 were archived before ``Store.archive`` wrote
        the flag.  US-PM-17-9 applied ADR-002's manual remedy to both, so they
        now carry ``archived: true`` with ``status: done`` untouched and a
        positive archive signal in the log.  Such a task is settled: the
        migration has nothing left to say about it.

        Asserted as a property of every archived-and-done task rather than by
        id — pinning ids is what made this class brittle before.
        """
        settled = {}
        for path in sorted(real_copy.tasks_dir.glob("*.md")):
            meta = frontmatter.load(path).metadata
            if meta.get("archived") is True and meta.get("status") == "done":
                settled[path.name] = path.read_bytes()
        assert settled, "no archived-and-done task in this repo's data"

        report = migrate_archived_as_done(real_copy, apply=True)
        reported = (
            {c.task_id for c in report.candidates}
            | {s.task_id for s in report.needs_review}
            | {s.task_id for s in report.skipped}
        )
        assert reported.isdisjoint({name[:-3] for name in settled})
        assert {
            name: (real_copy.tasks_dir / name).read_bytes() for name in settled
        } == settled

    def _seed(self, store, complete):
        """A freshly completed task inside the real data, on the current path."""
        story, _ = store.create_story("Completion path probe", "US-PM-17-8")
        task = store.create_task(story.id, "Probe", "Desc")
        _cache.clear()
        return complete(store, task.id)

    def test_work_completed_in_real_data_is_never_demoted(
        self, real_copy, complete
    ):
        """Every completion path, against this repo's actual history.

        The four tasks that exposed US-PM-17 were closed straight from
        ``todo`` by a ``/pm audit`` pass, in exactly this project.
        """
        task_id = self._seed(real_copy, complete)
        _cache.clear()
        path = real_copy.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(real_copy, apply=True)

        assert task_id not in report.migrated
        assert path.read_bytes() == before
        meta = _task_meta(real_copy, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_live_project_directory_is_never_written(self, real_copy):
        """Belt and braces: the copy is what changed, not the repo."""
        before = {
            p.name: p.read_bytes() for p in (REAL_PROJECT / "tasks").glob("*.md")
        }
        migrate_archived_as_done(real_copy, apply=True)
        after = {p.name: p.read_bytes() for p in (REAL_PROJECT / "tasks").glob("*.md")}
        assert before == after


# ─── the CLI surface ──────────────────────────────────────────────────


class TestCliCommand:
    """``projectman migrate-archived`` is the only way to trigger this.

    Nothing runs it on load or as a side effect of another command, and the
    bare invocation reports without writing.
    """

    @pytest.fixture
    def cli_project(self, tmp_project, monkeypatch):
        _cache.clear()
        store = Store(tmp_project)
        _dropped_archive_flag(store, _make_task(store))
        # One genuinely finished task per completion path, so the CLI's own
        # write path is exercised against all of them, not just one shape.
        self.genuine = _complete_every_way(store, "Real", make=_make_task)
        monkeypatch.chdir(tmp_project)
        _cache.clear()
        return store

    def _run(self, args):
        from click.testing import CliRunner

        from projectman.cli import cli

        return CliRunner().invoke(cli, args)

    def test_bare_invocation_is_a_dry_run(self, cli_project):
        before = _snapshot(cli_project.tasks_dir)
        result = self._run(["migrate-archived"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert "US-TST-1-1" in result.output
        assert _snapshot(cli_project.tasks_dir) == before

    def test_apply_flag_writes(self, cli_project):
        result = self._run(["migrate-archived", "--apply"])
        assert result.exit_code == 0, result.output
        assert "APPLIED" in result.output
        assert _task_meta(cli_project, "US-TST-1-1").archived is True

    def test_apply_is_idempotent_through_the_cli(self, cli_project):
        self._run(["migrate-archived", "--apply"])
        _cache.clear()
        result = self._run(["migrate-archived", "--apply"])
        assert "no archived-as-done tasks found" in result.output

    def test_genuinely_done_tasks_untouched_by_the_cli(self, cli_project):
        result = self._run(["migrate-archived", "--apply"])
        assert result.exit_code == 0, result.output
        after = {
            path: (
                _task_meta(cli_project, task_id).status.value,
                _task_meta(cli_project, task_id).archived,
            )
            for path, task_id in self.genuine.items()
        }
        assert after == {path: ("done", False) for path in COMPLETION_PATHS}

    def test_single_write_close_is_reported_for_review_not_written(
        self, tmp_project, monkeypatch
    ):
        _cache.clear()
        store = Store(tmp_project)
        task_id = _legacy_archive(store, _make_task(store))
        monkeypatch.chdir(tmp_project)
        _cache.clear()

        result = self._run(["migrate-archived", "--apply"])
        assert result.exit_code == 0, result.output
        assert "need manual review" in result.output
        assert task_id in result.output
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)


# ─── realistic activity-log shapes ────────────────────────────────────


class TestActivityLogShapes:
    """Identification has to survive the logs real projects actually have.

    Interleaved items, long histories, half-written lines, no log at all —
    none of these may turn into a wrong migration or a traceback.
    """

    def test_interleaved_events_from_another_task_do_not_confuse_it(self, store):
        archived = _new_task(store, "Abandoned")
        genuine = _new_task(store, "Real")
        store.update(genuine, status="in-progress")
        _dropped_archive_flag(store, archived, prior_status="blocked")
        store.update(genuine, status="done")

        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [archived]
        assert report.candidates[0].prior_status == "blocked"

    def test_two_interleaved_archives_are_both_found(self, store):
        first = _new_task(store, "One")
        second = _new_task(store, "Two")
        _dropped_archive_flag(store, first, prior_status="blocked")
        _dropped_archive_flag(store, second)

        report = find_archived_as_done(store)
        assert {c.task_id: c.prior_status for c in report.candidates} == {
            first: "blocked",
            second: None,
        }

    def test_history_before_the_archive_does_not_disqualify_it(self, store):
        """Picked up, put back in the backlog, then archived: still an archive."""
        task_id = _new_task(store)
        store.update(task_id, status="in-progress")
        store.update(task_id, status="todo")
        _dropped_archive_flag(store, task_id)

        (candidate,) = find_archived_as_done(store).candidates
        assert candidate.task_id == task_id

    def test_a_long_genuine_history_is_never_a_candidate(self, store):
        task_id = _new_task(store)
        for status in ("in-progress", "review", "in-progress", "done"):
            store.update(task_id, status=status)
        assert find_archived_as_done(store).candidates == []

    def test_missing_before_key_is_flagged_for_review(self, store):
        """Absent is not the same as null — both must refuse to guess."""
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        _status_entries(entries, task_id)[-1]["changes"]["status"].pop("before")
        _write_log(store, entries)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]

    def test_unrecognised_prior_status_is_flagged_for_review(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        _status_entries(entries, task_id)[-1]["changes"]["status"]["before"] = "wibble"
        _write_log(store, entries)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]
        assert "invented" in report.needs_review[0].reason

    def test_needs_review_is_surfaced_in_the_rendered_report(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        _status_entries(entries, task_id)[-1]["changes"]["status"]["before"] = None
        _write_log(store, entries)

        text = format_report(find_archived_as_done(store))
        assert "need manual review" in text
        assert task_id in text

    def test_empty_activity_log_file(self, store):
        _dropped_archive_flag(store, _new_task(store))
        _log_path(store).write_text("")
        _cache.clear()
        assert read_activity_log(store.project_dir) == []
        assert find_archived_as_done(store).candidates == []

    def test_blank_and_whitespace_only_lines(self, store):
        task_id = _dropped_archive_flag(store, _new_task(store))
        _log_path(store).write_text(
            "\n   \n\n" + _log_path(store).read_text() + "\n  \n"
        )
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_truncated_final_line_is_tolerated(self, store):
        """A log cut off mid-write must not hide the entries before it."""
        task_id = _dropped_archive_flag(store, _new_task(store))
        with _log_path(store).open("a") as fh:
            fh.write('{"event_type": "update", "item_id": "US-TST-1-1", "cha')
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_json_lines_that_are_not_objects_are_ignored(self, store):
        task_id = _dropped_archive_flag(store, _new_task(store))
        _log_path(store).write_text(
            '[1, 2, 3]\n"a bare string"\nnull\n42\n' + _log_path(store).read_text()
        )
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_status_change_without_a_before_after_object_is_ignored(self, store):
        """Some historical rows record a bare value, not a diff."""
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        for entry in _status_entries(entries, task_id):
            entry["changes"]["status"] = "done"
        _write_log(store, entries)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert report.needs_review == []

    def test_task_with_events_but_no_status_events_is_not_a_candidate(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        entries = [
            e
            for e in _read_log(store)
            if not (e.get("item_id") == task_id and "status" in (e.get("changes") or {}))
        ]
        assert entries  # the create event survives
        _write_log(store, entries)
        assert find_archived_as_done(store).candidates == []

    def test_last_status_event_disagreeing_with_the_file_is_not_migrated(self, store):
        """Log says the task ended at todo, the file says done: do not guess."""
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        _status_entries(entries, task_id)[-1]["changes"]["status"]["after"] = "todo"
        _write_log(store, entries)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert report.needs_review == []

    def test_a_dedicated_archive_event_counts_as_a_signal(self, store):
        """``EventType.archive`` exists but nothing emits it — yet."""
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        for entry in _status_entries(entries, task_id):
            entry["event_type"] = "archive"
        _write_log(store, entries)

        (candidate,) = find_archived_as_done(store).candidates
        assert (candidate.task_id, candidate.prior_status) == (task_id, "todo")

    def test_a_bare_archived_value_is_read_as_a_signal(self, store):
        """Not every historical row records a before/after diff."""
        task_id = _dropped_archive_flag(store, _new_task(store))
        entries = _read_log(store)
        for entry in _archive_entries(entries, task_id):
            entry["changes"]["archived"] = True
        _write_log(store, entries)

        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_read_activity_log_returns_empty_for_an_absent_file(self, tmp_path):
        assert read_activity_log(tmp_path) == []


# ─── the false-positive boundary ──────────────────────────────────────


class TestFalsePositiveBoundary:
    """Adversarial shapes that must never be rewritten.

    Demoting a genuinely finished task destroys the record of delivered
    work; failing to migrate an abandoned one is a cosmetic metrics bug.
    Everything here is biased towards leaving files alone.
    """

    def test_completion_bundled_with_a_points_change_is_not_migrated(self, store):
        task_id = _new_task(store)
        store.update(task_id, status="done", points=5)
        assert find_archived_as_done(store).candidates == []

    def test_completion_bundled_with_a_body_edit_is_not_migrated(self, store):
        task_id = _new_task(store)
        store.update(task_id, status="done", body="Finished — see the PR.")
        assert find_archived_as_done(store).candidates == []

    def test_a_bundled_completion_survives_an_applied_run_untouched(self, store):
        task_id = _new_task(store)
        store.update(task_id, status="done", assignee="ryan")
        _cache.clear()
        path = store.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert path.read_bytes() == before

    def test_the_audit_pass_shape_is_never_written(self, store):
        """US-PRJ-29-2..-5: stale placeholders closed straight from todo.

        These were live candidates under the rejected rule, and ``--apply``
        would have un-completed all four.
        """
        closed = []
        for n in range(4):
            task_id = _new_task(store, f"AC placeholder {n}")
            store.update(
                task_id,
                status="done",
                outcome="success",
                note="Closed during audit: AC placeholder task",
            )
            closed.append(task_id)
        _cache.clear()
        before = _snapshot(store.tasks_dir)

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert {s.task_id for s in report.needs_review} == set(closed)
        assert _snapshot(store.tasks_dir) == before

    def test_reopened_to_blocked_then_completed_again_is_skipped(self, store):
        task_id = _dropped_archive_flag(store, _new_task(store))
        store.update(task_id, status="blocked")
        store.update(task_id, status="done")

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.skipped] == [task_id]
        assert "after the archive" in report.skipped[0].reason

        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_a_reopen_buried_in_older_history_still_blocks_the_migration(self, store):
        """The guard looks at everything after the archive, not the last event."""
        task_id = _dropped_archive_flag(store, _new_task(store))
        for status in ("todo", "in-progress", "todo", "done"):
            store.update(task_id, status=status)

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.skipped] == [task_id]

    def test_archived_then_unarchived_then_genuinely_finished(self, store):
        task_id = _new_task(store)
        store.update(task_id, status="in-progress")
        store.archive(task_id)
        store.unarchive(task_id)
        store.update(task_id, status="done")

        assert find_archived_as_done(store).candidates == []
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_legacy_footprint_followed_by_an_explicit_unarchive_is_left_alone(
        self, store
    ):
        """Once the flag has been written and cleared, the state is deliberate."""
        task_id = _legacy_archive(store, _new_task(store), strip_field=False)
        store.archive(task_id)
        store.unarchive(task_id)
        assert find_archived_as_done(store).candidates == []

    def test_only_the_archived_file_changes_when_histories_interleave(self, store):
        archived = _new_task(store, "Abandoned")
        genuine = _new_task(store, "Real")
        store.update(genuine, status="in-progress")
        _dropped_archive_flag(store, archived)
        store.update(genuine, status="done")

        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        after = _snapshot(store.tasks_dir)

        assert report.migrated == [archived]
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {f"{archived}.md"}

    def test_a_realistic_mix_changes_exactly_the_abandoned_tasks(self, store):
        genuine = list(_complete_every_way(store).values())
        single_write = _legacy_archive(store, _new_task(store, "Closed in one write"))
        abandoned = [
            _dropped_archive_flag(store, _new_task(store, "Dropped")),
            _dropped_archive_flag(
                store, _new_task(store, "Stalled"), prior_status="blocked"
            ),
        ]
        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        after = _snapshot(store.tasks_dir)

        assert sorted(report.migrated) == sorted(abandoned)
        assert {k for k in before if before[k] != after[k]} == {
            f"{t}.md" for t in abandoned
        }
        for task_id in [*genuine, single_write]:
            meta = _task_meta(store, task_id)
            assert (meta.status.value, meta.archived) == ("done", False)

    def test_done_task_predating_the_activity_log_is_never_touched(self, store):
        _dropped_archive_flag(store, _new_task(store))
        _log_path(store).write_text("")
        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert _snapshot(store.tasks_dir) == before


# ─── the invariant, swept across every signal-less shape ──────────────


class TestNoSignalNeverLeavesDone:
    """US-PM-17's invariant over the whole apply surface, in one sweep.

    The classes above pin one history each.  This one builds a project
    holding a done task of *every* shape that carries no positive archive
    signal, runs a single ``apply=True``, and asserts that not one of them
    moved out of ``done`` — in fact that not one byte was written.  A new
    signal-less shape has to survive here too, not just in a test of its own.
    """

    def _no_signal_shapes(self, store) -> dict[str, str]:
        """One ``done`` task per signal-less shape, keyed by what it is."""
        shapes: dict[str, str] = {}

        shapes["single write from todo"] = _legacy_archive(
            store, _new_task(store, "Single write")
        )
        shapes["single write from blocked"] = _legacy_archive(
            store, _new_task(store, "From blocked"), from_status="blocked"
        )
        # Genuine completion, every path the suite knows about — including
        # the single-write closes, whose files keep ``archived: false`` where
        # the two ``_legacy_archive`` shapes above have lost the key entirely.
        for path, task_id in _complete_every_way(store, "Genuine").items():
            shapes[f"genuine completion, {path}"] = task_id

        review = _new_task(store, "Review")
        store.update(review, status="review")
        store.update(review, status="done")
        shapes["routed through review"] = review

        long_history = _new_task(store, "Long history")
        for status in ("in-progress", "review", "in-progress", "done"):
            store.update(long_history, status=status)
        shapes["long mixed history"] = long_history

        bundled = _new_task(store, "Bundled")
        store.update(bundled, status="done", assignee="ryan", points=5)
        shapes["closed alongside other fields"] = bundled

        unarchived = _new_task(store, "Unarchived")
        store.update(unarchived, status="done")
        store.archive(unarchived)
        store.unarchive(unarchived)
        _set_archived_field(store, unarchived, None)
        shapes["signal cleared by a later unarchive"] = unarchived

        resurrected = _legacy_archive(store, _new_task(store, "Resurrected"))
        store.update(resurrected, status="in-progress")
        store.update(resurrected, status="done")
        shapes["old footprint, then picked back up"] = resurrected

        # Shapes the store cannot produce: a file whose history was edited
        # away, a log that disagrees with the file, a pre-diff log row.
        hand_edited = _legacy_archive(store, _new_task(store, "Hand edited"))
        disagreeing = _legacy_archive(store, _new_task(store, "Disagreeing log"))
        bare_value = _legacy_archive(store, _new_task(store, "Bare value"))
        entries = [
            e
            for e in _read_log(store)
            if not (
                e.get("item_id") == hand_edited
                and "status" in (e.get("changes") or {})
            )
        ]
        _status_entries(entries, disagreeing)[-1]["changes"]["status"]["after"] = "todo"
        for entry in _status_entries(entries, bare_value):
            entry["changes"]["status"] = "done"
        _write_log(store, entries)
        shapes["hand-edited file with no status events"] = hand_edited
        shapes["log disagrees with the file"] = disagreeing
        shapes["status logged as a bare value"] = bare_value

        _cache.clear()
        return shapes

    def test_not_one_signal_less_shape_leaves_done(self, store):
        shapes = self._no_signal_shapes(store)
        migrate_archived_as_done(store, apply=True)
        moved = {
            name: _task_meta(store, task_id).status.value
            for name, task_id in shapes.items()
            if _task_meta(store, task_id).status.value != "done"
        }
        assert moved == {}

    def test_not_one_signal_less_shape_is_flagged_archived(self, store):
        """The flag is the other half of a write, and it is not licensed either."""
        shapes = self._no_signal_shapes(store)
        migrate_archived_as_done(store, apply=True)
        flagged = {
            name for name, t in shapes.items() if _task_meta(store, t).archived
        }
        assert flagged == set()

    def test_a_signal_less_project_is_left_byte_identical(self, store):
        shapes = self._no_signal_shapes(store)
        before = _snapshot(store.project_dir)

        report = migrate_archived_as_done(store, apply=True)

        assert report.migrated == []
        assert report.examined == len(shapes)
        assert _snapshot(store.project_dir) == before

    def test_the_sweep_is_not_vacuous(self, store):
        """A signal in the same project *is* repaired — the flag, and only it.

        Without this the assertions above would pass on a migration that
        never wrote anything at all.  It also pins the other half of the
        invariant: a signal whose event recorded no status change sets
        ``archived`` and leaves ``done`` exactly where it was.
        """
        shapes = self._no_signal_shapes(store)
        repairable = _dropped_archive_flag(store, _new_task(store, "Lost flag"))
        _cache.clear()
        before = _snapshot(store.tasks_dir)

        report = migrate_archived_as_done(store, apply=True)
        after = _snapshot(store.tasks_dir)

        assert report.migrated == [repairable]
        assert {k for k in before if before[k] != after[k]} == {f"{repairable}.md"}
        meta = _task_meta(store, repairable)
        assert (meta.status.value, meta.archived) == ("done", True)
        assert all(
            _task_meta(store, t).status.value == "done" for t in shapes.values()
        )

    def test_an_unarchive_cleared_signal_survives_an_applied_run(self, store):
        """Archived, unarchived, then the flag lost from disk: still no signal.

        The last explicit write to ``archived`` was ``false``, so the
        un-flagged file is the intended state — there is nothing to repair
        and nothing to move.
        """
        task_id = _new_task(store)
        store.update(task_id, status="done")
        store.archive(task_id)
        store.unarchive(task_id)
        _set_archived_field(store, task_id, None)
        path = store.tasks_dir / f"{task_id}.md"
        before = path.read_bytes()

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert path.read_bytes() == before
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)


# ─── safety properties, as tests rather than prose ────────────────────


class TestSafetyProperties:
    def test_cli_report_run_leaves_the_whole_tree_byte_identical(
        self, store, monkeypatch, complete
    ):
        """Not just the task files — no index rebuild, no log entry, nothing."""
        _dropped_archive_flag(store, _new_task(store))
        complete(store, _new_task(store, "Real"))
        monkeypatch.chdir(store.project_dir.parent)
        _cache.clear()

        from click.testing import CliRunner

        from projectman.cli import cli

        before = _snapshot(store.project_dir)
        result = CliRunner().invoke(cli, ["migrate-archived"])
        assert result.exit_code == 0, result.output
        assert _snapshot(store.project_dir) == before

    def test_a_second_applied_run_leaves_the_whole_tree_byte_identical(
        self, store, complete
    ):
        _dropped_archive_flag(store, _new_task(store))
        complete(store, _new_task(store, "Real"))
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        before = _snapshot(store.project_dir)

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert _snapshot(store.project_dir) == before

    def _boom_on(self, store, monkeypatch, task_id):
        """Fail inside ``Store.update``, after it has read but before it writes."""
        import projectman.store as store_module

        real_dumps = store_module.frontmatter.dumps

        def dumps(post, *args, **kwargs):
            if post.metadata.get("id") == task_id:
                raise RuntimeError("disk on fire")
            return real_dumps(post, *args, **kwargs)

        monkeypatch.setattr(store_module.frontmatter, "dumps", dumps)

    def test_a_failure_does_not_stop_the_other_tasks(self, store, monkeypatch):
        first = _dropped_archive_flag(store, _new_task(store, "One"))
        second = _dropped_archive_flag(store, _new_task(store, "Two"))
        self._boom_on(store, monkeypatch, second)

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == [first]
        assert [e.split(":")[0] for e in report.errors] == [second]

    def test_a_failed_task_file_is_left_byte_identical(self, store, monkeypatch):
        """No half-written frontmatter: the file is whole or it is unchanged."""
        _dropped_archive_flag(store, _new_task(store, "One"))
        second = _dropped_archive_flag(store, _new_task(store, "Two"))
        path = store.tasks_dir / f"{second}.md"
        before = path.read_bytes()

        self._boom_on(store, monkeypatch, second)
        migrate_archived_as_done(store, apply=True)

        assert path.read_bytes() == before
        _cache.clear()
        meta, _ = store.get_task(second)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_a_failure_is_reported(self, store, monkeypatch):
        second = _dropped_archive_flag(store, _new_task(store, "Two"))
        self._boom_on(store, monkeypatch, second)
        text = format_report(migrate_archived_as_done(store, apply=True))
        assert "errors:" in text
        assert second in text

    def test_a_failed_task_is_still_migratable_on_a_later_run(self, store, monkeypatch):
        task_id = _dropped_archive_flag(store, _new_task(store))
        self._boom_on(store, monkeypatch, task_id)
        assert migrate_archived_as_done(store, apply=True).migrated == []

        monkeypatch.undo()
        _cache.clear()
        assert migrate_archived_as_done(store, apply=True).migrated == [task_id]
        assert _task_meta(store, task_id).archived is True


# ─── fidelity of the rewrite ──────────────────────────────────────────


RICH_BODY = """Investigate the parser.

```python
def parse(text: str) -> dict:
    return {"café": "→ ✓"}
```

- [ ] read the spec
- [x] reproduce it

> A quote with trailing spaces.
"""


class TestRewriteFidelity:
    """Only status and archived may move. Everything else is a record."""

    def _archived_task_with_content(self, store):
        task_id = _new_task(
            store, "Rich", body=RICH_BODY, points=3, tags=["parser", "bug"]
        )
        store.update(task_id, assignee="ryan")
        _dropped_archive_flag(store, task_id, prior_status="blocked")
        return task_id

    def test_body_is_preserved_byte_for_byte(self, store):
        task_id = self._archived_task_with_content(store)
        path = store.tasks_dir / f"{task_id}.md"
        before = frontmatter.load(str(path)).content

        migrate_archived_as_done(store, apply=True)
        assert frontmatter.load(str(path)).content == before

    def test_unrelated_frontmatter_is_preserved(self, store):
        task_id = self._archived_task_with_content(store)
        path = store.tasks_dir / f"{task_id}.md"
        before = dict(frontmatter.load(str(path)).metadata)

        migrate_archived_as_done(store, apply=True)
        after = dict(frontmatter.load(str(path)).metadata)

        moved = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        assert moved <= {"status", "archived", "updated"}
        for key in ("id", "story_id", "title", "points", "tags", "assignee", "created"):
            assert after[key] == before[key], key
        assert (after["status"], after["archived"]) == ("blocked", True)

    def test_the_file_still_parses_as_a_task(self, store):
        task_id = self._archived_task_with_content(store)
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        meta, body = store.get_task(task_id)
        assert meta.id == task_id
        assert meta.points == 3
        assert "café" in body

    def test_completion_percentage_falls_after_the_migration(self, store, complete):
        """The reason the migration exists: abandoned work stops counting.

        The genuinely finished task has to keep counting on *every* completion
        path — a demotion here is the bug pointed at the metrics.
        """
        from projectman.indexer import build_index

        genuine = _new_task(store, "Real", points=3)
        _new_task(store, "Open", points=3)
        abandoned = _new_task(store, "Abandoned", points=3)
        complete(store, genuine)
        _dropped_archive_flag(store, abandoned)

        _cache.clear()
        before = build_index(store)
        assert (before.completed_points, before.total_points) == (6, 9)
        assert round(before.completed_points / before.total_points * 100) == 67

        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        after = build_index(store)
        assert (after.completed_points, after.total_points) == (3, 6)
        assert round(after.completed_points / after.total_points * 100) == 50

    def test_index_yaml_points_reflect_the_correction(self, store, complete):
        import yaml

        genuine = _new_task(store, "Real", points=3)
        abandoned = _new_task(store, "Abandoned", points=3)
        complete(store, genuine)
        _dropped_archive_flag(store, abandoned)

        migrate_archived_as_done(store, apply=True)
        index = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        assert index["total_points"] == 3
        assert index["completed_points"] == 3


# ─── the docstring, pinned to the code it describes ───────────────────


class TestTheDocstringMatchesTheCode:
    """US-PM-17-4 — every factual claim the module docstring makes, mechanically.

    The bug this story exists to fix was a *docstring*: it asserted "skip
    rather than write" over code that wrote on evidence unable to support it.
    Prose does not stay true on its own, so the claims that can be checked by
    machine are checked here — the names and commands it cites, the safety
    stance it takes, and the absence of any promise about behaviour that has
    not shipped.  The safety invariant itself is pinned behaviourally by
    ``TestNoSignalNeverLeavesDone`` above; this class pins the *text*.
    """

    SRC = Path(migrations.__file__).resolve().parent

    def _docstring(self) -> str:
        assert migrations.__doc__, "the module docstring has gone missing"
        return migrations.__doc__

    # -- names and commands the text cites ----------------------------

    def test_every_cli_command_it_cites_exists(self):
        """``projectman <cmd>`` in the text has to be a command you can run."""
        from projectman.cli import cli

        cited = set(re.findall(r"projectman ([a-z][a-z-]+)", self._docstring()))
        assert cited, "no CLI command cited — the claim moved, update this test"
        assert cited <= set(cli.commands), (
            f"docstring cites commands that do not exist: "
            f"{sorted(cited - set(cli.commands))}"
        )

    def test_no_cli_subcommand_archives_a_task(self):
        """The text says archiving by hand has no CLI subcommand today."""
        from projectman.cli import cli

        assert "archive" not in cli.commands, (
            "a `projectman archive` command now exists — the docstring's "
            "manual-remedy paragraph says it does not"
        )

    def test_the_python_names_it_cites_resolve(self):
        """``Store.archive``, ``models.is_archived``, ``EventType`` archive."""
        from projectman import models
        from projectman.models import EventType

        assert callable(models.is_archived)
        assert callable(Store.archive)
        assert callable(Store.unarchive)
        assert EventType("archive")

    def test_nothing_emits_the_dedicated_archive_event(self):
        """The text's claim: the value exists in ``EventType``, nothing emits it."""
        emitters = [
            str(path.relative_to(self.SRC))
            for path in sorted(self.SRC.rglob("*.py"))
            if "EventType.archive" in path.read_text(encoding="utf-8")
        ]
        assert emitters == [], (
            f"something now emits EventType.archive ({emitters}); the "
            f"docstring still says nothing does"
        )

    def test_the_migration_is_only_reachable_through_the_cli(self):
        """The text's claim: the CLI command is the only way in, today."""
        importers = [
            str(path.relative_to(self.SRC))
            for path in sorted(self.SRC.rglob("*.py"))
            if path.name != "migrations.py"
            and re.search(r"(from|import)\s+\S*migrations", path.read_text(encoding="utf-8"))
        ]
        assert importers == ["cli.py"], (
            f"the migration module gained callers ({importers}); the docstring "
            f"claims the CLI is the only entry point"
        )

    # -- claims about behaviour ---------------------------------------

    def test_report_is_the_default_at_every_entry_point(self):
        """The text's claim: report is the default at every entry point."""
        from projectman.cli import cli

        assert (
            inspect.signature(migrate_archived_as_done).parameters["apply"].default
            is False
        )
        apply_opt = next(
            p for p in cli.commands["migrate-archived"].params if p.name == "apply_changes"
        )
        assert apply_opt.is_flag and apply_opt.default is False

    def test_store_archive_never_touches_status(self, store):
        """The text's claim about current archive semantics."""
        task_id = _new_task(store, "Abandoned mid-flight")
        store.update(task_id, status="in-progress")

        store.archive(task_id)

        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("in-progress", True)

    def test_the_flag_alone_is_what_the_metrics_consult(self, store):
        """The text's claim: the flag fixes the metrics on its own."""
        from projectman.indexer import build_index

        task_id = _new_task(store, "Abandoned", points=3)
        store.update(task_id, status="done")
        store.archive(task_id)
        _cache.clear()

        meta = _task_meta(store, task_id)
        assert meta.status.value == "done"  # status untouched, flag alone
        index = build_index(store)
        assert (index.total_points, index.completed_points) == (0, 0)

    # -- the stance the text takes -------------------------------------

    def test_pre_signal_archives_are_documented_as_unrecoverable(self):
        """US-PM-17-3 — the class the migration *cannot* repair is named.

        The criterion is "handled or explicitly documented as unrecoverable".
        Handling is pinned above; this pins the documentation, in the module
        docstring and in the shipped CLI reference, remedy included.  A doc
        that quietly drops the caveat reads as a promise the code cannot keep.
        """
        doc = self._docstring()
        assert "unrecoverable by machine" in doc, (
            "the docstring no longer says pre-signal archives cannot be "
            "recovered by machine"
        )
        assert "pm_archive" in doc and "Store.archive" in doc, (
            "the docstring names no manual remedy for the unrecoverable class"
        )

        cli_doc = (
            self.SRC.parents[1] / "docs" / "reference" / "cli.md"
        ).read_text(encoding="utf-8")
        assert "unrecoverable by machine" in cli_doc and "pm_archive" in cli_doc, (
            "docs/reference/cli.md dropped the unrecoverable-archives caveat "
            "or its manual remedy"
        )

    def test_the_invariant_is_still_stated(self):
        assert "never moves a task out of ``done`` on inferred evidence" in (
            self._docstring()
        ), "the headline safety invariant has been edited out of the docstring"

    def test_the_docstring_promises_nothing_unimplemented(self):
        """No "spec ahead of code" escape hatch — that framing *was* the bug.

        US-PM-17-6 wrote the contract before it existed and said so in a
        disclaimer; US-PM-17-7 implemented it.  A docstring that once again
        describes behaviour as intended-but-absent is how the original defect
        looked, so the phrasings that permit it are banned outright.
        """
        forward_looking = re.compile(
            r"(?i:the code is the bug)"
            r"|(?i:this text is the specification)"
            r"|(?i:describes the contract .{0,40}implemented by)"
            r"|(?i:not yet implemented)"
            r"|(?i:once implemented)"
            r"|(?i:will be implemented)"
            # Case-sensitive: the task status ``todo`` is not a code marker.
            r"|\bTODO\b|\bFIXME\b"
        )
        found = forward_looking.findall(self._docstring())
        assert found == [], (
            f"the module docstring describes unshipped behaviour again: {found}"
        )
