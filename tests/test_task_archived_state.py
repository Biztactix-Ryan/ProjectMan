"""Archiving a task must not mark it done (US-PM-16-5).

``Store.archive`` used to dispatch tasks to ``status=done``, because
``TaskStatus`` had no way to say "archived".  Abandoned work was therefore
recorded as delivered work, and nothing downstream could tell the two apart.

Archival is now an ``archived`` boolean that sits *beside* ``status``, so the
status a task actually reached when work stopped survives the archive.  These
tests pin that behaviour, the round-trip through disk, and the back-compat of
task files written before the field existed.
"""

import frontmatter
import pytest
import yaml

from projectman.audit import run_audit
from projectman.deps import incomplete_task_dependencies
from projectman.indexer import build_index, write_index
from projectman.models import TaskFrontmatter, is_archived
from projectman.readiness import check_readiness
from projectman.store import Store, _cache


def _seed_task(store, *, status=None):
    store.create_story("Story", "Desc")
    store.create_task("US-TST-1", "Task", "Desc")
    if status is not None:
        store.update("US-TST-1-1", status=status)
    return "US-TST-1-1"


class TestArchiveDoesNotCompleteTheTask:
    """The headline acceptance criterion: archive must not write ``done``."""

    def test_archive_sets_the_archived_marker(self, store):
        task_id = _seed_task(store)
        store.archive(task_id)
        meta, _ = store.get_task(task_id)
        assert meta.archived is True

    def test_archive_does_not_set_status_done(self, store):
        task_id = _seed_task(store)
        store.archive(task_id)
        meta, _ = store.get_task(task_id)
        assert meta.status.value != "done"
        assert meta.status.value == "todo"

    @pytest.mark.parametrize(
        "status", ["todo", "in-progress", "review", "blocked", "done"]
    )
    def test_archive_preserves_the_last_real_status(self, store, status):
        """Whatever status the task reached is the status it keeps.

        This is the whole reason archival is a flag and not a status value:
        the migration in US-PM-16-7 and anyone asking "why was this abandoned?"
        need to see where the work actually stopped.
        """
        task_id = _seed_task(store, status=status)
        store.archive(task_id)
        meta, _ = store.get_task(task_id)
        assert meta.status.value == status
        assert meta.archived is True

    def test_a_genuinely_done_task_stays_distinguishable_from_an_archived_one(
        self, store
    ):
        """done+archived and done+active must not collapse into the same record."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Finished", "Desc")
        store.create_task("US-TST-1", "Abandoned", "Desc")
        store.update("US-TST-1-1", status="done")
        store.update("US-TST-1-2", status="done")
        store.archive("US-TST-1-2")

        finished, _ = store.get_task("US-TST-1-1")
        abandoned, _ = store.get_task("US-TST-1-2")
        assert finished.status.value == "done" and finished.archived is False
        assert abandoned.status.value == "done" and abandoned.archived is True

    def test_unarchive_clears_the_marker_and_leaves_status_alone(self, store):
        task_id = _seed_task(store, status="review")
        store.archive(task_id)
        store.unarchive(task_id)
        meta, _ = store.get_task(task_id)
        assert meta.archived is False
        assert meta.status.value == "review"


class TestArchivedPersistsAndReloads:
    """Round-trip: the marker has to survive the filesystem, not just the cache."""

    def test_archived_is_written_into_task_frontmatter(self, store):
        task_id = _seed_task(store, status="in-progress")
        store.archive(task_id)
        post = frontmatter.load(str(store.tasks_dir / f"{task_id}.md"))
        assert post.metadata["archived"] is True
        assert post.metadata["status"] == "in-progress"

    def test_archived_survives_a_fresh_store_with_a_cold_cache(self, store, tmp_project):
        task_id = _seed_task(store, status="blocked")
        store.archive(task_id)

        _cache.clear()
        reloaded = Store(tmp_project)
        meta, _ = reloaded.get_task(task_id)
        assert meta.archived is True
        assert meta.status.value == "blocked"

    def test_unarchived_tasks_round_trip_as_not_archived(self, store, tmp_project):
        task_id = _seed_task(store)
        _cache.clear()
        meta, _ = Store(tmp_project).get_task(task_id)
        assert meta.archived is False


class TestBackCompatWithFilesLackingTheField:
    """Every task file written before this change omits ``archived``."""

    def test_a_task_file_without_archived_parses(self):
        meta = TaskFrontmatter(
            id="US-TST-1-1",
            story_id="US-TST-1",
            title="Legacy",
            status="todo",
            created="2026-01-01",
            updated="2026-01-01",
        )
        assert meta.archived is False

    def test_a_legacy_file_on_disk_loads_and_lists(self, store, tmp_project):
        """Hand-write a pre-change task file — no ``archived`` key at all."""
        store.create_story("Story", "Desc")
        path = store.tasks_dir / "US-TST-1-9.md"
        path.write_text(
            "---\n"
            "id: US-TST-1-9\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: in-progress\n"
            "points: 3\n"
            "assignee: null\n"
            "tags: []\n"
            "depends_on: []\n"
            "created: 2026-01-01\n"
            "updated: 2026-01-01\n"
            "---\n\nA task file from before archival existed.\n"
        )
        assert "archived" not in path.read_text()

        _cache.clear()
        reloaded = Store(tmp_project)
        meta, _ = reloaded.get_task("US-TST-1-9")
        assert meta.archived is False
        assert meta.status.value == "in-progress"
        assert "US-TST-1-9" in [t.id for t in reloaded.list_tasks()]

    def test_archiving_a_legacy_file_does_not_rewrite_its_status(
        self, store, tmp_project
    ):
        store.create_story("Story", "Desc")
        (store.tasks_dir / "US-TST-1-9.md").write_text(
            "---\n"
            "id: US-TST-1-9\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: review\n"
            "created: 2026-01-01\n"
            "updated: 2026-01-01\n"
            "---\n\nBody.\n"
        )
        _cache.clear()
        reloaded = Store(tmp_project)
        reloaded.archive("US-TST-1-9")
        meta, _ = reloaded.get_task("US-TST-1-9")
        assert meta.archived is True
        assert meta.status.value == "review"


class TestEpicsAndStoriesAreUnchanged:
    """Epics and stories keep their genuine ``archived`` status."""

    def test_story_archive_still_writes_status_archived(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

    def test_epic_archive_still_writes_status_archived(self, store):
        store.create_epic("Epic", "Desc")
        store.archive("EPIC-TST-1")
        meta, _ = store.get_epic("EPIC-TST-1")
        assert meta.status.value == "archived"

    def test_unarchive_rejects_non_tasks(self, store):
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError):
            store.unarchive("US-TST-1")


class TestArchivedIsQueryable:
    """The surface US-PM-16-6 and US-PM-16-7 will build their math on."""

    def test_list_tasks_defaults_to_returning_archived_and_active_alike(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "A", "Desc")
        store.create_task("US-TST-1", "B", "Desc")
        store.archive("US-TST-1-2")
        assert len(store.list_tasks()) == 2

    def test_list_tasks_can_select_only_active_or_only_archived(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "A", "Desc")
        store.create_task("US-TST-1", "B", "Desc")
        store.archive("US-TST-1-2")
        assert [t.id for t in store.list_tasks(archived=False)] == ["US-TST-1-1"]
        assert [t.id for t in store.list_tasks(archived=True)] == ["US-TST-1-2"]

    def test_read_tasks_from_disk_can_select_by_archived(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "A", "Desc")
        store.create_task("US-TST-1", "B", "Desc")
        store.archive("US-TST-1-2")
        active = store._read_tasks_from_disk(archived=False)
        assert [m.id for m, _ in active] == ["US-TST-1-1"]

    def test_is_archived_answers_uniformly_across_item_types(self, store):
        store.create_epic("Epic", "Desc")
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("EPIC-TST-1")
        store.archive("US-TST-1")
        store.archive("US-TST-1-1")
        assert is_archived(store.get_epic("EPIC-TST-1")[0]) is True
        assert is_archived(store.get_story("US-TST-1")[0]) is True
        assert is_archived(store.get_task("US-TST-1-1")[0]) is True

    def test_is_archived_is_false_for_a_genuinely_done_task(self, store):
        task_id = _seed_task(store, status="done")
        assert is_archived(store.get_task(task_id)[0]) is False

    def test_index_entry_carries_archived_for_tasks(self, store):
        task_id = _seed_task(store)
        store.archive(task_id)
        index = build_index(store)
        entry = next(e for e in index.entries if e.id == task_id)
        assert entry.archived is True
        assert entry.status == "todo"

    def test_index_yaml_on_disk_records_archived(self, store):
        task_id = _seed_task(store)
        store.archive(task_id)
        write_index(store)
        data = yaml.safe_load((store.project_dir / "index.yaml").read_text())
        entry = next(e for e in data["entries"] if e["id"] == task_id)
        assert entry["archived"] is True


class TestArchivedTasksAreNotWorkable:
    """Archiving used to remove a task from play by writing ``done``.

    Keeping the real status must not hand an abandoned task back to the queue.
    """

    def test_an_archived_task_is_not_ready_to_grab(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="ready")
        store.create_task(
            "US-TST-1",
            "Task",
            "A description long enough to clear the readiness length gate easily.",
            points=2,
        )
        before = check_readiness(*store.get_task("US-TST-1-1"), store)
        assert before["ready"] is True

        store.archive("US-TST-1-1")
        after = check_readiness(*store.get_task("US-TST-1-1"), store)
        assert after["ready"] is False
        assert any("archived" in b for b in after["blockers"])

    def test_an_archived_dependency_does_not_block_its_dependents_forever(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Dep", "Desc")
        store.create_task("US-TST-1", "Dependent", "Desc")
        store.update("US-TST-1-2", depends_on=["US-TST-1-1"])

        tasks = store.list_tasks()
        dependent = next(t for t in tasks if t.id == "US-TST-1-2")
        assert incomplete_task_dependencies(dependent, tasks, store.list_stories()) == [
            "US-TST-1-1"
        ]

        store.archive("US-TST-1-1")
        tasks = store.list_tasks()
        dependent = next(t for t in tasks if t.id == "US-TST-1-2")
        assert incomplete_task_dependencies(dependent, tasks, store.list_stories()) == []

    def test_an_archived_task_is_not_outstanding_work_for_a_done_story(
        self, store, tmp_project
    ):
        """The audit must not report an abandoned task as a done story's debt."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Abandoned", "Desc")
        store.archive("US-TST-1-1")
        store.update("US-TST-1", status="done")

        report = run_audit(tmp_project)
        assert "is done but has" not in report


