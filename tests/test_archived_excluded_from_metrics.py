"""Archived work must not be counted as delivered (US-PM-16-6).

Archiving a task used to write ``status: done``, so abandoned work arrived in
every metric as delivered work.  US-PM-16-5 gave tasks an ``archived`` flag
beside their status; this module pins what the numbers do with it.

The rule these tests encode: an archived item leaves **both** sides of the
math.  It is not delivered, so it must not raise completed points; and it is
not still owed, so it must not sit in the denominator forever making a
burndown demand work nobody intends to do.  A genuinely ``done`` task is
untouched by any of this — that is the control in every test below.
"""

import yaml

from projectman.indexer import build_index
from projectman.store import Store


# ─── Helpers ─────────────────────────────────────────────────────


def _story_with_tasks(store, *points):
    """Create one story with a task per entry in *points*. Returns task IDs."""
    story, _ = store.create_story("Story", "Desc")
    ids = []
    for pts in points:
        task = store.create_task(story.id, f"Task {pts}", "Desc", points=pts)
        ids.append(task.id)
    return story.id, ids


def _mcp(tmp_project, monkeypatch):
    """Point the MCP tool layer at the temp project with a cold cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()


# ─── Completion percentage ───────────────────────────────────────


class TestCompletionPercentageExcludesArchived:
    """``pm_status`` completion is completed points over total points."""

    def test_archived_task_leaves_both_numerator_and_denominator(self, store):
        _, ids = _story_with_tasks(store, 5, 3)
        store.update(ids[0], status="done")
        store.archive(ids[1])

        index = build_index(store)
        assert index.total_points == 5
        assert index.completed_points == 5

    def test_archiving_an_already_done_task_removes_its_credit(self, store):
        """The exact US-PM-1-1 shape: work marked done, then abandoned.

        The task keeps ``status: done`` on disk (that is what archiving a
        finished item looks like), so only the ``archived`` flag can stop it
        being counted as delivery.
        """
        _, ids = _story_with_tasks(store, 5, 3)
        store.update(ids[0], status="done")
        store.update(ids[1], status="done")
        assert build_index(store).completed_points == 8

        store.archive(ids[1])
        index = build_index(store)
        assert index.completed_points == 5
        assert index.total_points == 5

    def test_a_genuinely_done_task_still_counts(self, store):
        _, ids = _story_with_tasks(store, 5, 3)
        store.update(ids[0], status="done")
        store.update(ids[1], status="done")

        index = build_index(store)
        assert index.total_points == 8
        assert index.completed_points == 8

    def test_archiving_every_task_does_not_divide_by_zero(self, store):
        _, ids = _story_with_tasks(store, 5, 3)
        for task_id in ids:
            store.archive(task_id)

        index = build_index(store)
        assert index.total_points == 0
        assert index.completed_points == 0

    def test_unarchiving_restores_the_points(self, store):
        _, ids = _story_with_tasks(store, 5, 3)
        store.archive(ids[1])
        assert build_index(store).total_points == 5

        store.unarchive(ids[1])
        assert build_index(store).total_points == 8

    def test_archived_task_is_still_listed_in_the_index(self, store):
        """Excluded from the math, not erased from the record."""
        _, ids = _story_with_tasks(store, 5, 3)
        store.archive(ids[1])

        index = build_index(store)
        entry = next(e for e in index.entries if e.id == ids[1])
        assert entry.archived is True
        assert index.task_count == 2

    def test_pm_status_completion_ignores_archived_work(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_story,
            pm_create_task,
            pm_status,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=5)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-2")

        result = yaml.safe_load(pm_status())
        assert result["total_points"] == 5
        assert result["completed_points"] == 5
        assert result["completion"] == "100%"

    def test_pm_status_does_not_file_archived_work_under_its_old_status(
        self, tmp_project, monkeypatch
    ):
        """An archived task keeps its last real status; reporting that status
        would claim abandoned work as either done or outstanding."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_story,
            pm_create_task,
            pm_status,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=5)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-1")

        by_status = yaml.safe_load(pm_status())["by_status"]
        assert by_status.get("done", 0) == 0
        assert by_status.get("archived") == 1


# ─── Burndown ────────────────────────────────────────────────────


