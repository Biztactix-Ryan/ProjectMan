"""Tests for pm_activity MCP tool (US-PRJ-19)."""

import json
import pytest
import yaml
from datetime import datetime, timezone

from projectman.activity_log import append_log_entry
from projectman.models import EventType, ItemType, LogEntry, LogSource


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Change to the project directory so server tools can find it."""
    monkeypatch.chdir(tmp_project)


def _make_entry(**overrides):
    defaults = {
        "event_type": EventType.create,
        "item_id": "US-TST-1",
        "item_type": ItemType.story,
        "timestamp": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        "actor": "claude",
        "source": LogSource.mcp,
    }
    defaults.update(overrides)
    return LogEntry(**defaults)


def _seed_log(tmp_project, entries):
    """Write multiple LogEntry objects to the activity log."""
    log_path = tmp_project / ".project" / "activity.jsonl"
    for entry in entries:
        append_log_entry(log_path, entry)


class TestPmActivityRegistered:
    """US-PRJ-19-1: pm_activity tool registered and callable via MCP."""

    def test_pm_activity_is_importable(self):
        """The pm_activity function can be imported from the server module."""
        from projectman.server import pm_activity
        assert callable(pm_activity)

    def test_pm_activity_returns_yaml(self, tmp_project):
        """pm_activity returns valid YAML output."""
        from projectman.server import pm_activity
        result = pm_activity()
        data = yaml.safe_load(result)
        assert isinstance(data, dict)

    def test_pm_activity_no_log_file(self, tmp_project):
        """Returns empty results when no activity log exists."""
        from projectman.server import pm_activity
        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0

    def test_pm_activity_reads_entries(self, tmp_project):
        """Returns entries from the activity log."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry()])
        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["total"] == 1
        assert len(data["entries"]) == 1

    def test_pm_activity_registered_on_mcp(self):
        """pm_activity is registered as an MCP tool on the server."""
        from projectman.server import mcp

        # FastMCP stores tools — verify pm_activity is among them
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        assert "pm_activity" in tool_names