class TestArchivedTasksDropOffTheWorkSurfaces:
    """Server surfaces that used to lose archived tasks when archive wrote done."""

    def _project(self, tmp_project, monkeypatch):
        monkeypatch.chdir(tmp_project)
        from projectman.server import _store_cache

        _store_cache.clear()

    def test_pm_board_omits_archived_tasks(self, tmp_project, monkeypatch):
        self._project(tmp_project, monkeypatch)
        from projectman.server import (
            pm_board,
            pm_create_story,
            pm_create_task,
            pm_update,
            pm_archive,
        )

        pm_create_story("Story", "Desc")
        pm_update("US-TST-1", status="active")
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=2)
        pm_update("US-TST-1-1", status="in-progress")
        pm_archive("US-TST-1-1")

        board = yaml.safe_load(pm_board())
        assert board["summary"] == {
            "available": 0,
            "not_ready": 0,
            "in_progress": 0,
            "in_review": 0,
            "blocked": 0,
        }

    def test_pm_active_omits_archived_in_progress_tasks(self, tmp_project, monkeypatch):
        self._project(tmp_project, monkeypatch)
        from projectman.server import (
            pm_active,
            pm_create_story,
            pm_create_task,
            pm_update,
            pm_archive,
        )

        pm_create_story("Story", "Desc")
        pm_update("US-TST-1", status="active")
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=2)
        pm_update("US-TST-1-1", status="in-progress")
        pm_archive("US-TST-1-1")

        data = yaml.safe_load(pm_active())
        assert data["active_tasks"] == []
        assert data["active_tasks_total"] == 0
