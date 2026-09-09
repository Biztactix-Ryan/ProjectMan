"""Acceptance criterion for US-PM-50 (task US-PM-50-2).

    > pm_estimate and pm_scope include duration_history for the project
    > alongside estimation_guidance

Checked at the MCP tool boundary: the two tool functions are imported from
:mod:`projectman.server` and called against a ``tmp_path`` project, so what
is asserted is the YAML a client actually receives — not the return value of
``estimator.estimate`` / ``scoper.scope``, which ``test_estimator.py`` covers
as units (US-PM-50-8).

"alongside estimation_guidance" is the criterion's wording and it is exact
for ``pm_estimate``; ``pm_scope`` has never had an ``estimation_guidance``
key — its advice block is ``decomposition_guidance``.  Both are asserted for
what is really there, including the absence, so the discrepancy is pinned
rather than papered over.

The history itself is seeded with the *store's own* log writer (``LogEntry``
+ ``append_log_entry``, as in ``test_duration_history_criterion.py``) rather
than hand-typed JSON, so the record shape under test is the one production
writes.
"""

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from projectman.activity_log import append_log_entry
from projectman.models import LogEntry
from projectman.store import Store

BASE = datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc)

#: (task, run id, minutes from BASE to the grab, minutes the task ran).
#: Two 1-pointers, five 2-pointers, one orchestrated 3-pointer and one
#: 3-pointer worked by hand — the last is not machine-paced and so is not a
#: measurement the tools may report.
TRANSITIONS = [
    ("US-TST-1-1", "orch-2026-09-09-385a", 0, 10),
    ("US-TST-1-1", "orch-2026-09-09-385a", 60, 20),
    ("US-TST-1-2", "orch-2026-09-09-385a", 120, 4),
    ("US-TST-1-2", "orch-2026-09-09-385a", 180, 8),
    ("US-TST-1-2", "orch-2026-09-09-385a", 240, 15),
    ("US-TST-1-2", "orch-2026-09-09-385a", 300, 30),
    ("US-TST-1-2", "orch-2026-09-09-385a", 360, 90),
    ("US-TST-1-3", "orch-2026-09-09-385a", 480, 45),
    ("US-TST-1-3", "human-2026-09-09", 600, 300),
]

#: What ``TRANSITIONS`` must come back as, per points band.  Percentiles are
#: nearest-rank: 1pt [10, 20] -> 1st and 2nd; 2pt [4, 8, 15, 30, 90] -> 3rd
#: and 5th; 3pt only the orchestrated 45.
EXPECTED_BANDS = {
    1: {"p50": 10.0, "p90": 20.0, "max": 20.0, "n": 2},
    2: {"p50": 15.0, "p90": 90.0, "max": 90.0, "n": 5},
    3: {"p50": 45.0, "p90": 45.0, "max": 45.0, "n": 1},
}


def _append(store, item_id, run_id, minute, changes):
    """Append one status-change event through the store's own log writer."""
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
            run_id=run_id,
        ),
    )


def _write_history(store, transitions):
    """Write a grab/done pair per transition, in chronological order."""
    for item_id, run_id, start, ran in transitions:
        _append(
            store,
            item_id,
            run_id,
            start,
            # A grab moves the assignee at the same time as the status, the
            # way pm_grab's log line does.
            {
                "assignee": {"before": None, "after": "claude"},
                "status": {"before": "todo", "after": "in-progress"},
            },
        )
        _append(
            store,
            item_id,
            run_id,
            start + ran,
            {"status": {"before": "in-progress", "after": "done"}},
        )


def _seed(tmp_project, transitions):
    """A store holding one 1-, one 2- and one 3-point task, plus history."""
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "d", points=1)  # US-TST-1-1
    store.create_task("US-TST-1", "Two pointer", "d", points=2)  # US-TST-1-2
    store.create_task("US-TST-1", "Three pointer", "d", points=3)  # US-TST-1-3
    _write_history(store, transitions)
    return store


