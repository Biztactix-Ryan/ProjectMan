"""Tests for Store.create_* activity log emissions (US-PRJ-18-1)."""

import json

import pytest

from projectman.store import Store


def _read_log(store: Store) -> list[dict]:
    """Read all log entries from the store's activity log."""
    log_path = store.project_dir / "activity.jsonl"
    if not log_path.exists():
        return []
    lines = log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class TestCreateStoryEmitsLog:
    """create_story must emit a 'create' log entry for the story."""

    def test_create_story_emits_created_entry(self, store):
        store.create_story("My Story", "Description")
        entries = _read_log(store)
        story_entries = [e for e in entries if e["item_id"] == "US-TST-1"]
        assert len(story_entries) >= 1
        assert story_entries[0]["event_type"] == "create"
        assert story_entries[0]["item_type"] == "story"

    def test_create_story_entry_has_correct_item_id(self, store):
        store.create_story("First", "Desc")
        store.create_story("Second", "Desc")
        entries = _read_log(store)
        story_ids = [e["item_id"] for e in entries if e["item_type"] == "story"]
        assert "US-TST-1" in story_ids
        assert "US-TST-2" in story_ids

    def test_create_story_with_acceptance_criteria_also_logs_tasks(self, store):
        """When acceptance criteria auto-create tasks, each task should also be logged."""
        store.create_story(
            "Story", "Desc",
            acceptance_criteria=["Users can log in", "Error on bad password"],
        )
        entries = _read_log(store)
        task_entries = [e for e in entries if e["item_type"] == "task"]
        assert len(task_entries) == 2
        assert all(e["event_type"] == "create" for e in task_entries)


class TestCreateTaskEmitsLog:
    """create_task must emit a 'create' log entry for the task."""

    def test_create_task_emits_created_entry(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Do something")
        entries = _read_log(store)
        task_entries = [e for e in entries if e["item_id"] == "US-TST-1-1"]
        assert len(task_entries) == 1
        assert task_entries[0]["event_type"] == "create"
        assert task_entries[0]["item_type"] == "task"

    def test_create_multiple_tasks_each_logged(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-1", "Task B", "Desc")
        entries = _read_log(store)
        task_entries = [e for e in entries if e["item_type"] == "task"]
        task_ids = [e["item_id"] for e in task_entries]
        assert "US-TST-1-1" in task_ids
        assert "US-TST-1-2" in task_ids


class TestCreateTasksEmitsLog:
    """create_tasks (batch) must emit a 'create' log entry for each task."""

    def test_create_tasks_emits_one_entry_per_task(self, store):
        store.create_story("Story", "Desc")
        store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "Desc A"},
            {"title": "Task B", "description": "Desc B"},
            {"title": "Task C", "description": "Desc C"},
        ])
        entries = _read_log(store)
        task_entries = [e for e in entries if e["item_type"] == "task"]
        assert len(task_entries) == 3
        assert all(e["event_type"] == "create" for e in task_entries)

    def test_create_tasks_logs_correct_ids(self, store):
        store.create_story("Story", "Desc")
        store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "Desc A"},
            {"title": "Task B", "description": "Desc B"},
        ])
        entries = _read_log(store)
        task_ids = [e["item_id"] for e in entries if e["item_type"] == "task"]
        assert "US-TST-1-1" in task_ids
        assert "US-TST-1-2" in task_ids


class TestCreateEpicEmitsLog:
    """create_epic must emit a 'create' log entry for the epic."""

    def test_create_epic_emits_created_entry(self, store):
        store.create_epic("My Epic", "Epic description")
        entries = _read_log(store)
        epic_entries = [e for e in entries if e["item_type"] == "epic"]
        assert len(epic_entries) == 1
        assert epic_entries[0]["event_type"] == "create"
        assert epic_entries[0]["item_id"].startswith("EPIC-TST-")

    def test_create_multiple_epics_each_logged(self, store):
        store.create_epic("Epic 1", "Desc")
        store.create_epic("Epic 2", "Desc")
        entries = _read_log(store)
        epic_entries = [e for e in entries if e["item_type"] == "epic"]
        assert len(epic_entries) == 2
        epic_ids = [e["item_id"] for e in epic_entries]
        assert "EPIC-TST-1" in epic_ids
        assert "EPIC-TST-2" in epic_ids


class TestCreateChangesetEmitsLog:
    """create_changeset must emit a 'create' log entry for the changeset."""

    def test_create_changeset_emits_created_entry(self, store):
        store.create_changeset("Deploy v1", ["api", "web"])
        entries = _read_log(store)
        cs_entries = [e for e in entries if e["item_type"] == "changeset"]
        assert len(cs_entries) == 1
        assert cs_entries[0]["event_type"] == "create"
        assert cs_entries[0]["item_id"].startswith("CS-TST-")


class TestLogEntryFields:
    """All emitted log entries must have required fields populated."""

    def test_log_entries_have_timestamp(self, store):
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        assert len(entries) > 0
        for entry in entries:
            assert "timestamp" in entry
            assert entry["timestamp"]  # non-empty

    def test_log_entries_have_actor(self, store):
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        for entry in entries:
            assert "actor" in entry
            assert entry["actor"]  # non-empty

    def test_log_entries_have_source(self, store):
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        for entry in entries:
            assert "source" in entry
            assert entry["source"]  # non-empty

    def test_logging_does_not_break_create(self, store):
        """Store.create_* must still work correctly with logging enabled."""
        meta, _ = store.create_story("Story", "Desc")
        assert meta.id == "US-TST-1"
        task = store.create_task("US-TST-1", "Task", "Desc")
        assert task.id == "US-TST-1-1"
        epic = store.create_epic("Epic", "Desc")
        assert epic.id.startswith("EPIC-TST-")
        # All items should be readable
        store.get_story("US-TST-1")
        store.get_task("US-TST-1-1")
        store.get_epic(epic.id)
