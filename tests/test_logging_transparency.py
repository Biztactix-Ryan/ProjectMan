"""Tests: Logging does not break existing functionality (transparent).

Acceptance criterion for US-PRJ-18: activity logging must be completely
transparent — Store mutation methods return the same values, persist the
same data, and succeed even when logging itself fails.
"""

import json
from unittest.mock import patch

import pytest

from projectman.store import Store


def _read_log(store: Store) -> list[dict]:
    log_path = store.project_dir / "activity.jsonl"
    if not log_path.exists():
        return []
    lines = log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ── Return value integrity ────────────────────────────────────────────


class TestCreateReturnValues:
    """All create methods return correct values with logging active."""

    def test_create_story_returns_meta_and_test_tasks(self, store):
        meta, test_tasks = store.create_story("Story", "Desc")
        assert meta.id == "US-TST-1"
        assert meta.title == "Story"
        assert meta.status.value == "backlog"
        assert test_tasks == []

    def test_create_story_with_ac_returns_test_tasks(self, store):
        meta, test_tasks = store.create_story(
            "Story", "Desc",
            acceptance_criteria=["Users can log in", "Errors handled"],
        )
        assert meta.id == "US-TST-1"
        assert len(test_tasks) == 2
        assert test_tasks[0].story_id == "US-TST-1"
        assert test_tasks[1].story_id == "US-TST-1"

    def test_create_task_returns_task_meta(self, store):
        store.create_story("Story", "Desc")
        task = store.create_task("US-TST-1", "Task", "Desc")
        assert task.id == "US-TST-1-1"
        assert task.story_id == "US-TST-1"
        assert task.title == "Task"
        assert task.status.value == "todo"

    def test_create_tasks_returns_list_of_metas(self, store):
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "Da"},
            {"title": "B", "description": "Db"},
        ])
        assert len(results) == 2
        assert results[0].id == "US-TST-1-1"
        assert results[1].id == "US-TST-1-2"

    def test_create_epic_returns_epic_meta(self, store):
        epic = store.create_epic("Epic", "Desc")
        assert epic.id == "EPIC-TST-1"
        assert epic.title == "Epic"
        assert epic.status.value == "draft"

    def test_create_changeset_returns_changeset_meta(self, store):
        cs = store.create_changeset("Deploy v1", ["api", "web"])
        assert cs.id.startswith("CS-TST-")
        assert cs.title == "Deploy v1"


