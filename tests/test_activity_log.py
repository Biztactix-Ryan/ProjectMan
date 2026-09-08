"""Tests for the activity log data model (US-PRJ-17)."""

import pytest
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        for it in ("story", "task", "epic", "sprint"):
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
        # `run_id` joined the schema in US-PM-14-5: which orchestrator run
        # owned this mutation, so a restarted run can find its own claims.
        # Serialised even when null — a fixed key set is what makes this
        # assertion a contract rather than a sample.
        expected_keys = {"event_type", "item_id", "item_type", "changes", "timestamp", "actor", "source", "run_id"}
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


class TestReadLogEntries:
    """US-PRJ-52-9: one tolerant reader in activity_log.py.

    Reading the log used to be hand-rolled once per caller.  These pin the
    single implementation's contract: a missing file and a bad line are
    survivable, order is the order entries were appended in unless the
    caller asks otherwise.
    """

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

    def _seed(self, log_file, item_ids):
        from projectman.activity_log import append_log_entry

        for item_id in item_ids:
            append_log_entry(log_file, self._make_entry(item_id=item_id))

    def test_missing_file_reads_as_empty(self, tmp_path):
        """A log that was never written is no entries, not an error."""
        from projectman.activity_log import read_log_entries

        assert read_log_entries(tmp_path / "activity.jsonl") == []

    def test_unreadable_path_reads_as_empty(self, tmp_path):
        """A path that is not a readable file is also just no entries."""
        from projectman.activity_log import read_log_entries

        a_directory = tmp_path / "activity.jsonl"
        a_directory.mkdir()
        assert read_log_entries(a_directory) == []

    def test_empty_file_reads_as_empty(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("")
        assert read_log_entries(log_file) == []

    def test_blank_lines_are_skipped(self, tmp_path):
        """Blank and whitespace-only lines carry no event."""
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1"])
        with open(log_file, "a") as f:
            f.write("\n   \n\n")
        self._seed(log_file, ["PRJ-2"])

        entries = read_log_entries(log_file)
        assert [e["item_id"] for e in entries] == ["PRJ-1", "PRJ-2"]

    def test_only_blank_lines_reads_as_empty(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("\n\n  \n\n")
        assert read_log_entries(log_file) == []

    def test_malformed_line_is_skipped_and_the_rest_kept(self, tmp_path):
        """One corrupt line must not cost the caller the whole history."""
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1"])
        with open(log_file, "a") as f:
            f.write("{not json at all\n")
        self._seed(log_file, ["PRJ-2"])

        entries = read_log_entries(log_file)
        assert [e["item_id"] for e in entries] == ["PRJ-1", "PRJ-2"]

    def test_all_lines_malformed_reads_as_empty(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("not json\nalso not json\n{broken\n")
        assert read_log_entries(log_file) == []

    def test_non_object_json_lines_are_skipped(self, tmp_path):
        """A bare scalar or array parses, but it is not an event."""
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text('42\n["a", "b"]\n"just a string"\n{"item_id": "PRJ-1"}\n')

        entries = read_log_entries(log_file)
        assert entries == [{"item_id": "PRJ-1"}]

    def test_entries_are_raw_dicts_with_unknown_keys_preserved(self, tmp_path):
        """Lines are returned as written: callers filter on keys by name and
        a line from an older version must not be validated away."""
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text('{"item_id": "PRJ-1", "legacy_field": "kept"}\n')

        entries = read_log_entries(log_file)
        assert entries == [{"item_id": "PRJ-1", "legacy_field": "kept"}]

    def test_default_order_is_oldest_first(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2", "PRJ-3"])

        entries = read_log_entries(log_file)
        assert [e["item_id"] for e in entries] == ["PRJ-1", "PRJ-2", "PRJ-3"]

    def test_newest_first_reverses_the_order(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2", "PRJ-3"])

        entries = read_log_entries(log_file, newest_first=True)
        assert [e["item_id"] for e in entries] == ["PRJ-3", "PRJ-2", "PRJ-1"]

    def test_limit_applies_after_ordering(self, tmp_path):
        """newest_first + limit is 'the N most recent events'."""
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2", "PRJ-3"])

        assert [e["item_id"] for e in read_log_entries(log_file, limit=2)] == [
            "PRJ-1",
            "PRJ-2",
        ]
        newest = read_log_entries(log_file, newest_first=True, limit=2)
        assert [e["item_id"] for e in newest] == ["PRJ-3", "PRJ-2"]

    def test_limit_larger_than_the_log_returns_everything(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2"])
        assert len(read_log_entries(log_file, limit=99)) == 2

    def test_limit_zero_returns_nothing(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2"])
        assert read_log_entries(log_file, limit=0) == []

    def test_round_trips_what_the_writer_wrote(self, tmp_path):
        """Every field append_log_entry serialises comes back."""
        from projectman.activity_log import append_log_entry, read_log_entries

        log_file = tmp_path / "activity.jsonl"
        entry = self._make_entry(
            event_type=EventType.update,
            changes={"status": {"before": "backlog", "after": "active"}},
            run_id="orch-1",
        )
        append_log_entry(log_file, entry)

        (read_back,) = read_log_entries(log_file)
        assert read_back == json.loads(entry.model_dump_json())
        assert read_back["changes"]["status"]["after"] == "active"
        assert read_back["run_id"] == "orch-1"

    def test_several_paths_are_read_in_the_order_given(self, tmp_path):
        """Rotation (US-PRJ-52-10) will pass rotated files then the live one,
        so the reader must accept a sequence and keep the caller's order."""
        from projectman.activity_log import read_log_entries

        older = tmp_path / "activity-2026-01-01.jsonl"
        live = tmp_path / "activity.jsonl"
        self._seed(older, ["PRJ-1", "PRJ-2"])
        self._seed(live, ["PRJ-3"])

        entries = read_log_entries([older, live])
        assert [e["item_id"] for e in entries] == ["PRJ-1", "PRJ-2", "PRJ-3"]

    def test_a_missing_path_in_a_sequence_is_skipped(self, tmp_path):
        from projectman.activity_log import read_log_entries

        live = tmp_path / "activity.jsonl"
        self._seed(live, ["PRJ-1"])

        entries = read_log_entries([tmp_path / "gone.jsonl", live])
        assert [e["item_id"] for e in entries] == ["PRJ-1"]

    def test_accepts_a_path_given_as_a_string(self, tmp_path):
        from projectman.activity_log import read_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1"])
        assert len(read_log_entries(str(log_file))) == 1

    def test_iter_log_entries_is_lazy(self, tmp_path):
        """The iterator form streams: it must not materialise the log."""
        from projectman.activity_log import iter_log_entries

        log_file = tmp_path / "activity.jsonl"
        self._seed(log_file, ["PRJ-1", "PRJ-2", "PRJ-3"])

        stream = iter_log_entries(log_file)
        assert not isinstance(stream, list)
        assert next(iter(stream))["item_id"] == "PRJ-1"


class TestOneReaderForEveryCaller:
    """US-PRJ-52: server.py and migrations.py read through activity_log.py."""

    def test_migrations_delegates_to_the_shared_reader(self):
        """migrations.read_activity_log keeps its public name but no longer
        parses the file itself."""
        import inspect

        from projectman import activity_log, migrations

        assert migrations.read_log_entries is activity_log.read_log_entries
        source = inspect.getsource(migrations.read_activity_log)
        assert "read_log_entries" in source
        assert "json.loads" not in source

    def test_migrations_reader_still_tolerates_a_missing_log(self, tmp_path):
        from projectman.migrations import read_activity_log

        assert read_activity_log(tmp_path) == []

    def test_migrations_reader_reads_the_project_dir_log(self, tmp_path):
        from projectman.activity_log import append_log_entry
        from projectman.migrations import read_activity_log

        entry = LogEntry(
            event_type=EventType.update,
            item_id="US-TST-1-1",
            item_type=ItemType.task,
            timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            actor="claude",
            source=LogSource.mcp,
        )
        append_log_entry(tmp_path / "activity.jsonl", entry)
        with open(tmp_path / "activity.jsonl", "a") as f:
            f.write("garbage\n")

        assert [e["item_id"] for e in read_activity_log(tmp_path)] == ["US-TST-1-1"]

    def test_pm_activity_reads_through_the_shared_reader(
        self, tmp_project, monkeypatch
    ):
        """pm_activity must not re-implement parsing: patching the one reader
        changes what it sees."""
        from projectman import activity_log

        monkeypatch.chdir(tmp_project)
        log_path = tmp_project / ".project" / "activity.jsonl"
        activity_log.append_log_entry(
            log_path,
            LogEntry(
                event_type=EventType.create,
                item_id="US-TST-1",
                item_type=ItemType.story,
                timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
                actor="claude",
                source=LogSource.mcp,
            ),
        )

        calls = []
        real_reader = activity_log.read_log_entries

        def spy(source, **kwargs):
            calls.append(source)
            return real_reader(source, **kwargs)

        monkeypatch.setattr(activity_log, "read_log_entries", spy)

        from projectman.server import pm_activity

        result = yaml.safe_load(pm_activity())
        # Since US-PRJ-52-10 the reader is handed the project's whole log
        # set — rotated siblings then the live file — not a bare path.
        assert calls == [[log_path]]
        assert result["total"] == 1


class TestActivityLogRotation:
    """US-PRJ-52-10: the log rotates on append past a configured bound.

    The unit of rotation is the append: the bound is checked against the
    file already on disk, the rename happens, and only then is the line
    written.  That order is what makes "rotation loses no entry" true, so
    most of these tests count entries either side of one.
    """

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

    def _append(self, log_file, item_id, **bounds):
        from projectman.activity_log import append_log_entry

        append_log_entry(log_file, self._make_entry(item_id=item_id), **bounds)

    def _all_entries(self, project_dir):
        from projectman.activity_log import log_paths, read_log_entries

        return read_log_entries(log_paths(project_dir))

    # --- the default: nothing rotates ---------------------------------

    def test_unconfigured_append_never_rotates(self, tmp_path):
        """No bound configured is the default and means the log grows."""
        log_file = tmp_path / "activity.jsonl"
        for i in range(20):
            self._append(log_file, f"PRJ-{i}")

        assert list(tmp_path.glob("activity-*.jsonl")) == []
        assert len(self._all_entries(tmp_path)) == 20

    def test_explicit_none_bounds_never_rotate(self, tmp_path):
        log_file = tmp_path / "activity.jsonl"
        for i in range(5):
            self._append(log_file, f"PRJ-{i}", max_bytes=None, max_days=None)

        assert list(tmp_path.glob("activity-*.jsonl")) == []

    def test_a_zero_or_negative_bound_is_no_bound(self, tmp_path):
        """Zero would rotate on every append; nobody means that by it."""
        log_file = tmp_path / "activity.jsonl"
        for i in range(5):
            self._append(log_file, f"PRJ-{i}", max_bytes=0, max_days=-1)

        assert list(tmp_path.glob("activity-*.jsonl")) == []

    def test_a_junk_bound_is_no_bound(self, tmp_path):
        log_file = tmp_path / "activity.jsonl"
        for i in range(5):
            self._append(log_file, f"PRJ-{i}", max_bytes="soon", max_days="never")

        assert list(tmp_path.glob("activity-*.jsonl")) == []

    def test_an_empty_log_is_never_rotated(self, tmp_path):
        """Rotating an empty file would only litter the directory."""
        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("")
        self._append(log_file, "PRJ-1", max_bytes=1)

        assert list(tmp_path.glob("activity-*.jsonl")) == []
        assert len(self._all_entries(tmp_path)) == 1

    # --- the size bound -----------------------------------------------

    def test_size_bound_rotates_and_the_new_entry_lands_in_the_fresh_file(
        self, tmp_path
    ):
        log_file = tmp_path / "activity.jsonl"
        self._append(log_file, "PRJ-1")
        over = log_file.stat().st_size

        self._append(log_file, "PRJ-2", max_bytes=over)

        (rotated,) = list(tmp_path.glob("activity-*.jsonl"))
        from projectman.activity_log import read_log_entries

        assert [e["item_id"] for e in read_log_entries(rotated)] == ["PRJ-1"]
        assert [e["item_id"] for e in read_log_entries(log_file)] == ["PRJ-2"]

    def test_size_bound_under_the_limit_does_not_rotate(self, tmp_path):
        log_file = tmp_path / "activity.jsonl"
        self._append(log_file, "PRJ-1")

        self._append(log_file, "PRJ-2", max_bytes=10 * log_file.stat().st_size)

        assert list(tmp_path.glob("activity-*.jsonl")) == []
        assert len(self._all_entries(tmp_path)) == 2

    def test_rotation_loses_no_entry(self, tmp_path):
        """count before + 1 == count across every file after."""
        log_file = tmp_path / "activity.jsonl"
        for i in range(5):
            self._append(log_file, f"PRJ-{i}")
        before = len(self._all_entries(tmp_path))

        self._append(log_file, "PRJ-final", max_bytes=1)

        after = self._all_entries(tmp_path)
        assert len(after) == before + 1
        assert after[-1]["item_id"] == "PRJ-final"
        assert [e["item_id"] for e in after[:-1]] == [f"PRJ-{i}" for i in range(5)]

    def test_repeated_rotations_keep_every_entry(self, tmp_path):
        """Rotating on every append still adds up to every entry, in order."""
        import itertools

        from projectman import activity_log

        log_file = tmp_path / "activity.jsonl"
        moments = itertools.count()
        real_rotate = activity_log.rotate_log
        # Distinct stamps without sleeping a real second per append.
        base = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

        def rotate_at_a_fake_time(path, now=None):
            return real_rotate(path, now=base + timedelta(seconds=next(moments)))

        self._append(log_file, "PRJ-0")
        original = activity_log.rotate_log
        activity_log.rotate_log = rotate_at_a_fake_time
        try:
            for i in range(1, 5):
                self._append(log_file, f"PRJ-{i}", max_bytes=1)
        finally:
            activity_log.rotate_log = original

        assert len(list(tmp_path.glob("activity-*.jsonl"))) == 4
        assert [e["item_id"] for e in self._all_entries(tmp_path)] == [
            f"PRJ-{i}" for i in range(5)
        ]

    # --- the age bound ------------------------------------------------

    def test_age_bound_rotates_when_the_oldest_entry_is_older_than_n_days(
        self, tmp_path
    ):
        log_file = tmp_path / "activity.jsonl"
        old = datetime.now(timezone.utc) - timedelta(days=10)
        self._append_at(log_file, "PRJ-old", old)

        self._append(log_file, "PRJ-new", max_days=7)

        (rotated,) = list(tmp_path.glob("activity-*.jsonl"))
        from projectman.activity_log import read_log_entries

        assert [e["item_id"] for e in read_log_entries(rotated)] == ["PRJ-old"]
        assert [e["item_id"] for e in read_log_entries(log_file)] == ["PRJ-new"]

    def test_age_bound_does_not_rotate_a_young_log(self, tmp_path):
        log_file = tmp_path / "activity.jsonl"
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        self._append_at(log_file, "PRJ-1", recent)

        self._append(log_file, "PRJ-2", max_days=7)

        assert list(tmp_path.glob("activity-*.jsonl")) == []

    def test_age_is_measured_from_the_oldest_entry_not_the_newest(self, tmp_path):
        """A busy log must still rotate: mtime would keep it young forever."""
        log_file = tmp_path / "activity.jsonl"
        self._append_at(log_file, "PRJ-old", datetime.now(timezone.utc) - timedelta(days=30))
        self._append_at(log_file, "PRJ-recent", datetime.now(timezone.utc))

        self._append(log_file, "PRJ-newest", max_days=7)

        (rotated,) = list(tmp_path.glob("activity-*.jsonl"))
        from projectman.activity_log import read_log_entries

        assert [e["item_id"] for e in read_log_entries(rotated)] == [
            "PRJ-old",
            "PRJ-recent",
        ]

    def test_age_falls_back_to_mtime_when_no_line_parses(self, tmp_path):
        """A log of nothing but corrupt lines still has an answerable age."""
        import os
        import time

        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("garbage\nmore garbage\n")
        long_ago = time.time() - 30 * 86400
        os.utime(log_file, (long_ago, long_ago))

        self._append(log_file, "PRJ-1", max_days=7)

        assert len(list(tmp_path.glob("activity-*.jsonl"))) == 1
        assert [e["item_id"] for e in self._all_entries(tmp_path)] == ["PRJ-1"]

    def _append_at(self, log_file, item_id, moment):
        from projectman.activity_log import append_log_entry

        append_log_entry(log_file, self._make_entry(item_id=item_id, timestamp=moment))

    # --- the sibling's name -------------------------------------------

    def test_rotated_sibling_is_named_for_the_moment_it_rotated(self, tmp_path):
        from projectman.activity_log import rotate_log

        log_file = tmp_path / "activity.jsonl"
        self._append(log_file, "PRJ-1")

        rotated = rotate_log(
            log_file, now=datetime(2026, 9, 8, 14, 30, 45, tzinfo=timezone.utc)
        )

        assert rotated.name == "activity-20260908-143045.jsonl"
        assert rotated.exists()
        assert not log_file.exists()

    def test_a_taken_name_pushes_the_stamp_forward_not_a_suffix(self, tmp_path):
        """A ``-2`` suffix would sort *before* the plain name and break
        chronological order; the next second does not."""
        from projectman.activity_log import rotate_log

        moment = datetime(2026, 9, 8, 14, 30, 45, tzinfo=timezone.utc)
        (tmp_path / "activity-20260908-143045.jsonl").write_text("{}\n")
        log_file = tmp_path / "activity.jsonl"
        self._append(log_file, "PRJ-1")

        rotated = rotate_log(log_file, now=moment)

        assert rotated.name == "activity-20260908-143046.jsonl"

    def test_rotate_log_returns_none_when_the_rename_fails(self, tmp_path):
        """A failed rename must not be silent *and* must not lose the entry."""
        from projectman import activity_log

        log_file = tmp_path / "activity.jsonl"
        self._append(log_file, "PRJ-1")

        def refuse(self, target):
            raise OSError("read-only filesystem")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "rename", refuse)
            assert activity_log.rotate_log(log_file) is None
            # ...and the appending caller writes anyway rather than lose it.
            self._append(log_file, "PRJ-2", max_bytes=1)

        assert list(tmp_path.glob("activity-*.jsonl")) == []
        assert [e["item_id"] for e in self._all_entries(tmp_path)] == ["PRJ-1", "PRJ-2"]

    # --- the reader across siblings -----------------------------------

    def test_log_paths_walks_siblings_oldest_first_then_live(self, tmp_path):
        from projectman.activity_log import log_paths

        for name in (
            "activity-20260601-000000.jsonl",
            "activity-20260301-000000.jsonl",
            "activity-20260901-000000.jsonl",
        ):
            (tmp_path / name).write_text("{}\n")
        (tmp_path / "activity.jsonl").write_text("{}\n")

        assert [p.name for p in log_paths(tmp_path)] == [
            "activity-20260301-000000.jsonl",
            "activity-20260601-000000.jsonl",
            "activity-20260901-000000.jsonl",
            "activity.jsonl",
        ]

    def test_log_paths_skips_a_missing_live_file(self, tmp_path):
        from projectman.activity_log import log_paths

        (tmp_path / "activity-20260301-000000.jsonl").write_text("{}\n")

        assert [p.name for p in log_paths(tmp_path)] == [
            "activity-20260301-000000.jsonl"
        ]

    def test_log_paths_is_empty_for_a_project_with_no_log(self, tmp_path):
        from projectman.activity_log import log_paths

        assert log_paths(tmp_path) == []

    def test_a_hand_dropped_lookalike_is_not_treated_as_rotation_output(self, tmp_path):
        """Only the exact activity-YYYYMMDD-HHMMSS.jsonl shape counts."""
        from projectman.activity_log import log_paths

        for name in (
            "activity-old.jsonl",
            "activity-2026-03-01.jsonl",
            "activity-20260301.jsonl",
            "activity-20260301-000000.jsonl.bak",
        ):
            (tmp_path / name).write_text("{}\n")
        (tmp_path / "activity.jsonl").write_text("{}\n")

        assert [p.name for p in log_paths(tmp_path)] == ["activity.jsonl"]

    def test_reader_returns_entries_across_a_real_rotation_in_order(self, tmp_path):
        log_file = tmp_path / "activity.jsonl"
        for i in range(3):
            self._append(log_file, f"PRJ-{i}")
        self._append(log_file, "PRJ-3", max_bytes=1)
        self._append(log_file, "PRJ-4")

        assert [e["item_id"] for e in self._all_entries(tmp_path)] == [
            f"PRJ-{i}" for i in range(5)
        ]


class TestRotationThroughTheStore:
    """The bounds reach the writer from config.yaml, through the store."""

    def _set_bounds(self, tmp_project, **bounds):
        from projectman.config import clear_config_cache

        config_path = tmp_project / ".project" / "config.yaml"
        data = yaml.safe_load(config_path.read_text())
        data.update(bounds)
        config_path.write_text(yaml.dump(data))
        clear_config_cache(tmp_project)

    def test_config_defaults_leave_both_bounds_unset(self, tmp_project):
        from projectman.config import load_config

        config = load_config(tmp_project)
        assert config.activity_log_max_bytes is None
        assert config.activity_log_max_days is None

    def test_a_junk_bound_does_not_break_the_config_load(self, tmp_project):
        from projectman.config import load_config

        self._set_bounds(tmp_project, activity_log_max_bytes="soon")
        config = load_config(tmp_project)
        assert config.activity_log_max_bytes is None

    def test_store_writes_rotate_once_a_size_bound_is_configured(self, tmp_project):
        from projectman.store import Store

        self._set_bounds(tmp_project, activity_log_max_bytes=1)
        store = Store(tmp_project)
        proj_dir = tmp_project / ".project"

        store.create_story("First story", "A description")
        store.create_story("Second story", "A description")

        from projectman.activity_log import log_paths, read_log_entries

        assert list(proj_dir.glob("activity-*.jsonl"))
        entries = read_log_entries(log_paths(proj_dir))
        assert len(entries) == 2

    def test_store_writes_do_not_rotate_by_default(self, tmp_project):
        from projectman.store import Store

        store = Store(tmp_project)
        proj_dir = tmp_project / ".project"
        for i in range(4):
            store.create_story(f"Story {i}", "A description")

        assert list(proj_dir.glob("activity-*.jsonl")) == []

    def test_pm_activity_counts_entries_across_rotated_files(
        self, tmp_project, monkeypatch
    ):
        from projectman.activity_log import append_log_entry

        monkeypatch.chdir(tmp_project)
        proj_dir = tmp_project / ".project"

        def entry(item_id):
            return LogEntry(
                event_type=EventType.create,
                item_id=item_id,
                item_type=ItemType.story,
                timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
                actor="claude",
                source=LogSource.mcp,
            )

        append_log_entry(proj_dir / "activity-20260301-000000.jsonl", entry("US-TST-1"))
        append_log_entry(proj_dir / "activity-20260601-000000.jsonl", entry("US-TST-2"))
        append_log_entry(proj_dir / "activity.jsonl", entry("US-TST-3"))

        from projectman.server import pm_activity

        result = yaml.safe_load(pm_activity())
        assert result["total"] == 3
        # Newest-first page, and "newest" spans the rotation boundary.
        assert "US-TST-3" in result["entries"][0]
        assert "US-TST-1" in result["entries"][-1]

    def test_pm_activity_reads_rotated_files_when_the_live_file_is_gone(
        self, tmp_project, monkeypatch
    ):
        """A log rotated a second ago has no live file yet — history stands."""
        from projectman.activity_log import append_log_entry

        monkeypatch.chdir(tmp_project)
        proj_dir = tmp_project / ".project"
        append_log_entry(
            proj_dir / "activity-20260301-000000.jsonl",
            LogEntry(
                event_type=EventType.create,
                item_id="US-TST-1",
                item_type=ItemType.story,
                timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
                actor="claude",
                source=LogSource.mcp,
            ),
        )

        from projectman.server import pm_activity

        result = yaml.safe_load(pm_activity())
        assert result["total"] == 1
        assert "message" not in result

    def test_pm_activity_still_reports_no_log_when_there_is_none(
        self, tmp_project, monkeypatch
    ):
        monkeypatch.chdir(tmp_project)

        from projectman.server import pm_activity

        result = yaml.safe_load(pm_activity())
        assert result["total"] == 0
        assert "No activity log found" in result.get("message", "")

    def test_migrations_reader_spans_rotated_files(self, tmp_path):
        from projectman.activity_log import append_log_entry
        from projectman.migrations import read_activity_log

        def entry(item_id):
            return LogEntry(
                event_type=EventType.update,
                item_id=item_id,
                item_type=ItemType.task,
                timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
                actor="claude",
                source=LogSource.mcp,
            )

        append_log_entry(tmp_path / "activity-20260301-000000.jsonl", entry("US-TST-1-1"))
        append_log_entry(tmp_path / "activity.jsonl", entry("US-TST-1-2"))

        assert [e["item_id"] for e in read_activity_log(tmp_path)] == [
            "US-TST-1-1",
            "US-TST-1-2",
        ]
