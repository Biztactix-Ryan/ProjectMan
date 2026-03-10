"""Tests for run-log feature (outcome/note on pm_update + pm_run_log reader)."""

import json

import pytest

from projectman.store import Store, _cache


class TestRunLog:
    def test_update_with_outcome_creates_log(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", status="in-progress", outcome="partial", note="Started work, tests failing")

        entries = store.get_run_log("US-TST-1-1")
        assert len(entries) == 1
        assert entries[0].outcome.value == "partial"
        assert entries[0].note == "Started work, tests failing"
        assert entries[0].status == "in-progress"

    def test_update_without_outcome_no_log(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", status="in-progress")

        entries = store.get_run_log("US-TST-1-1")
        assert entries == []

    def test_note_over_1024_rejected(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        with pytest.raises(ValueError, match="1024 characters"):
            store.update("US-TST-1-1", outcome="info", note="x" * 1025)

    def test_note_exactly_1024_accepted(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", outcome="info", note="x" * 1024)

        entries = store.get_run_log("US-TST-1-1")
        assert len(entries) == 1
        assert len(entries[0].note) == 1024

    def test_invalid_outcome_rejected(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        with pytest.raises(ValueError):
            store.update("US-TST-1-1", outcome="yolo", note="bad outcome")

    def test_multiple_entries_append(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        store.update("US-TST-1-1", status="in-progress", outcome="failed", note="Build error")
        store.update("US-TST-1-1", outcome="partial", note="Fixed build, tests still failing")
        store.update("US-TST-1-1", status="done", outcome="success", note="All green")

        entries = store.get_run_log("US-TST-1-1")
        assert len(entries) == 3
        # Most recent first
        assert entries[0].outcome.value == "success"
        assert entries[1].outcome.value == "partial"
        assert entries[2].outcome.value == "failed"

    def test_get_run_log_reverse_chronological(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        store.update("US-TST-1-1", outcome="info", note="First")
        store.update("US-TST-1-1", outcome="info", note="Second")
        store.update("US-TST-1-1", outcome="info", note="Third")

        entries = store.get_run_log("US-TST-1-1")
        assert entries[0].note == "Third"
        assert entries[1].note == "Second"
        assert entries[2].note == "First"

    def test_get_run_log_pagination(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        for i in range(5):
            store.update("US-TST-1-1", outcome="info", note=f"Entry {i}")

        entries = store.get_run_log("US-TST-1-1", limit=2)
        assert len(entries) == 2
        assert entries[0].note == "Entry 4"
        assert entries[1].note == "Entry 3"

        entries = store.get_run_log("US-TST-1-1", limit=2, offset=2)
        assert len(entries) == 2
        assert entries[0].note == "Entry 2"
        assert entries[1].note == "Entry 1"

    def test_get_run_log_empty(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")

        entries = store.get_run_log("US-TST-1-1")
        assert entries == []

    def test_get_run_log_nonexistent_item(self, store):
        entries = store.get_run_log("US-TST-999-1")
        assert entries == []

    def test_log_file_location(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", outcome="info", note="test")

        log_path = store.project_dir / "logs" / "US-TST-1-1.jsonl"
        assert log_path.exists()
        line = log_path.read_text().strip()
        data = json.loads(line)
        assert data["outcome"] == "info"
        assert data["note"] == "test"

    def test_log_on_story(self, store):
        store.create_story("Story", "Body")
        store.update("US-TST-1", outcome="blocked", note="Waiting on design")

        entries = store.get_run_log("US-TST-1")
        assert len(entries) == 1
        assert entries[0].outcome.value == "blocked"

    def test_log_on_epic(self, store):
        store.create_epic("Epic", "Big feature")
        store.update("EPIC-TST-1", outcome="info", note="Kickoff meeting done")

        entries = store.get_run_log("EPIC-TST-1")
        assert len(entries) == 1
        assert entries[0].outcome.value == "info"

    def test_outcome_without_note_uses_empty(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", outcome="success")

        entries = store.get_run_log("US-TST-1-1")
        assert len(entries) == 1
        assert entries[0].note == ""

    def test_note_without_outcome_uses_info(self, store):
        store.create_story("Story", "Body")
        store.create_task("US-TST-1", "Task one", "Do it")
        store.update("US-TST-1-1", note="Just a note")

        entries = store.get_run_log("US-TST-1-1")
        assert len(entries) == 1
        assert entries[0].outcome.value == "info"
        assert entries[0].note == "Just a note"
