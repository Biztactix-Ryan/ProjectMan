"""US-PM-50-9: the sprint view flags tasks whose band usually overruns.

    > The sprint view lists tasks whose points band has p90 above
    > orchestrate.max_task_minutes (default 60) under long_task_risk

The history is seeded the way ``test_duration_history_criterion.py`` seeds
it — real ``Store`` writes into a ``tmp_path`` project, transitions appended
through ``LogEntry`` + ``append_log_entry`` — so what is measured is the
record shape production writes.  Both entry points are covered: the reusable
``durations.long_task_risk`` (which US-PM-50-10 will call from ``pm_audit``)
and ``pm_get_sprint``, which must always carry the key.
"""

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from projectman.activity_log import append_log_entry
from projectman.durations import long_task_risk
from projectman.models import LogEntry
from projectman.store import Store

BASE = datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc)

RUN = "orch-2026-09-09-385a"

#: (task, minutes from BASE to the grab, minutes the task ran).  One-pointers
#: are quick, two-pointers have five samples with a 90-minute tail, and the
#: three-pointers have only two samples — slow ones, but too few to judge by.
TRANSITIONS = [
    ("US-TST-1-1", 0, 10),
    ("US-TST-1-1", 60, 20),
    ("US-TST-1-1", 120, 15),
    ("US-TST-1-2", 180, 4),
    ("US-TST-1-2", 240, 8),
    ("US-TST-1-2", 300, 15),
    ("US-TST-1-2", 360, 30),
    ("US-TST-1-2", 420, 90),
    ("US-TST-1-3", 600, 120),
    ("US-TST-1-3", 780, 130),
]


def _append(store, item_id, minute, changes):
    append_log_entry(
        store.project_dir / "activity.jsonl",
        LogEntry(
            event_type="update",
            item_id=item_id,
            item_type="task",
            changes=changes,
            timestamp=BASE + timedelta(minutes=minute),
            actor="claude",
            source="cli",
            run_id=RUN,
        ),
    )


def _write_history(store, transitions=TRANSITIONS):
    """Write a grab/done pair per transition, in chronological order."""
    for item_id, start, ran in transitions:
        _append(
            store,
            item_id,
            start,
            {
                "assignee": {"before": None, "after": "claude"},
                "status": {"before": "todo", "after": "in-progress"},
            },
        )
        _append(
            store,
            item_id,
            start + ran,
            {"status": {"before": "in-progress", "after": "done"}},
        )


@pytest.fixture
def store(tmp_project):
    """A story of six tasks, planned into a sprint.

    ``US-TST-1-1`` (1pt), ``US-TST-1-2`` (2pt) and ``US-TST-1-3`` (3pt) carry
    the history; ``-4`` is a second open two-pointer, ``-5`` a finished one
    and ``-6`` an abandoned one.
    """
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "d", points=1)
    store.create_task("US-TST-1", "Two pointer", "d", points=2)
    store.create_task("US-TST-1", "Three pointer", "d", points=3)
    store.create_task("US-TST-1", "Another two pointer", "d", points=2)
    store.create_task("US-TST-1", "Delivered two pointer", "d", points=2)
    store.create_task("US-TST-1", "Abandoned two pointer", "d", points=2)
    store.update("US-TST-1-5", status="done")
    store.archive("US-TST-1-6")
    store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
    return store


def _sprint(store):
    meta, _ = store.get_sprint("SPRINT-TST-1")
    return meta


def test_flags_the_open_tasks_of_a_band_whose_p90_is_over_the_ceiling(store):
    """Two-pointers run 4/8/15/30/90 — p90 90 is over the 60-minute default."""
    _write_history(store)

    flagged = long_task_risk(store, _sprint(store))

    assert [entry["id"] for entry in flagged] == ["US-TST-1-2", "US-TST-1-4"]
    assert flagged[0] == {
        "id": "US-TST-1-2",
        "points": 2,
        "p50": 15.0,
        "p90": 90.0,
        "max_task_minutes": 60.0,
    }
    assert flagged[1]["p90"] == 90.0


def test_a_band_under_the_ceiling_is_not_flagged(store):
    """One-pointers peak at 20 minutes: nothing to split there."""
    _write_history(store)

    flagged = long_task_risk(store, _sprint(store))

    assert "US-TST-1-1" not in [entry["id"] for entry in flagged]


def test_a_band_with_fewer_than_three_samples_is_skipped(store):
    """Three-pointers took 120 and 130 minutes — slow, but two samples is
    not a p90, and flagging on it would cry wolf on a young project."""
    _write_history(store)

    flagged = long_task_risk(store, _sprint(store))

    assert "US-TST-1-3" not in [entry["id"] for entry in flagged]


def test_done_and_archived_tasks_are_not_flagged(store):
    """Only open work can be re-scoped."""
    _write_history(store)

    ids = [entry["id"] for entry in long_task_risk(store, _sprint(store))]

    assert "US-TST-1-5" not in ids  # done
    assert "US-TST-1-6" not in ids  # archived


def test_raising_max_task_minutes_clears_the_flag(store, tmp_project):
    """The ceiling is `orchestrate.max_task_minutes`, read from config."""
    _write_history(store)
    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["orchestrate"] = {"max_task_minutes": 200}
    config_path.write_text(yaml.dump(config))

    relaxed = Store(tmp_project)

    assert relaxed.config.orchestrate.max_task_minutes == 200
    assert long_task_risk(relaxed, _sprint(relaxed)) == []


def test_no_history_flags_nothing(store):
    """An empty log is not evidence that anything runs long."""
    assert long_task_risk(store, _sprint(store)) == []


class TestThroughPmGetSprint:
    """The key is always on the sprint view, flagged or not."""

    @staticmethod
    def _cold(tmp_project, monkeypatch):
        monkeypatch.chdir(tmp_project)
        from projectman.server import _store_cache
        from projectman.store import _cache

        _store_cache.clear()
        _cache.clear()

    def test_lists_the_flagged_tasks(self, store, tmp_project, monkeypatch):
        _write_history(store)
        self._cold(tmp_project, monkeypatch)
        from projectman.server import pm_get_sprint

        result = yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))

        assert result["long_task_risk"] == [
            {
                "id": "US-TST-1-2",
                "points": 2,
                "p50": 15.0,
                "p90": 90.0,
                "max_task_minutes": 60.0,
            },
            {
                "id": "US-TST-1-4",
                "points": 2,
                "p50": 15.0,
                "p90": 90.0,
                "max_task_minutes": 60.0,
            },
        ]

    def test_key_is_present_and_empty_when_nothing_is_flagged(
        self, store, tmp_project, monkeypatch
    ):
        self._cold(tmp_project, monkeypatch)
        from projectman.server import pm_get_sprint

        result = yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))

        assert result["long_task_risk"] == []
