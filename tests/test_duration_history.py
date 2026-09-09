"""Per-points grab-to-done duration history (US-PM-50-6).

The input is a synthetic ``activity.jsonl`` written straight into a
``tmp_path`` store: the real log is history, and a test that had to *make*
history by driving the store would be pinning the store's write path rather
than this module's read path.  Writing the lines by hand also makes the
awkward cases — an unpaired close, a corrupt line, a human-run transition —
one line each instead of a scenario.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from projectman.durations import duration_history, task_durations
from projectman.store import Store

BASE = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


def _line(
    item_id,
    after,
    minute,
    *,
    run_id="orch-2026-09-09-1",
    before=None,
    item_type="task",
    event_type="update",
    changes=...,
):
    """One activity-log event, ``minute`` minutes after BASE."""
    if changes is ...:
        changes = {"status": {"before": before, "after": after}}
    entry = {
        "event_type": event_type,
        "item_id": item_id,
        "item_type": item_type,
        "changes": changes,
        "timestamp": (BASE + timedelta(minutes=minute))
        .isoformat()
        .replace("+00:00", "Z"),
        "actor": "tester",
        "source": "cli",
    }
    if run_id is not None:
        entry["run_id"] = run_id
    return json.dumps(entry)


def _write_log(store, lines):
    (store.project_dir / "activity.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture
def seeded(tmp_project):
    """A store with four pointed tasks, one of them archived."""
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "d", points=1)  # US-TST-1-1
    store.create_task("US-TST-1", "Two pointer", "d", points=2)  # -2
    store.create_task("US-TST-1", "Another two", "d", points=2)  # -3
    store.create_task("US-TST-1", "Archived three", "d", points=3)  # -4
    store.archive("US-TST-1-4")
    return store


def test_pairs_in_progress_with_done(seeded):
    """One claim and one close become one duration in the task's band."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, before="todo"),
            _line("US-TST-1-1", "done", 12, before="in-progress"),
        ],
    )

    history = duration_history(seeded)

    assert history["n"] == 1
    assert history["by_points"][1] == {"p50": 12.0, "p90": 12.0, "max": 12.0, "n": 1}


def test_review_closes_a_stretch_too(seeded):
    """A hand-back for review ends the worker's stretch, same as done."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, before="todo"),
            _line("US-TST-1-1", "review", 7, before="in-progress"),
        ],
    )

    assert duration_history(seeded)["by_points"][1]["p50"] == 7.0


def test_only_orch_runs_are_counted(seeded):
    """A human's transitions, and unstamped ones, are not measurements."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, run_id=None),
            _line("US-TST-1-1", "done", 600, run_id=None),
            _line("US-TST-1-2", "in-progress", 0, run_id="manual-2026"),
            _line("US-TST-1-2", "done", 900, run_id="manual-2026"),
        ],
    )

    assert duration_history(seeded) == {"by_points": {}, "n": 0}


def test_unpaired_and_unparseable_transitions_are_skipped(seeded):
    """A close with no claim, a claim never closed, junk lines: no raise."""
    (seeded.project_dir / "activity.jsonl").write_text(
        "\n".join(
            [
                "{not json at all",
                "[1, 2, 3]",
                "",
                _line("US-TST-1-1", "done", 5, before="in-progress"),  # no claim
                _line("US-TST-1-2", "in-progress", 0, before="todo"),  # never closed
                _line("US-TST-1-3", "in-progress", 0, before="todo"),
                # A claim whose timestamp cannot be parsed, then a real pair.
                _line("US-TST-1-3", "done", 4, before="in-progress").replace(
                    '"timestamp": "2026', '"timestamp": "not-a-time'
                ),
                _line("US-TST-1-3", "done", 9, before="in-progress"),
            ]
        )
        + "\n"
    )

    history = duration_history(seeded)

    assert history["n"] == 1
    assert history["by_points"][2]["n"] == 1
    assert history["by_points"][2]["p50"] == 9.0