class TestBurndownExcludesArchived:
    """Remaining points must not include work nobody intends to do."""

    def test_archived_points_are_not_remaining_work(self, tmp_project, monkeypatch):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_burndown,
            pm_create_story,
            pm_create_task,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Outstanding", "A" * 80, points=3)
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=8)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-3")

        result = yaml.safe_load(pm_burndown())
        assert result["total_points"] == 8
        assert result["completed_points"] == 5
        assert result["remaining_points"] == 3

    def test_archived_points_do_not_inflate_completion(
        self, tmp_project, monkeypatch
    ):
        """Archived-as-done is the pre-16-5 shape and the one that lies."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_burndown,
            pm_create_story,
            pm_create_task,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=8)
        pm_create_task("US-TST-1", "Outstanding", "A" * 80, points=2)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-1")

        result = yaml.safe_load(pm_burndown())
        assert result["completed_points"] == 0
        assert result["remaining_points"] == 2
        assert result["completion"] == "0%"

    def test_genuinely_done_work_still_burns_down(self, tmp_project, monkeypatch):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_burndown,
            pm_create_story,
            pm_create_task,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Outstanding", "A" * 80, points=3)
        pm_update("US-TST-1-1", status="done")

        result = yaml.safe_load(pm_burndown())
        assert result["total_points"] == 8
        assert result["completed_points"] == 5
        assert result["remaining_points"] == 3


# ─── Epic rollup ─────────────────────────────────────────────────


class TestEpicRollupExcludesArchived:
    def test_pm_epic_rollup_drops_archived_task_points(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_epic,
            pm_create_story,
            pm_create_task,
            pm_epic,
            pm_update,
        )

        pm_create_epic("Epic", "Desc")
        pm_create_story("Story", "Desc", epic_id="EPIC-TST-1")
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=5)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-2")

        rollup = yaml.safe_load(pm_epic("EPIC-TST-1"))["rollup"]
        assert rollup["total_points"] == 5
        assert rollup["completed_points"] == 5
        assert rollup["completion"] == "100%"


# ─── Sprint velocity ─────────────────────────────────────────────


class TestSprintVelocityCountsOnlyDelivered:
    """``completed_points`` on a closed sprint *is* the velocity number that
    the next sprint gets sized against, so it may only count real delivery."""

    def test_archived_story_does_not_contribute_velocity(self, store):
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")
        assert meta.completed_points == 5

    def test_a_story_archived_after_being_done_stops_counting(self, store):
        """Closing out a sprint after /pm-cleanup ran must not re-credit it."""
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")
        assert meta.completed_points == 5

    def test_genuinely_done_stories_still_produce_velocity(self, store):
        store.create_story("A", "Desc", points=5)
        store.create_story("B", "Desc", points=3)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")
        assert meta.completed_points == 8

    def test_a_wholly_abandoned_sprint_reports_zero_velocity(self, store):
        store.create_story("A", "Desc", points=5)
        store.create_story("B", "Desc", points=3)
        store.archive("US-TST-1")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")
        assert meta.completed_points == 0

    def test_pm_update_sprint_completes_with_delivered_points_only(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_sprint,
            pm_create_story,
            pm_update,
            pm_update_sprint,
        )

        pm_create_story("Delivered", "Desc", points=5)
        pm_create_story("Abandoned", "Desc", points=8)
        pm_update("US-TST-1", status="done")
        pm_update("US-TST-2", status="done")
        pm_archive("US-TST-2")
        pm_create_sprint("Sprint 1", planned_stories="US-TST-1,US-TST-2")

        result = yaml.safe_load(
            pm_update_sprint("SPRINT-TST-1", status="completed")
        )
        assert result["updated"]["completed_points"] == 5

    def test_sprint_progress_ratio_ignores_archived_tasks(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_sprint,
            pm_create_story,
            pm_create_task,
            pm_get_sprint,
            pm_update,
        )

        pm_create_story("Story", "Desc", points=5)
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=3)
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=3)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-2")
        pm_create_sprint("Sprint 1", planned_stories="US-TST-1")

        progress = yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))["story_progress"][0]
        assert progress["tasks_total"] == 1
        assert progress["tasks_done"] == 1


# ─── Archived epics and stories ──────────────────────────────────


class TestArchivedStoriesAndEpicsAreAlreadyExcluded:
    """Epics and stories carry ``archived`` as a real status value, and the
    store already keeps them out of the default listings.  Pinned here so the
    exclusion is not quietly lost."""

    def test_archived_story_points_leave_the_completion_math(self, store):
        store.create_story("Kept", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.archive("US-TST-2")

        index = build_index(store)
        assert index.total_points == 5
        assert index.completed_points == 5

    def test_build_index_ignores_archived_items_passed_in_explicitly(
        self, store, tmp_project
    ):
        """Callers may hand build_index a pre-loaded list that was read from
        disk rather than through the archived-filtering accessors."""
        store.create_story("Kept", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=8)
        store.archive("US-TST-2")

        fresh = Store(tmp_project)
        stories = [m for m, _ in fresh._read_stories_from_disk()]
        assert len(stories) == 2  # both, including the archived one

        index = build_index(store, stories=stories, tasks=[], epics=[])
        assert index.total_points == 5

    def test_an_archived_task_does_not_block_a_dependent_story_forever(self, store):
        """Sprint views report blocked stories from this; an abandoned task
        would otherwise hold its dependents blocked for good."""
        from projectman.deps import incomplete_story_dependencies

        store.create_story("Provider", "Desc")
        store.create_task("US-TST-1", "Abandoned", "Desc")
        store.create_story("Consumer", "Desc", depends_on=["US-TST-1-1"])
        store.archive("US-TST-1-1")

        consumer, _ = store.get_story("US-TST-2")
        blocked = incomplete_story_dependencies(
            consumer, store.list_tasks(), store.list_stories()
        )
        assert blocked == []

    def test_a_live_task_dependency_still_blocks(self, store):
        from projectman.deps import incomplete_story_dependencies

        store.create_story("Provider", "Desc")
        store.create_task("US-TST-1", "Outstanding", "Desc")
        store.create_story("Consumer", "Desc", depends_on=["US-TST-1-1"])

        consumer, _ = store.get_story("US-TST-2")
        blocked = incomplete_story_dependencies(
            consumer, store.list_tasks(), store.list_stories()
        )
        assert blocked == ["US-TST-1-1"]