class TestUpdateReturnValues:
    """update() returns correct updated metadata with logging active."""

    def test_update_story_returns_updated_meta(self, store):
        store.create_story("Story", "Desc")
        meta = store.update("US-TST-1", status="active", title="Renamed")
        assert meta.status.value == "active"
        assert meta.title == "Renamed"

    def test_update_task_returns_updated_meta(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        meta = store.update("US-TST-1-1", status="in-progress", assignee="alice")
        assert meta.status.value == "in-progress"
        assert meta.assignee == "alice"

    def test_update_epic_returns_updated_meta(self, store):
        store.create_epic("Epic", "Desc")
        meta = store.update("EPIC-TST-1", status="active")
        assert meta.status.value == "active"


# ── Data persistence after logging ────────────────────────────────────


class TestDataPersistence:
    """Items written to disk are intact and not corrupted by logging."""

    def test_story_persists_correctly(self, store):
        store.create_story("My Story", "Body text", priority="must", points=5)
        meta, body = store.get_story("US-TST-1")
        assert meta.title == "My Story"
        assert meta.priority.value == "must"
        assert meta.points == 5
        assert "Body text" in body

    def test_task_persists_correctly(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Task body", points=3)
        meta, body = store.get_task("US-TST-1-1")
        assert meta.title == "Task"
        assert meta.points == 3
        assert "Task body" in body

    def test_epic_persists_correctly(self, store):
        store.create_epic("Epic", "Epic body", priority="must")
        meta, body = store.get_epic("EPIC-TST-1")
        assert meta.title == "Epic"
        assert meta.priority.value == "must"
        assert "Epic body" in body

    def test_update_persists_correctly(self, store):
        store.create_story("Story", "Original body")
        store.update("US-TST-1", body="New body", status="active")
        meta, body = store.get_story("US-TST-1")
        assert meta.status.value == "active"
        assert body == "New body"

    def test_archive_persists_correctly(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

    def test_archive_task_persists_correctly(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.status.value == "done"


# ── Logging does not affect item files ────────────────────────────────


class TestNoSideEffects:
    """Logging writes only to activity.jsonl, never to item files."""

    def test_activity_log_is_separate_from_story_file(self, store):
        store.create_story("Story", "Desc")
        story_path = store.stories_dir / "US-TST-1.md"
        content = story_path.read_text()
        assert "activity" not in content.lower()
        assert "log_entry" not in content.lower()

    def test_activity_log_is_separate_from_task_file(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        task_path = store.tasks_dir / "US-TST-1-1.md"
        content = task_path.read_text()
        assert "activity" not in content.lower()
        assert "log_entry" not in content.lower()

    def test_sequential_ids_unaffected_by_logging(self, store):
        """ID generation is deterministic regardless of logging."""
        s1, _ = store.create_story("First", "Desc")
        s2, _ = store.create_story("Second", "Desc")
        assert s1.id == "US-TST-1"
        assert s2.id == "US-TST-2"

        store.create_task("US-TST-1", "T1", "D")
        store.create_task("US-TST-1", "T2", "D")
        tasks = store.list_tasks(story_id="US-TST-1")
        ids = [t.id for t in tasks]
        assert "US-TST-1-1" in ids
        assert "US-TST-1-2" in ids


# ── Failure resilience: logging errors must not propagate ─────────────


class TestLoggingFailureResilience:
    """When the log writer fails, Store operations must still succeed.

    We patch the underlying append_log_entry writer (the real failure
    point — e.g. disk full, permission denied) rather than _emit_log
    itself, because _emit_log contains the try/except that swallows
    errors. This tests the actual resilience path.
    """

    _PATCH_TARGET = "projectman.activity_log.append_log_entry"

    def test_create_story_succeeds_when_logging_fails(self, store):
        with patch(self._PATCH_TARGET, side_effect=OSError("disk full")):
            meta, test_tasks = store.create_story("Story", "Desc")
        assert meta.id == "US-TST-1"
        assert meta.title == "Story"
        meta2, _ = store.get_story("US-TST-1")
        assert meta2.title == "Story"

    def test_create_task_succeeds_when_logging_fails(self, store):
        store.create_story("Story", "Desc")
        with patch(self._PATCH_TARGET, side_effect=RuntimeError("log broken")):
            task = store.create_task("US-TST-1", "Task", "Desc")
        assert task.id == "US-TST-1-1"
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.title == "Task"

    def test_create_tasks_succeeds_when_logging_fails(self, store):
        store.create_story("Story", "Desc")
        with patch(self._PATCH_TARGET, side_effect=OSError("nope")):
            results = store.create_tasks("US-TST-1", [
                {"title": "A", "description": "Da"},
                {"title": "B", "description": "Db"},
            ])
        assert len(results) == 2
        assert results[0].id == "US-TST-1-1"

    def test_create_epic_succeeds_when_logging_fails(self, store):
        with patch(self._PATCH_TARGET, side_effect=Exception("boom")):
            epic = store.create_epic("Epic", "Desc")
        assert epic.id == "EPIC-TST-1"
        meta, _ = store.get_epic("EPIC-TST-1")
        assert meta.title == "Epic"

    def test_update_succeeds_when_logging_fails(self, store):
        store.create_story("Story", "Desc")
        with patch(self._PATCH_TARGET, side_effect=OSError("disk full")):
            meta = store.update("US-TST-1", status="active")
        assert meta.status.value == "active"
        meta2, _ = store.get_story("US-TST-1")
        assert meta2.status.value == "active"

    def test_archive_succeeds_when_logging_fails(self, store):
        store.create_story("Story", "Desc")
        with patch(self._PATCH_TARGET, side_effect=RuntimeError("broken")):
            store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

    def test_create_changeset_succeeds_when_logging_fails(self, store):
        with patch(self._PATCH_TARGET, side_effect=Exception("nope")):
            cs = store.create_changeset("Deploy", ["api"])
        assert cs.id.startswith("CS-TST-")
        assert cs.title == "Deploy"

    def test_no_activity_log_written_when_writer_fails(self, store):
        """When the writer raises, no log file should be created."""
        with patch(self._PATCH_TARGET, side_effect=OSError("fail")):
            store.create_story("Story", "Desc")
        entries = _read_log(store)
        assert len(entries) == 0


# ── Full workflow: combined operations stay consistent ─────────────────


class TestFullWorkflowTransparency:
    """A complete create → update → archive workflow works with logging."""

    def test_story_lifecycle(self, store):
        meta, _ = store.create_story("Story", "Desc", points=3)
        assert meta.id == "US-TST-1"

        meta = store.update("US-TST-1", status="active")
        assert meta.status.value == "active"

        meta = store.update("US-TST-1", title="Renamed Story", points=5)
        assert meta.title == "Renamed Story"
        assert meta.points == 5

        store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

        # Log entries emitted at each step, but none interfere
        entries = _read_log(store)
        assert len(entries) >= 4  # create + update + update + archive

    def test_task_lifecycle(self, store):
        store.create_story("Story", "Desc")
        task = store.create_task("US-TST-1", "Task", "Desc")
        assert task.id == "US-TST-1-1"

        meta = store.update("US-TST-1-1", status="in-progress", assignee="alice")
        assert meta.status.value == "in-progress"

        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.status.value == "done"

    def test_mixed_operations_do_not_interfere(self, store):
        """Creating stories, tasks, and epics in sequence all work."""
        s1, _ = store.create_story("Story 1", "D1")
        s2, _ = store.create_story("Story 2", "D2")
        e1 = store.create_epic("Epic", "ED")
        store.create_task("US-TST-1", "Task A", "DA")
        store.create_task("US-TST-2", "Task B", "DB")

        # All items readable
        store.get_story("US-TST-1")
        store.get_story("US-TST-2")
        store.get_epic(e1.id)
        store.get_task("US-TST-1-1")
        store.get_task("US-TST-2-1")

        # Lists work
        assert len(store.list_stories()) == 2
        assert len(store.list_tasks(story_id="US-TST-1")) == 1
        assert len(store.list_tasks(story_id="US-TST-2")) == 1