class TestPmActivityFiltering:
    """US-PRJ-19-2: Supports filtering by item_id and event_type and date range."""

    def test_filter_by_item_id(self, tmp_project):
        """Filtering by item_id returns only entries for that item."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(item_id="US-TST-1"),
            _make_entry(item_id="US-TST-2"),
            _make_entry(item_id="US-TST-1"),
        ])
        result = pm_activity(item_id="US-TST-1")
        data = yaml.safe_load(result)
        assert data["total"] == 2
        assert all("US-TST-1" in e for e in data["entries"])

    def test_filter_by_item_id_no_match(self, tmp_project):
        """Filtering by a non-existent item_id returns empty results."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(item_id="US-TST-1")])
        result = pm_activity(item_id="US-TST-999")
        data = yaml.safe_load(result)
        assert data["total"] == 0
        assert data["entries"] == []

    def test_filter_by_event_type(self, tmp_project):
        """Filtering by event_type returns only matching events."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(event_type=EventType.create),
            _make_entry(event_type=EventType.update),
            _make_entry(event_type=EventType.create),
            _make_entry(event_type=EventType.archive),
        ])
        result = pm_activity(event_type="create")
        data = yaml.safe_load(result)
        assert data["total"] == 2
        assert all("CREATE" in e for e in data["entries"])

    def test_filter_by_event_type_no_match(self, tmp_project):
        """Filtering by an event_type with no matches returns empty."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(event_type=EventType.create)])
        result = pm_activity(event_type="delete")
        data = yaml.safe_load(result)
        assert data["total"] == 0

    def test_filter_by_from_date(self, tmp_project):
        """from_date excludes entries before the given date."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ])
        result = pm_activity(from_date="2026-02-01T00:00:00+00:00")
        data = yaml.safe_load(result)
        assert data["total"] == 2

    def test_filter_by_to_date(self, tmp_project):
        """to_date excludes entries after the given date."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ])
        result = pm_activity(to_date="2026-02-01T00:00:00+00:00")
        data = yaml.safe_load(result)
        assert data["total"] == 1

    def test_filter_by_date_range(self, tmp_project):
        """Combining from_date and to_date filters to a date range."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 4, 1, tzinfo=timezone.utc)),
        ])
        result = pm_activity(from_date="2026-02-01T00:00:00+00:00", to_date="2026-03-15T00:00:00+00:00")
        data = yaml.safe_load(result)
        assert data["total"] == 2

    def test_combined_item_id_and_event_type(self, tmp_project):
        """Filters can be combined: item_id + event_type."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(item_id="US-TST-1", event_type=EventType.create),
            _make_entry(item_id="US-TST-1", event_type=EventType.update),
            _make_entry(item_id="US-TST-2", event_type=EventType.create),
        ])
        result = pm_activity(item_id="US-TST-1", event_type="update")
        data = yaml.safe_load(result)
        assert data["total"] == 1
        assert "UPDATE" in data["entries"][0]
        assert "US-TST-1" in data["entries"][0]

    def test_combined_all_filters(self, tmp_project):
        """All filters can be combined: item_id + event_type + date range."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(item_id="US-TST-1", event_type=EventType.create,
                        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _make_entry(item_id="US-TST-1", event_type=EventType.update,
                        timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc)),
            _make_entry(item_id="US-TST-1", event_type=EventType.update,
                        timestamp=datetime(2026, 4, 1, tzinfo=timezone.utc)),
            _make_entry(item_id="US-TST-2", event_type=EventType.update,
                        timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc)),
        ])
        result = pm_activity(item_id="US-TST-1", event_type="update",
                             from_date="2026-02-01T00:00:00+00:00",
                             to_date="2026-03-01T00:00:00+00:00")
        data = yaml.safe_load(result)
        assert data["total"] == 1
        assert "US-TST-1" in data["entries"][0]
        assert "UPDATE" in data["entries"][0]


class TestPmActivityFormattedOutput:
    """US-PRJ-19-3: Returns formatted human-readable output with timestamps."""

    def test_entry_contains_timestamp(self, tmp_project):
        """Each formatted entry includes the ISO 8601 timestamp in brackets."""
        from projectman.server import pm_activity

        ts = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        _seed_log(tmp_project, [_make_entry(timestamp=ts)])
        result = pm_activity()
        data = yaml.safe_load(result)
        entry = data["entries"][0]
        assert "2026-03-01" in entry
        assert "14:30" in entry

    def test_entry_starts_with_bracketed_timestamp(self, tmp_project):
        """Formatted entries start with [timestamp] for readability."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry()])
        result = pm_activity()
        data = yaml.safe_load(result)
        entry = data["entries"][0]
        assert entry.startswith("[")
        assert "]" in entry

    def test_entry_contains_event_type_uppercased(self, tmp_project):
        """Event type is displayed in uppercase for visibility."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(event_type=EventType.update)])
        result = pm_activity()
        data = yaml.safe_load(result)
        entry = data["entries"][0]
        assert "UPDATE" in entry

    def test_entry_contains_item_type_and_id(self, tmp_project):
        """Formatted entry includes the item type and item ID."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(item_id="US-TST-5", item_type=ItemType.story)])
        result = pm_activity()
        data = yaml.safe_load(result)
        entry = data["entries"][0]
        assert "US-TST-5" in entry
        assert "story" in entry

    def test_entry_contains_actor(self, tmp_project):
        """Formatted entry includes 'by {actor}' when actor is present."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(actor="alice")])
        result = pm_activity()
        data = yaml.safe_load(result)
        entry = data["entries"][0]
        assert "by alice" in entry

    def test_entry_shows_changes_with_before_after(self, tmp_project):
        """Changes with before/after are displayed as 'field: before → after'."""
        from projectman.server import pm_activity

        entry = _make_entry(
            event_type=EventType.update,
            changes={"status": {"before": "todo", "after": "in-progress"}},
        )
        _seed_log(tmp_project, [entry])
        result = pm_activity()
        data = yaml.safe_load(result)
        formatted = data["entries"][0]
        assert "status:" in formatted
        assert "todo" in formatted
        assert "in-progress" in formatted

    def test_result_includes_pagination_info(self, tmp_project):
        """Result includes a 'showing' field with pagination range."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(), _make_entry(), _make_entry()])
        result = pm_activity(limit=2)
        data = yaml.safe_load(result)
        assert "showing" in data
        assert "of 3" in data["showing"]

    def test_result_includes_total_count(self, tmp_project):
        """Result includes total count of matching entries."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [_make_entry(), _make_entry()])
        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["total"] == 2

    def test_multiple_entries_each_have_timestamps(self, tmp_project):
        """Every entry in a multi-entry result includes a timestamp."""
        from projectman.server import pm_activity

        entries = [
            _make_entry(timestamp=datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 2, 20, 16, 45, 0, tzinfo=timezone.utc)),
            _make_entry(timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)),
        ]
        _seed_log(tmp_project, entries)
        result = pm_activity()
        data = yaml.safe_load(result)
        for entry in data["entries"]:
            # Each entry should start with a bracketed timestamp
            assert entry.startswith("[")
            assert "2026-0" in entry

    def test_entries_are_reverse_chronological(self, tmp_project):
        """Entries are returned most-recent-first."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(item_id="US-TST-OLD", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _make_entry(item_id="US-TST-NEW", timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ])
        result = pm_activity()
        data = yaml.safe_load(result)
        assert "US-TST-NEW" in data["entries"][0]
        assert "US-TST-OLD" in data["entries"][1]


