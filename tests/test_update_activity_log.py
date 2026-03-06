"""Tests for Store.update() activity log emissions (US-PRJ-18-2)."""

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


def _update_entries(store: Store) -> list[dict]:
    """Return only 'update' log entries."""
    return [e for e in _read_log(store) if e["event_type"] == "update"]


class TestUpdateEmitsLogEntry:
    """Store.update() must emit an 'update' log entry."""

    def test_update_story_emits_update_entry(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _update_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "US-TST-1"
        assert entries[0]["item_type"] == "story"

    def test_update_task_emits_update_entry(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.update("US-TST-1-1", status="in-progress")
        entries = _update_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "US-TST-1-1"
        assert entries[0]["item_type"] == "task"

    def test_update_epic_emits_update_entry(self, store):
        store.create_epic("Epic", "Desc")
        store.update("EPIC-TST-1", status="active")
        entries = _update_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "EPIC-TST-1"
        assert entries[0]["item_type"] == "epic"


class TestUpdateCapturesFieldDiffs:
    """Update entries must include before/after values for changed fields."""

    def test_status_change_has_before_after(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _update_entries(store)
        assert "status" in entries[0]["changes"]
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "backlog"
        assert diff["after"] == "active"

    def test_points_change_has_before_after(self, store):
        store.create_story("Story", "Desc", points=3)
        store.update("US-TST-1", points=5)
        entries = _update_entries(store)
        assert "points" in entries[0]["changes"]
        diff = entries[0]["changes"]["points"]
        assert diff["before"] == 3
        assert diff["after"] == 5

    def test_title_change_has_before_after(self, store):
        store.create_story("Old Title", "Desc")
        store.update("US-TST-1", title="New Title")
        entries = _update_entries(store)
        assert "title" in entries[0]["changes"]
        diff = entries[0]["changes"]["title"]
        assert diff["before"] == "Old Title"
        assert diff["after"] == "New Title"

    def test_body_change_has_before_after(self, store):
        store.create_story("Story", "Original body")
        store.update("US-TST-1", body="Updated body")
        entries = _update_entries(store)
        assert "body" in entries[0]["changes"]
        diff = entries[0]["changes"]["body"]
        assert diff["before"] == "Original body"
        assert diff["after"] == "Updated body"

    def test_multiple_field_changes_all_captured(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active", title="Renamed")
        entries = _update_entries(store)
        assert "status" in entries[0]["changes"]
        assert "title" in entries[0]["changes"]

    def test_unchanged_fields_not_in_changes(self, store):
        """If a field is set to its current value, it should not appear in changes."""
        store.create_story("Story", "Desc")
        store.update("US-TST-1", title="Story")
        entries = _update_entries(store)
        # title didn't actually change, so it shouldn't be in changes
        assert "title" not in entries[0]["changes"]

    def test_task_status_change_has_before_after(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.update("US-TST-1-1", status="in-progress")
        entries = _update_entries(store)
        diff = entries[0]["changes"]["status"]
        assert diff["before"] == "todo"
        assert diff["after"] == "in-progress"


class TestUpdateLogEntryFields:
    """Update log entries must have all required fields."""

    def test_has_timestamp(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _update_entries(store)
        assert "timestamp" in entries[0]
        assert entries[0]["timestamp"]

    def test_has_actor(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _update_entries(store)
        assert "actor" in entries[0]
        assert entries[0]["actor"]

    def test_has_source(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _update_entries(store)
        assert "source" in entries[0]
        assert entries[0]["source"]

    def test_multiple_updates_emit_multiple_entries(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        store.update("US-TST-1", status="done")
        entries = _update_entries(store)
        assert len(entries) == 2

    def test_update_does_not_break_existing_functionality(self, store):
        """Store.update() must still work correctly with logging enabled."""
        store.create_story("Story", "Desc")
        meta = store.update("US-TST-1", status="active", title="Renamed")
        assert meta.status.value == "active"
        assert meta.title == "Renamed"
        # Verify persisted correctly
        meta2, _ = store.get_story("US-TST-1")
        assert meta2.status.value == "active"
        assert meta2.title == "Renamed"
