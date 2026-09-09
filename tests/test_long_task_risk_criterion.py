"""Acceptance criterion for US-PM-50 (task US-PM-50-3).

    > The sprint view lists tasks whose points band has p90 above
    > orchestrate.max_task_minutes (default 60) under long_task_risk

Pinned at the ``pm_get_sprint`` tool boundary — the "sprint view" the
criterion names — with the YAML parsed back the way a caller reads it.
``test_long_task_risk.py`` (US-PM-50-9) covers the behaviour of the
``durations.long_task_risk`` helper itself and two end-to-end cases; this
file pins only the three specifics the criterion's wording carries:

1. the key is spelled ``long_task_risk``, and it lists tasks of bands whose
   p90 is *above* the ceiling, not at or below it.  Three bands are seeded
   for that single comparison — p90 61 (clearly above), p90 59 (clearly
   below) and p90 60 (exactly at) — so the boundary is pinned rather than
   assumed.  **The implementation compares strictly (``p90 > limit``): the
   band sitting exactly on 60 is not flagged**, asserted below.
2. the ceiling is the ``orchestrate.max_task_minutes`` config key — a real
   ``config.yaml`` in the ``tmp_path`` store is rewritten with an override
   and the flagged set changes accordingly.
3. the default is 60 — the fixture's ``config.yaml`` carries no
   ``orchestrate`` section at all, and the p90-61 band is flagged under it
   while the p90-59 band is not.

History is seeded the way ``test_duration_history_criterion.py`` seeds it:
real ``Store`` writes into a ``tmp_path`` project, transitions appended
through ``LogEntry`` + ``append_log_entry``, so the record shape under test
is the one production writes.
"""

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from projectman.activity_log import append_log_entry
from projectman.models import LogEntry
from projectman.store import Store

BASE = datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc)

RUN = "orch-2026-09-09-385a"

#: Three samples per band — the minimum ``long_task_risk`` will judge on —
#: chosen so each band's nearest-rank p90 (the largest of three) lands on a
#: known side of the 60-minute default:
#:
#:   US-TST-1-1, 1pt: 50/55/59  -> p50 55, p90 59  (clearly below)
#:   US-TST-1-2, 2pt: 30/45/61  -> p50 45, p90 61  (clearly above)
#:   US-TST-1-3, 3pt: 20/40/60  -> p50 40, p90 60  (exactly at)
#:
#: (task, minutes from BASE to the grab, minutes the task ran)
TRANSITIONS = [
    ("US-TST-1-1", 0, 50),
    ("US-TST-1-1", 120, 55),
    ("US-TST-1-1", 240, 59),
    ("US-TST-1-2", 360, 30),
    ("US-TST-1-2", 480, 45),
    ("US-TST-1-2", 600, 61),
    ("US-TST-1-3", 720, 20),
    ("US-TST-1-3", 840, 40),
    ("US-TST-1-3", 960, 60),
]


def _append(store, item_id, minute, changes, run_id=RUN):
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


def _write_history(store, run_id=RUN):
    """Write a grab/done pair per transition, in chronological order."""
    for item_id, start, ran in TRANSITIONS:
        _append(
            store,
            item_id,
            start,
            {
                "assignee": {"before": None, "after": "claude"},
                "status": {"before": "todo", "after": "in-progress"},
            },
            run_id=run_id,
        )
        _append(
            store,
            item_id,
            start + ran,
            {"status": {"before": "in-progress", "after": "done"}},
            run_id=run_id,
        )


@pytest.fixture
def sprint_store(tmp_project):
    """One story of three open tasks — a 1-, a 2- and a 3-pointer — planned
    into a sprint, each band carrying its own three-sample history."""
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "d", points=1)
    store.create_task("US-TST-1", "Two pointer", "d", points=2)
    store.create_task("US-TST-1", "Three pointer", "d", points=3)
    store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
    return store


def _set_max_task_minutes(tmp_project, minutes):
    """Write ``orchestrate.max_task_minutes`` into the store's config.yaml."""
    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["orchestrate"] = {"max_task_minutes": minutes}
    config_path.write_text(yaml.dump(config))


