"""Migrating tasks archived under the old archive-as-done behaviour (US-PM-16-7).

Before US-PM-16, ``Store.archive`` on a task ran ``update(task_id,
status="done")``.  Every task archived that way is still on disk claiming to be
delivered work.  ``projectman.migrations`` recovers them from the activity log
and restores the status they really held.

These tests pin the identification rules, the false-positive guards (a task
that was re-opened and then genuinely finished must survive untouched), the
dry-run default, idempotency, and the real ``.project/`` data of this repo —
against a *copy*, never the live directory.
"""

import json
import shutil
from pathlib import Path

import frontmatter
import pytest

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


def _legacy_archive(store, task_id, *, from_status=None, strip_field=True):
    """Reproduce the pre-US-PM-16 archive: update(status="done"), nothing else.

    ``strip_field`` also removes the ``archived`` key from the file, so the
    task looks exactly like one written before the field existed.
    """
    if from_status is not None:
        store.update(task_id, status=from_status)
    store.update(task_id, status="done")
    if strip_field:
        path = store.tasks_dir / f"{task_id}.md"
        post = frontmatter.load(str(path))
        post.metadata.pop("archived", None)
        path.write_text(frontmatter.dumps(post))
        _cache.clear()
    return task_id


def _genuinely_complete(store, task_id):
    """The normal workflow: pick the task up, then finish it."""
    store.update(task_id, status="in-progress")
    store.update(task_id, status="done")
    return task_id


def _task_meta(store, task_id):
    _cache.clear()
    meta, _ = store.get_task(task_id)
    return meta


def _snapshot(project_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(project_dir)): p.read_text()
        for p in sorted(project_dir.rglob("*"))
        if p.is_file()
    }


# ─── identification ───────────────────────────────────────────────────


