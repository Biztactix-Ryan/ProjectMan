"""Tests for Store.archive() activity log emissions (US-PRJ-18-3)."""

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


def _archive_entries(store: Store) -> list[dict]:
    """Return only log entries emitted after the initial create(s).

    Since archive() delegates to update(), we look for update entries
    whose changes include a status transition to 'archived' or 'done'.
    """
    return [
        e
        for e in _read_log(store)
        if e["event_type"] == "update"
        and "status" in e.get("changes", {})
        and e["changes"]["status"].get("after") in ("archived", "done")
    ]


class TestArchiveStoryEmitsLog:
    """Store.archive() on a story must emit a log entry with status → archived."""

    def test_archive_story_emits_entry(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "US-TST-1"
        assert entries[0]["item_type"] == "story"

    def test_archive_story_status_change(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "backlog"
        assert diff["after"] == "archived"

    def test_archive_active_story_captures_transition(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "active"
        assert diff["after"] == "archived"


class TestArchiveTaskEmitsLog:
    """Store.archive() on a task must emit a log entry with status → done."""

    def test_archive_task_emits_entry(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "US-TST-1-1"
        assert entries[0]["item_type"] == "task"

    def test_archive_task_status_change(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "todo"
        assert diff["after"] == "done"

    def test_archive_in_progress_task_captures_transition(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.update("US-TST-1-1", status="in-progress")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "in-progress"
        assert diff["after"] == "done"


class TestArchiveEpicEmitsLog:
    """Store.archive() on an epic must emit a log entry with status → archived."""

    def test_archive_epic_emits_entry(self, store):
        store.create_epic("Epic", "Desc")
        store.archive("EPIC-TST-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "EPIC-TST-1"
        assert entries[0]["item_type"] == "epic"

    def test_archive_epic_status_change(self, store):
        store.create_epic("Epic", "Desc")
        store.archive("EPIC-TST-1")
        entries = _archive_entries(store)
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "draft"
        assert diff["after"] == "archived"

    def test_archive_active_epic_captures_transition(self, store):
        store.create_epic("Epic", "Desc")
        store.update("EPIC-TST-1", status="active")
        store.archive("EPIC-TST-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "active"
        assert diff["after"] == "archived"


class TestArchiveLogEntryFields:
    """Archive log entries must have all required fields."""

    def test_has_timestamp(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        assert "timestamp" in entries[0]
        assert entries[0]["timestamp"]

    def test_has_actor(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        assert "actor" in entries[0]
        assert entries[0]["actor"]

    def test_has_source(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _archive_entries(store)
        assert "source" in entries[0]
        assert entries[0]["source"]

    def test_archive_does_not_break_existing_functionality(self, store):
        """Store.archive() must still work correctly with logging enabled."""
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

    def test_archive_task_does_not_break_existing_functionality(self, store):
        """Archiving a task still sets it to done."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.status.value == "done"
