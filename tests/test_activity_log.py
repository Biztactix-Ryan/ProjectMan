"""Tests for the activity log data model (US-PRJ-17)."""

import pytest
from datetime import datetime, timezone

from pydantic import ValidationError

from projectman.models import EventType, ItemType, LogEntry, LogSource


class TestLogEntrySchema:
    """US-PRJ-17-1: Log entry schema defined with all required fields."""

    def _make_entry(self, **overrides):
        defaults = {
            "event_type": EventType.create,
            "item_id": "PRJ-1",
            "item_type": ItemType.story,
            "timestamp": datetime.now(timezone.utc),
            "actor": "claude",
            "source": LogSource.mcp,
        }
        defaults.update(overrides)
        return LogEntry(**defaults)

    def test_required_fields_present(self):
        """Schema must include event_type, item_id, item_type, timestamp, actor, source."""
        required = {"event_type", "item_id", "item_type", "timestamp", "actor", "source"}
        field_names = set(LogEntry.model_fields.keys())
        assert required.issubset(field_names)

    def test_valid_entry(self):
        entry = self._make_entry()
        assert entry.event_type == EventType.create
        assert entry.item_id == "PRJ-1"
        assert entry.item_type == ItemType.story
        assert entry.actor == "claude"
        assert entry.source == LogSource.mcp

    def test_changes_defaults_to_empty_dict(self):
        entry = self._make_entry()
        assert entry.changes == {}

    def test_changes_with_before_after(self):
        entry = self._make_entry(
            event_type=EventType.update,
            changes={"status": {"before": "backlog", "after": "active"}},
        )
        assert entry.changes["status"]["before"] == "backlog"
        assert entry.changes["status"]["after"] == "active"

    def test_timestamp_is_iso8601(self):
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry = self._make_entry(timestamp=ts)
        assert entry.timestamp.isoformat() == "2026-03-01T12:00:00+00:00"

    def test_event_type_enum_values(self):
        for et in ("create", "update", "delete", "archive"):
            entry = self._make_entry(event_type=et)
            assert entry.event_type == et

    def test_invalid_event_type_rejected(self):
        with pytest.raises(ValidationError):
            self._make_entry(event_type="invalid")

    def test_item_type_enum_values(self):
        for it in ("story", "task", "epic", "changeset"):
            entry = self._make_entry(item_type=it)
            assert entry.item_type == it

    def test_invalid_item_type_rejected(self):
        with pytest.raises(ValidationError):
            self._make_entry(item_type="widget")

    def test_source_enum_values(self):
        for src in ("mcp", "web", "cli"):
            entry = self._make_entry(source=src)
            assert entry.source == src

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            self._make_entry(source="api")

    def test_missing_required_field_rejected(self):
        """Each required field must cause a ValidationError when omitted."""
        required = ["event_type", "item_id", "item_type", "timestamp", "actor", "source"]
        for field in required:
            kwargs = {
                "event_type": "create",
                "item_id": "PRJ-1",
                "item_type": "story",
                "timestamp": datetime.now(timezone.utc),
                "actor": "claude",
                "source": "mcp",
            }
            del kwargs[field]
            with pytest.raises(ValidationError, match=field):
                LogEntry(**kwargs)


import json