class TestPmActivityGracefulHandling:
    """US-PRJ-19-4: Handles empty or missing log file gracefully."""

    def test_missing_log_file_returns_empty(self, tmp_project):
        """When no activity.jsonl exists, returns empty entries without error."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        assert not log_path.exists()

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0
        assert "No activity log found" in data.get("message", "")

    def test_missing_log_file_does_not_raise(self, tmp_project):
        """pm_activity never raises an exception for a missing log."""
        from projectman.server import pm_activity

        result = pm_activity()
        assert "error:" not in result

    def test_empty_log_file(self, tmp_project):
        """An empty activity.jsonl file returns empty entries without error."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        log_path.write_text("")

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0
        assert "error:" not in result

    def test_log_file_with_only_whitespace(self, tmp_project):
        """A log file containing only whitespace/blank lines returns empty."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        log_path.write_text("\n\n  \n\n")

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0

    def test_malformed_json_lines_are_skipped(self, tmp_project):
        """Lines with invalid JSON are silently skipped."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        valid_entry = _make_entry()
        append_log_entry(log_path, valid_entry)

        # Append a malformed line
        with open(log_path, "a") as f:
            f.write("this is not valid json\n")

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["total"] == 1
        assert len(data["entries"]) == 1
        assert "error:" not in result

    def test_all_lines_malformed(self, tmp_project):
        """If every line is malformed JSON, returns empty results gracefully."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        log_path.write_text("not json\nalso not json\n{broken\n")

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0

    def test_filters_work_with_missing_log(self, tmp_project):
        """Applying filters when the log file is missing still returns gracefully."""
        from projectman.server import pm_activity

        result = pm_activity(item_id="US-TST-1", event_type="create",
                             from_date="2026-01-01", to_date="2026-12-31")
        data = yaml.safe_load(result)
        assert data["entries"] == []
        assert data["total"] == 0

    def test_mixed_valid_and_empty_lines(self, tmp_project):
        """Valid entries interspersed with empty lines are parsed correctly."""
        from projectman.server import pm_activity

        log_path = tmp_project / ".project" / "activity.jsonl"
        valid_entry = _make_entry()
        append_log_entry(log_path, valid_entry)

        # Insert blank lines
        with open(log_path, "a") as f:
            f.write("\n\n")

        append_log_entry(log_path, _make_entry(item_id="US-TST-2"))

        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["total"] == 2
        assert len(data["entries"]) == 2


class TestPmActivityPagination:
    """US-PRJ-19-5: Pagination via limit/offset parameters."""

    def _seed_numbered(self, tmp_project, count):
        """Seed `count` entries with sequential item IDs and timestamps."""
        from datetime import timedelta

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        entries = [
            _make_entry(
                item_id=f"US-TST-{i}",
                timestamp=base + timedelta(hours=i),
            )
            for i in range(1, count + 1)
        ]
        _seed_log(tmp_project, entries)

    def test_default_limit_is_20(self, tmp_project):
        """Without explicit limit, at most 20 entries are returned."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 25)
        result = pm_activity()
        data = yaml.safe_load(result)
        assert data["total"] == 25
        assert len(data["entries"]) == 20

    def test_custom_limit(self, tmp_project):
        """A custom limit restricts the number of returned entries."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 10)
        result = pm_activity(limit=3)
        data = yaml.safe_load(result)
        assert data["total"] == 10
        assert len(data["entries"]) == 3

    def test_limit_larger_than_total(self, tmp_project):
        """A limit larger than total returns all entries."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 5)
        result = pm_activity(limit=100)
        data = yaml.safe_load(result)
        assert data["total"] == 5
        assert len(data["entries"]) == 5

    def test_offset_skips_entries(self, tmp_project):
        """Offset skips the first N entries (most-recent-first)."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 5)
        # Without offset: most recent first → US-TST-5, US-TST-4, ...
        result_all = pm_activity(limit=100)
        all_entries = yaml.safe_load(result_all)["entries"]

        result_offset = pm_activity(offset=2, limit=100)
        offset_data = yaml.safe_load(result_offset)
        assert offset_data["total"] == 5
        assert len(offset_data["entries"]) == 3
        assert offset_data["entries"] == all_entries[2:]

    def test_limit_and_offset_combined(self, tmp_project):
        """Limit and offset work together for paging through results."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 10)

        # Page 1: offset=0, limit=3
        page1 = yaml.safe_load(pm_activity(offset=0, limit=3))
        assert len(page1["entries"]) == 3
        assert page1["total"] == 10

        # Page 2: offset=3, limit=3
        page2 = yaml.safe_load(pm_activity(offset=3, limit=3))
        assert len(page2["entries"]) == 3
        assert page2["total"] == 10

        # Pages should not overlap
        assert set(page1["entries"]) & set(page2["entries"]) == set()

    def test_offset_beyond_total_returns_empty(self, tmp_project):
        """An offset >= total entries returns empty list."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 5)
        result = pm_activity(offset=10)
        data = yaml.safe_load(result)
        assert data["total"] == 5
        assert data["entries"] == []

    def test_showing_field_reflects_pagination(self, tmp_project):
        """The 'showing' field accurately reflects offset and limit."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 10)

        data = yaml.safe_load(pm_activity(offset=0, limit=3))
        assert data["showing"] == "1-3 of 10"

        data = yaml.safe_load(pm_activity(offset=3, limit=3))
        assert data["showing"] == "4-6 of 10"

        data = yaml.safe_load(pm_activity(offset=8, limit=5))
        assert data["showing"] == "9-10 of 10"

    def test_showing_field_empty_when_offset_beyond(self, tmp_project):
        """The 'showing' field says '0 of 0' when no entries match pagination."""
        from projectman.server import pm_activity

        self._seed_numbered(tmp_project, 3)
        data = yaml.safe_load(pm_activity(offset=10))
        assert data["showing"] == "0 of 0"

    def test_pagination_with_filters(self, tmp_project):
        """Pagination applies after filtering — total reflects filtered count."""
        from projectman.server import pm_activity

        _seed_log(tmp_project, [
            _make_entry(item_id="US-TST-A", event_type=EventType.create,
                        timestamp=datetime(2026, 1, 1, i, tzinfo=timezone.utc))
            for i in range(8)
        ] + [
            _make_entry(item_id="US-TST-B", event_type=EventType.update,
                        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        ])
        result = pm_activity(item_id="US-TST-A", limit=3, offset=0)
        data = yaml.safe_load(result)
        assert data["total"] == 8
        assert len(data["entries"]) == 3