def test_events_that_are_not_task_status_updates_are_ignored(seeded):
    """Creates, story updates and updates with no status change are noise."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", None, 0, event_type="create", changes={}),
            _line("US-TST-1", "done", 1, item_type="story"),
            _line("US-TST-1-1", "in-progress", 2, before="todo"),
            _line("US-TST-1-1", None, 3, changes={"points": {"before": 1, "after": 2}}),
            _line("US-TST-1-1", None, 4, changes="not a dict"),
            _line("US-TST-1-1", "done", 10, before="in-progress"),
        ],
    )

    history = duration_history(seeded)

    assert history["n"] == 1
    assert history["by_points"][1]["p50"] == 8.0


def test_a_re_grab_restarts_the_clock(seeded):
    """Released and re-claimed: the attempt that finished is what's measured."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, before="todo"),
            _line("US-TST-1-1", "in-progress", 30, before="todo"),
            _line("US-TST-1-1", "done", 35, before="in-progress"),
        ],
    )

    assert duration_history(seeded)["by_points"][1]["p50"] == 5.0


def test_groups_by_points_including_an_archived_task(seeded):
    """Bands come from the task files, and archived history still counts."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, before="todo"),
            _line("US-TST-1-1", "done", 3, before="in-progress"),
            _line("US-TST-1-2", "in-progress", 0, before="todo"),
            _line("US-TST-1-2", "done", 20, before="in-progress"),
            _line("US-TST-1-4", "in-progress", 0, before="todo"),
            _line("US-TST-1-4", "done", 44, before="in-progress"),
            # A task that no longer has a file on disk: no band, no crash.
            _line("US-TST-1-99", "in-progress", 0, before="todo"),
            _line("US-TST-1-99", "done", 500, before="in-progress"),
        ],
    )

    history = duration_history(seeded)

    assert list(history["by_points"]) == [1, 2, 3]
    assert history["by_points"][3] == {"p50": 44.0, "p90": 44.0, "max": 44.0, "n": 1}
    assert history["n"] == 3


def test_percentiles_and_max_over_many_samples(seeded):
    """Nearest-rank p50/p90 over ten samples, with max at the top."""
    lines = []
    for index, minutes in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 100]):
        start = index * 1000
        lines.append(_line("US-TST-1-2", "in-progress", start, before="todo"))
        lines.append(_line("US-TST-1-2", "done", start + minutes, before="in-progress"))
    _write_log(seeded, lines)

    band = duration_history(seeded)["by_points"][2]

    assert band["n"] == 10
    assert band["p50"] == 5.0  # nearest rank: the 5th of 10
    assert band["p90"] == 9.0  # the 9th, not the outlier
    assert band["max"] == 100.0


def test_empty_and_missing_logs_return_no_history(seeded):
    """No log, and an empty log, both mean "no data" rather than an error."""
    log = seeded.project_dir / "activity.jsonl"
    log.unlink(missing_ok=True)
    assert duration_history(seeded) == {"by_points": {}, "n": 0}

    log.write_text("")
    assert duration_history(seeded) == {"by_points": {}, "n": 0}
    assert task_durations(seeded) == []


def test_rotated_siblings_are_read_before_the_live_log(seeded):
    """A stretch that spans rotation is still one measurement."""
    (seeded.project_dir / "activity-20260909-100000.jsonl").write_text(
        _line("US-TST-1-1", "in-progress", 0, before="todo") + "\n"
    )
    _write_log(seeded, [_line("US-TST-1-1", "done", 15, before="in-progress")])

    assert duration_history(seeded)["by_points"][1]["p50"] == 15.0


def test_naive_timestamps_and_clock_skew(seeded):
    """Offset-less lines still pair; a negative span is dropped, not raised."""
    _write_log(
        seeded,
        [
            _line("US-TST-1-1", "in-progress", 0, before="todo").replace("Z\"", "\""),
            _line("US-TST-1-1", "done", 6, before="in-progress").replace("Z\"", "\""),
            _line("US-TST-1-2", "in-progress", 60, before="todo"),
            _line("US-TST-1-2", "done", 10, before="in-progress"),
        ],
    )

    history = duration_history(seeded)

    assert history["n"] == 1
    assert history["by_points"][1]["p50"] == 6.0
    assert 2 not in history["by_points"]