class TestAppendLogEntry:
    """US-PRJ-17-2: Append-only writer function that atomically appends entries."""

    def _make_entry(self, **overrides):
        defaults = {
            "event_type": EventType.create,
            "item_id": "PRJ-1",
            "item_type": ItemType.story,
            "timestamp": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            "actor": "claude",
            "source": LogSource.mcp,
        }
        defaults.update(overrides)
        return LogEntry(**defaults)

    def test_append_writes_single_entry(self, tmp_path):
        """Appending one entry produces exactly one line in the log file."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry()
        append_log_entry(log_file, entry)

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_append_writes_valid_json(self, tmp_path):
        """Each appended line must be valid JSON."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry()
        append_log_entry(log_file, entry)

        line = log_file.read_text().strip()
        parsed = json.loads(line)
        assert parsed["event_type"] == "create"
        assert parsed["item_id"] == "PRJ-1"
        assert parsed["item_type"] == "story"
        assert parsed["actor"] == "claude"
        assert parsed["source"] == "mcp"

    def test_append_preserves_previous_entries(self, tmp_path):
        """Multiple appends must add lines without overwriting earlier ones."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry1 = self._make_entry(item_id="PRJ-1")
        entry2 = self._make_entry(item_id="PRJ-2", event_type=EventType.update)

        append_log_entry(log_file, entry1)
        append_log_entry(log_file, entry2)

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["item_id"] == "PRJ-1"
        assert json.loads(lines[1])["item_id"] == "PRJ-2"

    def test_append_each_entry_on_own_line(self, tmp_path):
        """Each entry occupies exactly one line (no embedded newlines)."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry(
            changes={"status": {"before": "backlog", "after": "active"}},
        )
        append_log_entry(log_file, entry)

        text = log_file.read_text()
        # Must end with newline, and content before that has no newlines
        assert text.endswith("\n")
        assert "\n" not in text.rstrip("\n")

    def test_append_is_truly_append_only(self, tmp_path):
        """Writer must open in append mode — never truncate or rewrite."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        # Pre-seed a line to prove we don't overwrite
        log_file.write_text('{"seed": true}\n')

        entry = self._make_entry()
        append_log_entry(log_file, entry)

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"seed": True}

    def test_append_flushes_to_disk(self, tmp_path):
        """Entry must be flushed so it's readable immediately after the call."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry()
        append_log_entry(log_file, entry)

        # Re-read from a fresh file handle to confirm data is on disk
        with open(log_file, "r") as f:
            content = f.read()
        assert len(content.strip().splitlines()) == 1

    def test_append_includes_all_fields(self, tmp_path):
        """The serialized JSON must contain every LogEntry field."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry(
            changes={"title": {"before": "Old", "after": "New"}},
        )
        append_log_entry(log_file, entry)

        parsed = json.loads(log_file.read_text().strip())
        expected_keys = {"event_type", "item_id", "item_type", "changes", "timestamp", "actor", "source"}
        assert expected_keys == set(parsed.keys())


class TestStorageFormatIsJSONL:
    """US-PRJ-17-3: Storage format is JSONL (one JSON object per line) for easy parsing."""

    def _make_entry(self, **overrides):
        defaults = {
            "event_type": EventType.create,
            "item_id": "PRJ-1",
            "item_type": ItemType.story,
            "timestamp": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            "actor": "claude",
            "source": LogSource.mcp,
        }
        defaults.update(overrides)
        return LogEntry(**defaults)

    def test_each_line_is_valid_json(self, tmp_path):
        """Every line in the log file must be independently parseable as JSON."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        for i in range(5):
            append_log_entry(log_file, self._make_entry(item_id=f"PRJ-{i}"))

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)  # must not raise
            assert isinstance(parsed, dict)

    def test_no_multiline_json(self, tmp_path):
        """JSONL requires compact (single-line) JSON — no pretty-printing."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry(
            changes={"status": {"before": "backlog", "after": "active"},
                     "title": {"before": "Old title", "after": "New title"}},
        )
        append_log_entry(log_file, entry)

        text = log_file.read_text()
        content_lines = text.strip().splitlines()
        assert len(content_lines) == 1, "Entry must be a single line (compact JSON)"

    def test_lines_terminated_with_newline(self, tmp_path):
        """Each JSONL record must end with a newline character."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        raw = log_file.read_text()
        assert raw.endswith("\n"), "JSONL file must end with a trailing newline"

    def test_multiple_entries_parseable_line_by_line(self, tmp_path):
        """Simulate JSONL consumer: read line-by-line and parse each independently."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        entries = [
            self._make_entry(item_id="PRJ-1", event_type=EventType.create),
            self._make_entry(item_id="PRJ-2", event_type=EventType.update,
                             changes={"status": {"before": "todo", "after": "done"}}),
            self._make_entry(item_id="PRJ-3", event_type=EventType.archive),
        ]
        for e in entries:
            append_log_entry(log_file, e)

        # Parse like a typical JSONL consumer
        parsed_entries = []
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    parsed_entries.append(json.loads(line))

        assert len(parsed_entries) == 3
        assert parsed_entries[0]["item_id"] == "PRJ-1"
        assert parsed_entries[1]["item_id"] == "PRJ-2"
        assert parsed_entries[2]["item_id"] == "PRJ-3"

    def test_no_array_wrapper(self, tmp_path):
        """JSONL is NOT a JSON array — file must not start with '[' or end with ']'."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry(item_id="PRJ-1"))
        append_log_entry(log_file, self._make_entry(item_id="PRJ-2"))

        raw = log_file.read_text()
        assert not raw.strip().startswith("["), "JSONL must not be wrapped in a JSON array"
        assert not raw.strip().endswith("]"), "JSONL must not be wrapped in a JSON array"

    def test_each_object_is_a_dict_not_array(self, tmp_path):
        """Each JSONL line must be a JSON object (dict), not an array or scalar."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        for line in log_file.read_text().strip().splitlines():
            parsed = json.loads(line)
            assert isinstance(parsed, dict), f"Expected dict, got {type(parsed).__name__}"


class TestEntriesIncludeISO8601Timestamps:
    """US-PRJ-17-4: Entries include ISO 8601 timestamps."""

    def _make_entry(self, **overrides):
        defaults = {
            "event_type": EventType.create,
            "item_id": "PRJ-1",
            "item_type": ItemType.story,
            "timestamp": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            "actor": "claude",
            "source": LogSource.mcp,
        }
        defaults.update(overrides)
        return LogEntry(**defaults)

    def test_serialized_timestamp_is_iso8601(self, tmp_path):
        """The timestamp in the JSONL output must be a valid ISO 8601 string."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        parsed = json.loads(log_file.read_text().strip())
        ts_str = parsed["timestamp"]
        # Must be parseable as ISO 8601
        dt = datetime.fromisoformat(ts_str)
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 1
        assert dt.hour == 12

    def test_timestamp_contains_t_separator(self, tmp_path):
        """ISO 8601 requires a 'T' separator between date and time components."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        parsed = json.loads(log_file.read_text().strip())
        assert "T" in parsed["timestamp"]

    def test_timestamp_includes_timezone(self, tmp_path):
        """Timestamps must include timezone info (Z or +00:00) per ISO 8601."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        parsed = json.loads(log_file.read_text().strip())
        ts_str = parsed["timestamp"]
        # Must end with Z or an offset like +00:00
        assert ts_str.endswith("Z") or "+" in ts_str or ts_str.endswith("+00:00")

    def test_timestamp_roundtrips_correctly(self, tmp_path):
        """Timestamp must survive a write-then-parse roundtrip without data loss."""
        from projectman.activity_log import append_log_entry

        original_ts = datetime(2026, 6, 15, 9, 30, 45, tzinfo=timezone.utc)
        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry(timestamp=original_ts))

        parsed = json.loads(log_file.read_text().strip())
        restored = datetime.fromisoformat(parsed["timestamp"])
        assert restored == original_ts

    def test_timestamp_field_present_in_every_entry(self, tmp_path):
        """Every serialized log entry must contain a 'timestamp' key."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        for i in range(3):
            ts = datetime(2026, 1, 1 + i, tzinfo=timezone.utc)
            append_log_entry(log_file, self._make_entry(item_id=f"PRJ-{i}", timestamp=ts))

        for line in log_file.read_text().strip().splitlines():
            parsed = json.loads(line)
            assert "timestamp" in parsed, "Every entry must include a timestamp field"
            datetime.fromisoformat(parsed["timestamp"])  # must not raise


class TestFileCreatedOnFirstWrite:
    """US-PRJ-17-5: File created automatically on first write."""

    def _make_entry(self, **overrides):
        defaults = {
            "event_type": EventType.create,
            "item_id": "PRJ-1",
            "item_type": ItemType.story,
            "timestamp": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            "actor": "claude",
            "source": LogSource.mcp,
        }
        defaults.update(overrides)
        return LogEntry(**defaults)

    def test_file_created_when_not_exists(self, tmp_path):
        """Calling append_log_entry on a non-existent file must create it."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        assert not log_file.exists()

        append_log_entry(log_file, self._make_entry())
        assert log_file.exists()

    def test_file_contains_entry_after_creation(self, tmp_path):
        """The auto-created file must contain the written entry."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "activity.jsonl"
        append_log_entry(log_file, self._make_entry())

        content = log_file.read_text().strip()
        parsed = json.loads(content)
        assert parsed["item_id"] == "PRJ-1"

    def test_nested_directory_raises_if_parent_missing(self, tmp_path):
        """Writer should not silently create intermediate directories."""
        from projectman.activity_log import append_log_entry

        log_file = tmp_path / "nonexistent" / "subdir" / "activity.jsonl"
        with pytest.raises(FileNotFoundError):
            append_log_entry(log_file, self._make_entry())
