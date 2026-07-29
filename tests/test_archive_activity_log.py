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

    Since archive() delegates to update(), we look for update entries whose
    changes record the archival.  Epics and stories archive by moving *status*
    to 'archived'; tasks archive by setting the orthogonal ``archived`` flag
    and leaving status alone (US-PM-16), so both shapes count.
    """
    entries = []
    for e in _read_log(store):
        if e["event_type"] != "update":
            continue
        changes = e.get("changes", {})
        status_archived = (
            "status" in changes and changes["status"].get("after") == "archived"
        )
        flag_archived = "archived" in changes and changes["archived"].get("after") is True
        if status_archived or flag_archived:
            entries.append(e)
    return entries


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
    """Store.archive() on a task must emit a log entry setting ``archived``.

    Archiving used to write status=done, which made abandoned work
    indistinguishable from delivered work.  The log now has to show the
    archival itself, and show that status was left untouched.
    """

    def test_archive_task_emits_entry(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "US-TST-1-1"
        assert entries[0]["item_type"] == "task"

    def test_archive_task_sets_archived_flag_not_status(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        diff = entries[0]["changes"]["archived"]
        assert diff["after"] is True
        assert "status" not in entries[0]["changes"]

    def test_archive_in_progress_task_preserves_real_status(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.update("US-TST-1-1", status="in-progress")
        store.archive("US-TST-1-1")
        entries = _archive_entries(store)
        assert len(entries) == 1
        assert entries[0]["changes"]["archived"]["after"] is True
        assert "status" not in entries[0]["changes"]
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.status.value == "in-progress"
        assert meta.archived is True


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
        """Archiving a task marks it archived without claiming it was done."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.archived is True
        assert meta.status.value == "todo"