def _cold(tmp_project, monkeypatch):
    """Point the server's module-level store at *tmp_project*, cache-free."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()


def _call(tool_name, item_id):
    """Invoke a server tool function by name and parse its YAML."""
    import projectman.server as server

    return yaml.safe_load(getattr(server, tool_name)(item_id))


@pytest.fixture
def full_history(tmp_project, monkeypatch):
    """Eight orchestrated measurements — over MIN_HISTORY_SAMPLES."""
    _seed(tmp_project, TRANSITIONS)
    _cold(tmp_project, monkeypatch)
    return tmp_project


def test_pm_estimate_returns_duration_history_alongside_estimation_guidance(
    full_history,
):
    """The criterion, verbatim, for pm_estimate."""
    data = _call("pm_estimate", "US-TST-1")

    assert "estimation_guidance" in data
    assert "duration_history" in data
    # Alongside, not instead of: the guidance is intact.
    assert data["estimation_guidance"]["fibonacci_scale"] == [1, 2, 3, 5, 8, 13]
    assert data["duration_history"]["by_points"] == EXPECTED_BANDS
    assert data["duration_history"]["n"] == 8
    assert data["duration_history"]["max_task_minutes"] == 60


def test_pm_scope_returns_duration_history_alongside_its_guidance(full_history):
    """The criterion for pm_scope, against the key that is actually there.

    pm_scope's advice block is ``decomposition_guidance``; it carries no
    ``estimation_guidance`` and never has.
    """
    data = _call("pm_scope", "US-TST-1")

    assert "decomposition_guidance" in data
    assert "estimation_guidance" not in data
    assert "duration_history" in data
    assert "rules" in data["decomposition_guidance"]
    assert data["duration_history"]["by_points"] == EXPECTED_BANDS
    assert data["duration_history"]["n"] == 8
    assert data["duration_history"]["max_task_minutes"] == 60


def test_both_tools_report_the_same_project_wide_block(full_history):
    """The history is the project's, so the two tools cannot disagree."""
    assert (
        _call("pm_estimate", "US-TST-1")["duration_history"]
        == _call("pm_scope", "US-TST-1")["duration_history"]
    )


@pytest.mark.parametrize("tool_name", ["pm_estimate", "pm_scope"])
def test_no_note_once_three_or_more_tasks_have_been_measured(
    full_history, tool_name
):
    """At or over the threshold the block is reported without a caveat."""
    history = _call(tool_name, "US-TST-1")["duration_history"]

    assert history["n"] >= 3
    assert "note" not in history


@pytest.mark.parametrize("tool_name", ["pm_estimate", "pm_scope"])
def test_a_note_appears_while_fewer_than_three_tasks_are_measured(
    tmp_project, monkeypatch, tool_name
):
    """Two measurements is not a history, and the tools say so."""
    _seed(tmp_project, TRANSITIONS[:2])  # both 1-point stretches, n = 2
    _cold(tmp_project, monkeypatch)

    history = _call(tool_name, "US-TST-1")["duration_history"]

    assert history["n"] == 2
    assert "too thin to flag long tasks" in history["note"]
    # The measurements are still reported — the note qualifies them.
    assert history["by_points"] == {1: EXPECTED_BANDS[1]}


@pytest.mark.parametrize("tool_name", ["pm_estimate", "pm_scope"])
def test_the_note_goes_away_at_exactly_three_measurements(
    tmp_project, monkeypatch, tool_name
):
    """The boundary: three is a history, two was not."""
    _seed(tmp_project, TRANSITIONS[:3])
    _cold(tmp_project, monkeypatch)

    history = _call(tool_name, "US-TST-1")["duration_history"]

    assert history["n"] == 3
    assert "note" not in history


@pytest.mark.parametrize("tool_name", ["pm_estimate", "pm_scope"])
def test_an_unmeasured_project_reports_an_empty_history_with_the_note(
    tmp_project, monkeypatch, tool_name
):
    """Falsification: no orchestrated transitions, nothing to report."""
    _seed(
        tmp_project,
        [
            (item_id, run_id.replace("orch-", ""), start, ran)
            for item_id, run_id, start, ran in TRANSITIONS
        ],
    )
    _cold(tmp_project, monkeypatch)

    history = _call(tool_name, "US-TST-1")["duration_history"]

    assert history["by_points"] == {}
    assert history["n"] == 0
    assert "too thin to flag long tasks" in history["note"]


def test_pm_estimate_carries_the_history_for_a_task_id_too(full_history):
    """A task ID resolves through the same tool and gets the same block."""
    data = _call("pm_estimate", "US-TST-1-1")

    assert data["item"]["id"] == "US-TST-1-1"
    assert data["duration_history"]["by_points"] == EXPECTED_BANDS
