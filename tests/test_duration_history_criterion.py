"""Acceptance criterion for US-PM-50 (task US-PM-50-1).

    > A store function returns per-points p50, p90 and count of grab-to-done
    > minutes computed from orchestrated status transitions in activity.jsonl

End-to-end against the store layer rather than the reader in isolation:
the tasks are created through real ``Store`` writes into a ``tmp_path``
project, and the transitions are appended with the *same* writer the store
uses (``LogEntry`` + ``append_log_entry``), so the record shape under test
is the one production writes rather than a hand-typed imitation of it.  The
unit tests in ``test_duration_history.py`` cover the reader's edge cases —
this file only pins the criterion, and the falsification that goes with it.

"A store function": there is no ``Store.duration_history`` method; the
function lives in :mod:`projectman.durations`, takes a ``Store`` and reads
that store's project directory, which is the store-layer entry point the
criterion is satisfied by.  Asserted below so the wording is checked, not
assumed.
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from projectman.activity_log import append_log_entry
from projectman.durations import duration_history
from projectman.models import LogEntry
from projectman.store import Store

BASE = datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc)

#: (task, run id, minutes from BASE to the grab, minutes the task ran).
#: Two 1-pointers, five 2-pointers, one orchestrated 3-pointer and one
#: 3-pointer worked by hand — the last is the transition that must not be
#: counted.
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


@pytest.fixture
def store(tmp_project):
    """A real store holding one 1-, one 2- and one 3-point task."""
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "d", points=1)  # US-TST-1-1
    store.create_task("US-TST-1", "Two pointer", "d", points=2)  # US-TST-1-2
    store.create_task("US-TST-1", "Three pointer", "d", points=3)  # US-TST-1-3
    return store


def test_criterion_per_points_p50_p90_and_count_of_grab_to_done_minutes(store):
    """Per-points p50, p90 and n, in minutes, from orch- transitions only."""
    _write_history(store, TRANSITIONS)

    history = duration_history(store)

    by_points = history["by_points"]
    assert set(by_points) == {1, 2, 3}
    # 1 point: [10, 20] -> nearest rank p50 is the 1st, p90 the 2nd.
    assert by_points[1]["p50"] == 10.0
    assert by_points[1]["p90"] == 20.0
    assert by_points[1]["n"] == 2
    # 2 points: [4, 8, 15, 30, 90] -> p50 the 3rd, p90 the 5th.
    assert by_points[2]["p50"] == 15.0
    assert by_points[2]["p90"] == 90.0
    assert by_points[2]["n"] == 5
    # 3 points: the 300-minute stretch was worked under "human-2026-09-09",
    # so only the orchestrated 45-minute one is a measurement.
    assert by_points[3] == {"p50": 45.0, "p90": 45.0, "max": 45.0, "n": 1}
    assert history["n"] == 8


def test_criterion_falsified_when_no_transition_is_orchestrated(store):
    """The same history without the orch- prefix yields nothing to report."""
    _write_history(
        store,
        [
            (item_id, run_id.replace("orch-", ""), start, ran)
            for item_id, run_id, start, ran in TRANSITIONS
        ],
    )

    assert duration_history(store) == {"by_points": {}, "n": 0}


def test_the_function_is_reachable_from_the_store_layer(store):
    """It takes a Store and reads that store's project directory."""
    parameters = list(inspect.signature(duration_history).parameters)
    assert parameters == ["store"]
    assert duration_history(store)["n"] == 0  # a real Store, empty history