class TestIdentification:
    """The migration finds tasks archived under the old behaviour."""

    def test_finds_legacy_archived_task(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [task_id]

    def test_records_the_status_from_before_the_archive(self, store):
        task_id = _legacy_archive(store, _make_task(store), from_status="blocked")
        (candidate,) = find_archived_as_done(store).candidates
        assert candidate.prior_status == "blocked"

    def test_records_when_it_was_archived(self, store):
        _legacy_archive(store, _make_task(store))
        (candidate,) = find_archived_as_done(store).candidates
        assert candidate.archived_at

    def test_finds_task_that_still_carries_archived_false(self, store):
        """Files written after US-PM-16-5 have ``archived: false`` present."""
        task_id = _legacy_archive(store, _make_task(store), strip_field=False)
        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [task_id]

    def test_finds_several_at_once(self, store):
        first = _legacy_archive(store, _make_task(store, "One"))
        second = _legacy_archive(store, _make_task(store, "Two"))
        report = find_archived_as_done(store)
        assert sorted(c.task_id for c in report.candidates) == sorted(
            [first, second]
        )

    def test_reports_nothing_when_the_log_is_missing(self, store):
        _legacy_archive(store, _make_task(store))
        (store.project_dir / "activity.jsonl").unlink()
        assert find_archived_as_done(store).candidates == []

    def test_corrupt_log_lines_are_tolerated(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        log = store.project_dir / "activity.jsonl"
        log.write_text("not json at all\n\n" + log.read_text())
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [
            task_id
        ]


# ─── genuinely done work must be left alone ───────────────────────────


class TestGenuinelyDoneTasksAreUntouched:
    """The migration must never demote real completed work."""

    def test_normal_completion_is_not_a_candidate(self, store):
        _genuinely_complete(store, _make_task(store))
        assert find_archived_as_done(store).candidates == []

    def test_completion_from_review_is_not_a_candidate(self, store):
        task_id = _make_task(store)
        store.update(task_id, status="review")
        store.update(task_id, status="done")
        assert find_archived_as_done(store).candidates == []

    def test_completion_alongside_other_field_changes_is_not_a_candidate(
        self, store
    ):
        """The old archive wrote status and nothing else."""
        task_id = _make_task(store)
        store.update(task_id, status="done", assignee="claude")
        assert find_archived_as_done(store).candidates == []

    def test_genuine_completion_survives_an_applied_run(self, store):
        done_id = _genuinely_complete(store, _make_task(store, "Real"))
        _legacy_archive(store, _make_task(store, "Archived"))
        migrate_archived_as_done(store, apply=True)
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


class TestReopenedThenCompleted:
    """Archived, then re-opened, then genuinely finished: do not migrate.

    The log cannot prove which of the two ``-> done`` transitions was the
    archive, but it does prove work continued afterwards.  Skipping is the
    only safe reading.
    """

    def _reopen_and_finish(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        store.update(task_id, status="in-progress")
        store.update(task_id, status="done")
        return task_id

    def test_not_reported_as_a_candidate(self, store):
        self._reopen_and_finish(store)
        assert find_archived_as_done(store).candidates == []

    def test_reported_as_an_explicit_skip(self, store):
        task_id = self._reopen_and_finish(store)
        report = find_archived_as_done(store)
        assert [s.task_id for s in report.skipped] == [task_id]
        assert "re-opened" in report.skipped[0].reason

    def test_applied_run_leaves_it_done_and_unarchived(self, store):
        task_id = self._reopen_and_finish(store)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "done"
        assert meta.archived is False

    def test_reopened_back_to_todo_is_also_skipped(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        store.update(task_id, status="todo")
        store.update(task_id, status="done")
        assert find_archived_as_done(store).candidates == []


# ─── unknowable prior status ──────────────────────────────────────────


class TestUnknowablePriorStatus:
    """Never invent a status the log does not record."""

    def _log_archive_without_before(self, store, task_id):
        log = store.project_dir / "activity.jsonl"
        entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        for entry in entries:
            if entry["item_id"] == task_id and "status" in (entry.get("changes") or {}):
                entry["changes"]["status"]["before"] = None
        log.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def test_flagged_for_review_not_migrated(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        self._log_archive_without_before(store, task_id)
        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.needs_review] == [task_id]

    def test_left_untouched_by_an_applied_run(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        self._log_archive_without_before(store, task_id)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "done"
        assert meta.archived is False


# ─── dry run ──────────────────────────────────────────────────────────


class TestDryRunIsTheDefault:
    def test_find_writes_nothing(self, store):
        _legacy_archive(store, _make_task(store))
        before = _snapshot(store.project_dir)
        find_archived_as_done(store)
        assert _snapshot(store.project_dir) == before

    def test_migrate_without_apply_writes_nothing(self, store):
        _legacy_archive(store, _make_task(store))
        before = _snapshot(store.project_dir)
        report = migrate_archived_as_done(store)
        assert _snapshot(store.project_dir) == before
        assert report.applied is False
        assert report.migrated == []
        assert report.candidates

    def test_dry_run_appends_no_activity_entries(self, store):
        _legacy_archive(store, _make_task(store))
        before = len(read_activity_log(store.project_dir))
        migrate_archived_as_done(store)
        assert len(read_activity_log(store.project_dir)) == before

    def test_dry_run_report_says_so(self, store):
        _legacy_archive(store, _make_task(store))
        text = format_report(migrate_archived_as_done(store))
        assert "DRY RUN" in text
        assert "--apply" in text


# ─── applying ─────────────────────────────────────────────────────────


class TestApply:
    def test_sets_the_archived_flag(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        assert _task_meta(store, task_id).archived is True

    def test_restores_the_status_from_before_the_archive(self, store):
        task_id = _legacy_archive(store, _make_task(store), from_status="blocked")
        migrate_archived_as_done(store, apply=True)
        assert _task_meta(store, task_id).status.value == "blocked"

    def test_reports_what_it_migrated(self, store):
        task_id = _legacy_archive(store, _make_task(store))
        report = migrate_archived_as_done(store, apply=True)
        assert report.applied is True
        assert report.migrated == [task_id]
        assert report.changed is True

    def test_migrated_task_drops_out_of_completion_metrics(self, store):
        """The whole point: abandoned work stops counting as delivered."""
        task_id = _legacy_archive(store, _make_task(store))
        assert [t.id for t in store.list_tasks(status="done", archived=False)] == [
            task_id
        ]
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        assert store.list_tasks(status="done", archived=False) == []

    def test_index_reflects_the_migration(self, store):
        import yaml

        task_id = _legacy_archive(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        index = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        entry = next(e for e in index["entries"] if e["id"] == task_id)
        assert entry["status"] != "done"
        assert entry["archived"] is True


# ─── idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_second_applied_run_finds_nothing(self, store):
        _legacy_archive(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        second = migrate_archived_as_done(store, apply=True)
        assert second.candidates == []
        assert second.migrated == []

    def test_second_run_does_not_change_the_files(self, store):
        _legacy_archive(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        tasks_before = _snapshot(store.tasks_dir)
        migrate_archived_as_done(store, apply=True)
        assert _snapshot(store.tasks_dir) == tasks_before

    def test_status_is_not_walked_back_twice(self, store):
        task_id = _legacy_archive(store, _make_task(store), from_status="blocked")
        migrate_archived_as_done(store, apply=True)
        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert meta.status.value == "blocked"
        assert meta.archived is True

    def test_dry_run_after_apply_is_clean(self, store):
        _legacy_archive(store, _make_task(store))
        migrate_archived_as_done(store, apply=True)
        report = migrate_archived_as_done(store)
        assert report.candidates == []
        assert "no archived-as-done tasks found" in format_report(report)


# ─── a realistic multi-task project, built deterministically ──────────


class TestAgainstARealisticProject:
    """The identification rules against a project with mixed history.

    This class used to run against a *copy* of this repo's own ``.project/``
    directory and assert set-equality with a hardcoded pair of task ids
    (``US-PM-1-1``, ``US-PM-2-1``).  That coupled a unit test to live project
    data: closing any unrelated task straight from ``todo`` to ``done`` added a
    candidate and broke the equality, which is exactly what happened when a
    ``/pm audit`` pass closed four stale placeholder tasks.  The fixture below
    reproduces the same *shape* of history — several genuinely finished tasks,
    two legacy archives, a re-open, and a blocked-prior archive — without
    depending on data that legitimately changes.
    """

    @pytest.fixture
    def realistic(self, tmp_project):
        _cache.clear()
        store = Store(tmp_project)

        # Genuinely finished work: picked up, then completed.
        self.genuine = [
            _genuinely_complete(store, _make_task(store, f"Real {n}"))
            for n in range(1, 6)
        ]
        # Archived under the old behaviour, from the two never-started statuses.
        self.legacy_todo = _legacy_archive(store, _make_task(store, "Legacy todo"))
        self.legacy_blocked = _legacy_archive(
            store, _make_task(store, "Legacy blocked"), from_status="blocked"
        )
        # Archived, then re-opened and genuinely finished — must be skipped.
        self.reopened = _legacy_archive(store, _make_task(store, "Reopened"))
        store.update(self.reopened, status="in-progress")
        store.update(self.reopened, status="done")
        _cache.clear()
        return store

    LEGACY = property(lambda self: {self.legacy_todo, self.legacy_blocked})

    def test_finds_exactly_the_legacy_archives(self, realistic):
        report = find_archived_as_done(realistic)
        assert {c.task_id for c in report.candidates} == self.LEGACY

    def test_restores_each_to_the_status_it_held(self, realistic):
        report = find_archived_as_done(realistic)
        prior = {c.task_id: c.prior_status for c in report.candidates}
        assert prior[self.legacy_todo] == "todo"
        assert prior[self.legacy_blocked] == "blocked"

    def test_genuinely_done_tasks_are_left_alone(self, realistic):
        report = find_archived_as_done(realistic)
        flagged = {c.task_id for c in report.candidates}
        assert flagged.isdisjoint(self.genuine)
        assert report.examined > len(self.LEGACY)
        assert report.needs_review == []

    def test_reopened_task_is_skipped_not_migrated(self, realistic):
        report = find_archived_as_done(realistic)
        assert self.reopened not in {c.task_id for c in report.candidates}
        assert self.reopened in {s.task_id for s in report.skipped}

    def test_apply_migrates_only_the_legacy_archives(self, realistic):
        done_before = {t.id for t in realistic.list_tasks(status="done")}
        report = migrate_archived_as_done(realistic, apply=True)
        assert set(report.migrated) == self.LEGACY
        _cache.clear()
        done_after = {t.id for t in realistic.list_tasks(status="done")}
        assert done_before - done_after == self.LEGACY

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
    live directory is never written, and every candidate is a shape the
    migration is allowed to act on.
    """

    @pytest.fixture
    def real_copy(self, tmp_path):
        _cache.clear()
        shutil.copytree(REAL_PROJECT, tmp_path / ".project")
        return Store(tmp_path)

    def test_every_candidate_has_a_never_started_prior_status(self, real_copy):
        report = find_archived_as_done(real_copy)
        assert {c.prior_status for c in report.candidates} <= {"todo", "blocked"}

    def test_nothing_needs_review(self, real_copy):
        assert find_archived_as_done(real_copy).needs_review == []

    def test_apply_is_idempotent_on_real_data(self, real_copy):
        migrate_archived_as_done(real_copy, apply=True)
        assert migrate_archived_as_done(real_copy, apply=True).migrated == []

    def test_live_project_directory_is_never_written(self, real_copy):
        """Belt and braces: the copy is what changed, not the repo."""
        before = {
            p.name: p.read_text() for p in (REAL_PROJECT / "tasks").glob("*.md")
        }
        migrate_archived_as_done(real_copy, apply=True)
        after = {p.name: p.read_text() for p in (REAL_PROJECT / "tasks").glob("*.md")}
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
        _legacy_archive(store, _make_task(store))
        _genuinely_complete(store, _make_task(store, "Real"))
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

    def test_genuinely_done_task_untouched_by_the_cli(self, cli_project):
        self._run(["migrate-archived", "--apply"])
        meta = _task_meta(cli_project, "US-TST-1-2")
        assert meta.status.value == "done"
        assert meta.archived is False


# ─── log-shape helpers ────────────────────────────────────────────────


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


def _new_task(store, title="Task", **kwargs):
    """Create the shared story once, then a task, returning its id."""
    if not store.list_stories():
        store.create_story("Story", "Desc")
    return store.create_task("US-TST-1", title, kwargs.pop("body", "Desc"), **kwargs).id


# ─── realistic activity-log shapes ────────────────────────────────────


class TestActivityLogShapes:
    """Identification has to survive the logs real projects actually have.

    Interleaved items, long histories, half-written lines, no log at all —
    none of these may turn into a wrong migration or a traceback.
    """

    def test_interleaved_events_from_another_task_do_not_confuse_it(self, store):
        archived = _new_task(store, "Abandoned")
        genuine = _new_task(store, "Real")
        store.update(archived, status="blocked")
        store.update(genuine, status="in-progress")
        store.update(archived, status="done")  # the legacy archive
        store.update(genuine, status="done")  # genuine completion

        report = find_archived_as_done(store)
        assert [c.task_id for c in report.candidates] == [archived]
        assert report.candidates[0].prior_status == "blocked"

    def test_two_interleaved_archives_are_both_found(self, store):
        first = _new_task(store, "One")
        second = _new_task(store, "Two")
        store.update(first, status="blocked")
        store.update(second, status="done")
        store.update(first, status="done")

        report = find_archived_as_done(store)
        assert {c.task_id: c.prior_status for c in report.candidates} == {
            first: "blocked",
            second: "todo",
        }

    def test_history_before_the_archive_does_not_disqualify_it(self, store):
        """Picked up, put back in the backlog, then archived: still an archive."""
        task_id = _new_task(store)
        store.update(task_id, status="in-progress")
        store.update(task_id, status="todo")
        store.update(task_id, status="done")

        (candidate,) = find_archived_as_done(store).candidates
        assert (candidate.task_id, candidate.prior_status) == (task_id, "todo")

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
        _legacy_archive(store, _new_task(store))
        _log_path(store).write_text("")
        _cache.clear()
        assert read_activity_log(store.project_dir) == []
        assert find_archived_as_done(store).candidates == []

    def test_blank_and_whitespace_only_lines(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        _log_path(store).write_text(
            "\n   \n\n" + _log_path(store).read_text() + "\n  \n"
        )
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_truncated_final_line_is_tolerated(self, store):
        """A log cut off mid-write must not hide the entries before it."""
        task_id = _legacy_archive(store, _new_task(store))
        with _log_path(store).open("a") as fh:
            fh.write('{"event_type": "update", "item_id": "US-TST-1-1", "cha')
        _cache.clear()
        assert [c.task_id for c in find_archived_as_done(store).candidates] == [task_id]

    def test_json_lines_that_are_not_objects_are_ignored(self, store):
        task_id = _legacy_archive(store, _new_task(store))
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

    def test_non_update_event_types_are_ignored(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        entries = _read_log(store)
        for entry in _status_entries(entries, task_id):
            entry["event_type"] = "archive"
        _write_log(store, entries)
        assert find_archived_as_done(store).candidates == []

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
        """todo -> done, but the update carried an estimate too: a real edit."""
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
        before = path.read_text()

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert path.read_text() == before

    def test_reopened_to_blocked_then_completed_again_is_skipped(self, store):
        """The log cannot say which ``-> done`` was the archive, so neither may we."""
        task_id = _legacy_archive(store, _new_task(store))
        store.update(task_id, status="blocked")
        store.update(task_id, status="done")

        report = find_archived_as_done(store)
        assert report.candidates == []
        assert [s.task_id for s in report.skipped] == [task_id]
        assert "re-opened" in report.skipped[0].reason

        migrate_archived_as_done(store, apply=True)
        meta = _task_meta(store, task_id)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_a_reopen_buried_in_older_history_still_blocks_the_migration(self, store):
        """The guard looks at the whole history, not just the last two events."""
        task_id = _legacy_archive(store, _new_task(store))
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

    def test_legacy_archive_followed_by_an_explicit_archive_flag_is_left_alone(
        self, store
    ):
        """Once the honest flag has been written, the log is no longer evidence."""
        task_id = _legacy_archive(store, _new_task(store), strip_field=False)
        store.archive(task_id)
        store.unarchive(task_id)
        assert find_archived_as_done(store).candidates == []

    def test_only_the_archived_file_changes_when_histories_interleave(self, store):
        archived = _new_task(store, "Abandoned")
        genuine = _new_task(store, "Real")
        store.update(genuine, status="in-progress")
        store.update(archived, status="done")
        store.update(genuine, status="done")

        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        after = _snapshot(store.tasks_dir)

        assert report.migrated == [archived]
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {f"{archived}.md"}

    def test_a_realistic_mix_changes_exactly_the_abandoned_tasks(self, store):
        genuine = [
            _genuinely_complete(store, _new_task(store, f"Real {i}")) for i in range(5)
        ]
        abandoned = [
            _legacy_archive(store, _new_task(store, "Dropped")),
            _legacy_archive(store, _new_task(store, "Stalled"), from_status="blocked"),
        ]
        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        after = _snapshot(store.tasks_dir)

        assert sorted(report.migrated) == sorted(abandoned)
        assert {k for k in before if before[k] != after[k]} == {
            f"{t}.md" for t in abandoned
        }
        for task_id in genuine:
            meta = _task_meta(store, task_id)
            assert (meta.status.value, meta.archived) == ("done", False)

    def test_done_task_predating_the_activity_log_is_never_touched(self, store):
        task_id = _legacy_archive(store, _new_task(store))
        _log_path(store).write_text("")
        _cache.clear()
        before = _snapshot(store.tasks_dir)
        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == []
        assert _snapshot(store.tasks_dir) == before


# ─── safety properties, as tests rather than prose ────────────────────


class TestSafetyProperties:
    def test_cli_report_run_leaves_the_whole_tree_byte_identical(self, store, monkeypatch):
        """Not just the task files — no index rebuild, no log entry, nothing."""
        _legacy_archive(store, _new_task(store))
        _genuinely_complete(store, _new_task(store, "Real"))
        monkeypatch.chdir(store.project_dir.parent)
        _cache.clear()

        from click.testing import CliRunner

        from projectman.cli import cli

        before = _snapshot(store.project_dir)
        result = CliRunner().invoke(cli, ["migrate-archived"])
        assert result.exit_code == 0, result.output
        assert _snapshot(store.project_dir) == before

    def test_a_second_applied_run_leaves_the_whole_tree_byte_identical(self, store):
        _legacy_archive(store, _new_task(store))
        _genuinely_complete(store, _new_task(store, "Real"))
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
        first = _legacy_archive(store, _new_task(store, "One"))
        second = _legacy_archive(store, _new_task(store, "Two"))
        self._boom_on(store, monkeypatch, second)

        report = migrate_archived_as_done(store, apply=True)
        assert report.migrated == [first]
        assert [e.split(":")[0] for e in report.errors] == [second]

    def test_a_failed_task_file_is_left_byte_identical(self, store, monkeypatch):
        """No half-written frontmatter: the file is whole or it is unchanged."""
        _legacy_archive(store, _new_task(store, "One"))
        second = _legacy_archive(store, _new_task(store, "Two"))
        path = store.tasks_dir / f"{second}.md"
        before = path.read_text()

        self._boom_on(store, monkeypatch, second)
        migrate_archived_as_done(store, apply=True)

        assert path.read_text() == before
        _cache.clear()
        meta, _ = store.get_task(second)
        assert (meta.status.value, meta.archived) == ("done", False)

    def test_a_failure_is_reported(self, store, monkeypatch):
        second = _legacy_archive(store, _new_task(store, "Two"))
        self._boom_on(store, monkeypatch, second)
        text = format_report(migrate_archived_as_done(store, apply=True))
        assert "errors:" in text
        assert second in text

    def test_a_failed_task_is_still_migratable_on_a_later_run(self, store, monkeypatch):
        task_id = _legacy_archive(store, _new_task(store))
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
        store.update(task_id, assignee="ryan", status="blocked")
        _legacy_archive(store, task_id, strip_field=False)
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

    def test_completion_percentage_falls_after_the_migration(self, store):
        """The reason the migration exists: abandoned work stops counting."""
        from projectman.indexer import build_index

        genuine = _new_task(store, "Real", points=3)
        _new_task(store, "Open", points=3)
        abandoned = _new_task(store, "Abandoned", points=3)
        _genuinely_complete(store, genuine)
        _legacy_archive(store, abandoned)

        _cache.clear()
        before = build_index(store)
        assert (before.completed_points, before.total_points) == (6, 9)
        assert round(before.completed_points / before.total_points * 100) == 67

        migrate_archived_as_done(store, apply=True)
        _cache.clear()
        after = build_index(store)
        assert (after.completed_points, after.total_points) == (3, 6)
        assert round(after.completed_points / after.total_points * 100) == 50

    def test_index_yaml_points_reflect_the_correction(self, store):
        import yaml

        genuine = _new_task(store, "Real", points=3)
        abandoned = _new_task(store, "Abandoned", points=3)
        _genuinely_complete(store, genuine)
        _legacy_archive(store, abandoned)

        migrate_archived_as_done(store, apply=True)
        index = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        assert index["total_points"] == 3
        assert index["completed_points"] == 3