def _sprint_view(tmp_project, monkeypatch):
    """Call the ``pm_get_sprint`` tool against the tmp store, cold.

    Both the server's per-root store cache and the store layer's own cache
    are dropped so the view is built from what is on disk right now — this
    file rewrites config.yaml mid-test.
    """
    monkeypatch.chdir(tmp_project)
    from projectman.config import clear_config_cache
    from projectman.server import _store_cache, pm_get_sprint
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()
    clear_config_cache()
    return yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))


def _flagged(view):
    """The (id, points) pairs the criterion says the view must list."""
    return [(entry["id"], entry["points"]) for entry in view["long_task_risk"]]


def test_criterion_sprint_view_lists_tasks_whose_band_p90_is_above_the_ceiling(
    sprint_store, tmp_project, monkeypatch
):
    """Under the default 60: p90 61 is listed, p90 59 and p90 60 are not.

    This is the whole criterion in one assertion — the key is spelled
    ``long_task_risk``, it carries the task's id and points, and membership
    is decided by the band's p90 against the ceiling.  The 3-point band's
    p90 is *exactly* 60, and it is absent: the comparison is strict
    (``p90 > max_task_minutes``), not ``>=``.
    """
    _write_history(sprint_store)

    view = _sprint_view(tmp_project, monkeypatch)

    assert "long_task_risk" in view
    assert _flagged(view) == [("US-TST-1-2", 2)]
    # The band's own numbers ride along, so the reader can see why.
    assert view["long_task_risk"] == [
        {
            "id": "US-TST-1-2",
            "points": 2,
            "p50": 45.0,
            "p90": 61.0,
            "max_task_minutes": 60.0,
        }
    ]


def test_criterion_default_ceiling_is_60_with_no_config_key(
    sprint_store, tmp_project, monkeypatch
):
    """"(default 60)": with no key on disk the ceiling still lands on 60.

    The store rewrites config.yaml from the parsed model as it allocates
    ids, so the section is re-materialised with its defaults; it is stripped
    back out here so what is on disk is a config.yaml that never mentions
    ``orchestrate`` — the state a project that has never set the key is in.
    """
    _write_history(sprint_store)
    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config.pop("orchestrate", None)
    config_path.write_text(yaml.dump(config))
    assert "orchestrate" not in yaml.safe_load(config_path.read_text())

    view = _sprint_view(tmp_project, monkeypatch)

    # p90 61 is flagged, p90 59 is not — the line is drawn at 60.
    assert [entry["id"] for entry in view["long_task_risk"]] == ["US-TST-1-2"]
    assert view["long_task_risk"][0]["max_task_minutes"] == 60.0


def test_criterion_ceiling_comes_from_orchestrate_max_task_minutes(
    sprint_store, tmp_project, monkeypatch
):
    """Lowering the config key to 55 puts all three bands over it.

    59, 61 and 60 are each above 55, so the same history that flagged one
    task now flags all three: the threshold is read from the config key, not
    hard-coded.
    """
    _write_history(sprint_store)
    _set_max_task_minutes(tmp_project, 55)

    view = _sprint_view(tmp_project, monkeypatch)

    assert _flagged(view) == [
        ("US-TST-1-1", 1),
        ("US-TST-1-2", 2),
        ("US-TST-1-3", 3),
    ]
    assert {entry["max_task_minutes"] for entry in view["long_task_risk"]} == {55.0}


def test_criterion_raising_the_config_key_above_every_p90_flags_nothing(
    sprint_store, tmp_project, monkeypatch
):
    """The other direction: 200 is above all three p90s, so the list empties
    while staying present."""
    _write_history(sprint_store)
    _set_max_task_minutes(tmp_project, 200)

    view = _sprint_view(tmp_project, monkeypatch)

    assert view["long_task_risk"] == []


def test_criterion_falsified_without_orchestrated_history(
    sprint_store, tmp_project, monkeypatch
):
    """The same nine grab/done pairs under a non-orchestrated run id are not
    measurements, so no band has a p90 and nothing is flagged."""
    _write_history(sprint_store, run_id=RUN.replace("orch-", "human-"))

    view = _sprint_view(tmp_project, monkeypatch)

    assert view["long_task_risk"] == []
