"""Open decisions gate readiness: pm_grab, pm_done_next and the board (US-PM-64-7).

Every test runs against the tmp_path-isolated ``tmp_project`` fixture; the
decisions are created and resolved through the Store API, never the real
``.project``.
"""

import pytest
import yaml

from projectman.readiness import check_readiness
from projectman.store import Store

BODY = (
    "## Implementation\n\nDo the thing properly and completely.\n\n"
    "## Testing\n\nTest the thing properly.\n"
)


def _store():
    from projectman.server import _store

    return _store()


@pytest.fixture
def tree(tmp_project, monkeypatch):
    """EPIC-TST-1 > US-TST-1 > US-TST-1-1, US-TST-1-2 (both ready, 1 point)."""
    from projectman.server import (
        pm_create_epic,
        pm_create_story,
        pm_create_tasks,
        pm_update,
    )

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    # Guard before any write: the server must resolve to the tmp store.
    assert str(_store().root).startswith(str(tmp_project))

    pm_create_epic("Epic", "Epic description")
    pm_create_story("Story", "Story description long enough to matter.")
    pm_update("US-TST-1", status="active", epic_id="EPIC-TST-1")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": "Task one", "description": BODY, "points": 1},
            {"title": "Task two", "description": BODY, "points": 1},
        ],
    )
    return _store()


def _grab(task_id):
    from projectman.server import pm_grab

    return yaml.safe_load(pm_grab(task_id))


def _snapshot(store, task_id):
    meta, body = store.get_task(task_id)
    return meta.model_dump(mode="json"), body


@pytest.mark.parametrize("target", ["US-TST-1-1", "US-TST-1", "EPIC-TST-1"])
def test_pm_grab_refuses_a_decision_blocked_task(tree, target):
    tree.create_decision("Which database?", blocks=[target])

    data = _grab("US-TST-1-1")

    assert data["status"] == "not_ready"
    assert "blocked by open decision DEC-TST-1: Which database?" in data["blockers"]
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.status.value == "todo" and meta.assignee is None


def test_every_open_blocking_decision_is_named(tree):
    tree.create_decision("First?", blocks=["US-TST-1-1"])
    tree.create_decision("Second?", blocks=["EPIC-TST-1"])

    blockers = _grab("US-TST-1-1")["blockers"]

    assert blockers == [
        "blocked by open decision DEC-TST-1: First?",
        "blocked by open decision DEC-TST-2: Second?",
    ]


@pytest.mark.parametrize(
    "resolution",
    [{"status": "answered", "answer": "Postgres"}, {"status": "withdrawn"}],
    ids=["answered", "withdrawn"],
)
def test_resolving_the_decision_makes_the_task_grabbable(tree, resolution):
    tree.create_decision("Which database?", blocks=["US-TST-1"])
    assert _grab("US-TST-1-1")["status"] == "not_ready"
    before = _snapshot(tree, "US-TST-1-1")

    tree.update_decision("DEC-TST-1", **resolution)

    # Nothing about the task changed: resolving the decision alone frees it.
    assert _snapshot(tree, "US-TST-1-1") == before
    data = _grab("US-TST-1-1")
    assert data["grabbed"]["task"]["id"] == "US-TST-1-1"
    assert data["grabbed"]["task"]["status"] == "in-progress"


def test_task_without_decisions_is_unaffected(tree):
    tree.create_decision("Unrelated?", blocks=["US-TST-1-2"])

    assert check_readiness(*tree.get_task("US-TST-1-1"), tree)["blockers"] == []
    assert _grab("US-TST-1-1")["grabbed"]["task"]["id"] == "US-TST-1-1"


def test_pm_done_next_skips_a_decision_blocked_task(tree):
    from projectman.server import pm_create_tasks, pm_done_next

    pm_create_tasks(
        "US-TST-1", [{"title": "Task three", "description": BODY, "points": 1}]
    )
    tree.create_decision("Which database?", blocks=["US-TST-1-2"])
    _grab("US-TST-1-1")

    data = yaml.safe_load(pm_done_next("US-TST-1-1", note="done"))

    assert data["next"]["task"]["id"] == "US-TST-1-3"
    assert tree.get_task("US-TST-1-2")[0].assignee is None


def test_pm_done_next_picks_nothing_when_the_only_task_is_blocked(tree):
    from projectman.server import pm_done_next

    tree.create_decision("Which database?", blocks=["US-TST-1-2"])
    _grab("US-TST-1-1")

    data = yaml.safe_load(pm_done_next("US-TST-1-1", note="done"))

    assert data["status"] == "no_next_task"
    assert data["next"] is None


def test_board_agrees_with_grab(tree):
    from projectman.server import pm_board

    tree.create_decision("Which database?", blocks=["US-TST-1-1"])

    board = yaml.safe_load(pm_board())["board"]

    available = [row["id"] for row in board["available"]]
    assert available == ["US-TST-1-2"]
    rows = {row["id"]: row for row in board["blocked"]}
    assert rows["US-TST-1-1"]["decisions"] == [
        {"id": "DEC-TST-1", "title": "Which database?"}
    ]


# ─── Board: decision-held tasks are blocked (US-PM-64-8) ─────────


def _board(**kwargs):
    from projectman.server import pm_board

    return yaml.safe_load(pm_board(**kwargs))


def _ids(rows):
    return [row["id"] for row in rows]


@pytest.mark.parametrize("target", ["US-TST-1-1", "US-TST-1", "EPIC-TST-1"])
def test_board_lists_a_decision_held_task_under_blocked(tree, target):
    tree.create_decision("Which database?", blocks=[target])

    data = _board()
    board = data["board"]

    held = ["US-TST-1-1"] if target == "US-TST-1-1" else ["US-TST-1-1", "US-TST-1-2"]
    assert _ids(board["blocked"]) == held
    for row in board["blocked"]:
        assert row["decisions"] == [{"id": "DEC-TST-1", "title": "Which database?"}]
        # Nothing else holds it, so there is no blocker prose to carry.
        assert "blockers" not in row
        assert row["title"] and row["story"].startswith("US-TST-1")
    for group in ("available", "not_ready"):
        assert not set(held) & set(_ids(board[group])), group
    assert data["summary"]["blocked"] == len(held)
    assert data["summary"]["available"] == 2 - len(held)
    assert data["summary"]["not_ready"] == 0


def test_board_names_every_holding_decision(tree):
    tree.create_decision("First?", blocks=["US-TST-1-1"])
    tree.create_decision("Second?", blocks=["EPIC-TST-1"])

    rows = {row["id"]: row for row in _board()["board"]["blocked"]}

    assert rows["US-TST-1-1"]["decisions"] == [
        {"id": "DEC-TST-1", "title": "First?"},
        {"id": "DEC-TST-2", "title": "Second?"},
    ]
    assert rows["US-TST-1-2"]["decisions"] == [{"id": "DEC-TST-2", "title": "Second?"}]


def test_board_keeps_the_other_blockers_of_a_decision_held_task(tree):
    from projectman.server import pm_create_tasks

    pm_create_tasks("US-TST-1", [{"title": "Unsized", "description": BODY}])
    tree.create_decision("Which database?", blocks=["US-TST-1-3"])

    data = _board()
    rows = {row["id"]: row for row in data["board"]["blocked"]}

    assert rows["US-TST-1-3"]["decisions"] == [
        {"id": "DEC-TST-1", "title": "Which database?"}
    ]
    assert rows["US-TST-1-3"]["blockers"]
    assert not any("decision" in b for b in rows["US-TST-1-3"]["blockers"])
    assert "US-TST-1-3" not in _ids(data["board"]["not_ready"])


@pytest.mark.parametrize(
    "resolution",
    [{"status": "answered", "answer": "Postgres"}, {"status": "withdrawn"}],
    ids=["answered", "withdrawn"],
)
def test_resolving_the_decision_returns_the_task_to_available(tree, resolution):
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])
    assert _ids(_board()["board"]["blocked"]) == ["US-TST-1-1"]

    tree.update_decision("DEC-TST-1", **resolution)

    data = _board()
    assert _ids(data["board"]["available"]) == ["US-TST-1-1", "US-TST-1-2"]
    assert data["board"]["blocked"] == []
    assert data["summary"]["available"] == 2
    assert data["summary"]["blocked"] == 0


def test_board_counts_human_and_decision_blocked_together(tree):
    from projectman.server import pm_update

    pm_update("US-TST-1-2", status="blocked")
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])

    data = _board()

    assert sorted(_ids(data["board"]["blocked"])) == ["US-TST-1-1", "US-TST-1-2"]
    rows = {row["id"]: row for row in data["board"]["blocked"]}
    assert "decisions" not in rows["US-TST-1-2"]
    assert data["summary"]["blocked"] == 2
    assert data["summary"]["available"] == 0


def test_board_note_mentions_decision_held(tree):
    note = _board()["note"]
    assert "decision" in note
    assert "not_ready" in note and "blocked" in note


def test_board_fields_projection_reaches_decisions(tree):
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])

    data = _board(fields="decisions")

    assert data["board"]["blocked"] == [
        {
            "id": "US-TST-1-1",
            "decisions": [{"id": "DEC-TST-1", "title": "Which database?"}],
        }
    ]
    assert data["board"]["available"] == [{"id": "US-TST-1-2"}]
    assert data["summary"] == _board()["summary"]


def test_board_brief_keeps_the_held_task_under_blocked(tree):
    from projectman.server import BRIEF_BOARD_FIELDS

    tree.create_decision("Which database?", blocks=["US-TST-1-1"])

    data = _board(brief=True)

    assert _ids(data["board"]["blocked"]) == ["US-TST-1-1"]
    for row in data["board"]["blocked"]:
        assert set(row) <= set(BRIEF_BOARD_FIELDS)
    assert data["summary"]["blocked"] == 1


def test_lane_filter_never_offers_a_decision_held_task(tree):
    from projectman.server import pm_create_story, pm_create_tasks, pm_update

    pm_create_story("Other story", "Another story description long enough.")
    pm_update("US-TST-2", status="active", epic_id="EPIC-TST-1")
    pm_create_tasks(
        "US-TST-2",
        [
            {"title": "Held", "description": BODY, "points": 1},
            {"title": "Free", "description": BODY, "points": 1},
        ],
    )
    tree.create_decision("Which database?", blocks=["US-TST-2-1"])
    _grab("US-TST-1-1")

    data = _board(lane_compatible_with="US-TST-1-1")

    assert _ids(data["board"]["available"]) == ["US-TST-2-2"]
    assert "US-TST-2-1" in _ids(data["board"]["blocked"])
    # Held by the decision, not hidden by the lane: it never reached
    # `available`, so only the lane's own-story sibling counts as excluded.
    assert data["lane_excluded"] == 1


def test_board_reads_decisions_once(tree, monkeypatch):
    from projectman.server import pm_board, pm_create_tasks

    pm_create_tasks(
        "US-TST-1",
        [
            {"title": f"Task {n}", "description": BODY, "points": 1}
            for n in range(3, 11)
        ],
    )
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])

    calls = {"list_decisions": 0, "get_story": 0}
    for name in calls:
        original = getattr(Store, name)

        def spy(self, *args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Store, name, spy)

    pm_board()

    assert calls["list_decisions"] == 1, (
        f"pm_board called list_decisions {calls['list_decisions']}x for 10 tasks"
    )
    assert calls["get_story"] == 0


def test_pm_done_next_reads_decisions_once(tree, monkeypatch):
    from projectman.server import pm_create_tasks, pm_done_next

    pm_create_tasks(
        "US-TST-1",
        [
            {"title": f"Task {n}", "description": BODY, "points": 1}
            for n in range(3, 8)
        ],
    )
    # Every sibling but the last is decision-blocked, so the pick loop walks
    # past several candidates before one is ready.
    tree.create_decision(
        "Which database?", blocks=[f"US-TST-1-{n}" for n in range(2, 7)]
    )
    _grab("US-TST-1-1")

    calls = {"n": 0}
    original = Store.list_decisions

    def spy(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Store, "list_decisions", spy)

    data = yaml.safe_load(pm_done_next("US-TST-1-1", note="done"))

    assert data["next"]["task"]["id"] == "US-TST-1-7"
    # One read for the pick loop, one for the winning grab's own check.
    assert calls["n"] <= 2, f"pm_done_next called list_decisions {calls['n']}x"


def test_check_readiness_signature_is_backward_compatible(tree):
    meta, body = tree.get_task("US-TST-1-1")
    assert check_readiness(meta, body, tree) == {
        "ready": True,
        "blockers": [],
        "warnings": [],
    }
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])
    preloaded = tree.list_decisions()
    assert check_readiness(meta, body, tree, decisions=preloaded)["blockers"] == [
        "blocked by open decision DEC-TST-1: Which database?"
    ]


# ─── US-PM-64 criterion: pm_grab refuses a decision-blocked task (US-PM-64-1) ─


def _task_events(task_id):
    from projectman.activity_log import log_paths, read_log_entries
    from projectman.server import _project_dir

    paths = log_paths(_project_dir())
    return [e for e in read_log_entries(paths) if e.get("item_id") == task_id]


def _grab_as_run(task_id):
    from projectman.server import pm_grab

    return yaml.safe_load(pm_grab(task_id, run_id="run-crit"))


@pytest.mark.parametrize(
    "target",
    ["US-TST-1-1", "US-TST-1", "EPIC-TST-1"],
    ids=["task", "story", "epic"],
)
def test_us_pm_64_criterion_pm_grab_refuses_and_names_the_decision(tree, target):
    """US-PM-64 criterion: pm_grab refuses a task blocked by an open decision on
    the task, its story or its epic and names the decision id in the blocker."""
    tree.create_decision("Which database?", blocks=[target])
    before = _snapshot(tree, "US-TST-1-1")
    events_before = _task_events("US-TST-1-1")

    data = _grab_as_run("US-TST-1-1")

    assert data["status"] == "not_ready"
    assert "grabbed" not in data
    assert any(
        "DEC-TST-1" in b and "Which database?" in b for b in data["blockers"]
    ), data["blockers"]
    # Refusal leaves the task untouched: no status/assignee change, no claim
    # metadata, and no claim event in the activity log.
    assert _snapshot(tree, "US-TST-1-1") == before
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.status.value == "todo"
    assert meta.assignee is None
    assert meta.claimed_at is None and meta.claimed_by_run is None
    assert _task_events("US-TST-1-1") == events_before
    assert not [e for e in _task_events("US-TST-1-1") if e.get("run_id") == "run-crit"]


def test_us_pm_64_criterion_only_resolved_decisions_leave_the_task_grabbable(tree):
    """US-PM-64 criterion: a task whose only decisions are answered or withdrawn
    is grabbable — resolved decisions never block."""
    tree.create_decision("Answered on task?", blocks=["US-TST-1-1"])
    tree.create_decision("Withdrawn on story?", blocks=["US-TST-1"])
    tree.create_decision("Answered on epic?", blocks=["EPIC-TST-1"])
    tree.update_decision("DEC-TST-1", status="answered", answer="Postgres")
    tree.update_decision("DEC-TST-2", status="withdrawn")
    tree.update_decision("DEC-TST-3", status="answered", answer="Yes")

    data = _grab_as_run("US-TST-1-1")

    assert data["grabbed"]["task"]["id"] == "US-TST-1-1"
    assert data["grabbed"]["task"]["status"] == "in-progress"
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.assignee == "claude" and meta.claimed_by_run == "run-crit"


# ─── US-PM-64 criterion: answering/withdrawing frees the task (US-PM-64-3) ───

_RESOLUTIONS = pytest.mark.parametrize(
    "resolution",
    [{"status": "answered", "answer": "Postgres"}, {"status": "withdrawn"}],
    ids=["answered", "withdrawn"],
)
_TARGETS = pytest.mark.parametrize(
    "target",
    ["US-TST-1-1", "US-TST-1", "EPIC-TST-1"],
    ids=["task", "story", "epic"],
)


def _item_files(store):
    """Bytes of every epic, story, task and decision file in the tmp store."""
    root = store.project_dir
    return {
        str(path.relative_to(root)): path.read_bytes()
        for sub in ("epics", "stories", "tasks", "decisions")
        if (root / sub).is_dir()
        for path in sorted((root / sub).glob("*.md"))
    }


@_TARGETS
@_RESOLUTIONS
def test_us_pm_64_criterion_resolving_the_decision_frees_the_task_with_no_other_change(
    tree, target, resolution
):
    """US-PM-64 criterion: answering or withdrawing the decision makes the task
    grabbable again with no other change — the task, story and epic files are
    byte-identical, only the decision file differs, and pm_board moves the
    task from blocked back to available."""
    tree.create_decision("Which database?", blocks=[target])
    assert _grab_as_run("US-TST-1-1")["status"] == "not_ready"
    assert "US-TST-1-1" in _ids(_board()["board"]["blocked"])
    task_path = tree._task_path("US-TST-1-1")
    task_bytes = task_path.read_bytes()
    files_before = _item_files(tree)

    tree.update_decision("DEC-TST-1", **resolution)

    # No other change: only the decision file was rewritten.
    assert task_path.read_bytes() == task_bytes
    files_after = _item_files(tree)
    assert set(files_after) == set(files_before)
    changed = sorted(k for k in files_before if files_before[k] != files_after[k])
    assert changed == ["decisions/DEC-TST-1.md"]

    board = _board()
    assert "US-TST-1-1" in _ids(board["board"]["available"])
    assert board["board"]["blocked"] == []

    data = _grab_as_run("US-TST-1-1")
    assert data["grabbed"]["task"]["id"] == "US-TST-1-1"
    assert data["grabbed"]["task"]["status"] == "in-progress"
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.assignee == "claude" and meta.claimed_by_run == "run-crit"


@_TARGETS
@_RESOLUTIONS
def test_us_pm_64_criterion_a_second_open_decision_still_blocks(
    tree, target, resolution
):
    """US-PM-64 criterion: resolving one decision frees the task only when no
    other open decision still holds it."""
    tree.create_decision("First?", blocks=[target])
    tree.create_decision("Second?", blocks=["US-TST-1-1"])

    tree.update_decision("DEC-TST-1", **resolution)

    data = _grab_as_run("US-TST-1-1")
    assert data["status"] == "not_ready"
    assert data["blockers"] == ["blocked by open decision DEC-TST-2: Second?"]
    rows = {row["id"]: row for row in _board()["board"]["blocked"]}
    assert rows["US-TST-1-1"]["decisions"] == [{"id": "DEC-TST-2", "title": "Second?"}]
    assert tree.get_task("US-TST-1-1")[0].assignee is None

    tree.update_decision("DEC-TST-2", status="withdrawn")

    assert _grab_as_run("US-TST-1-1")["grabbed"]["task"]["id"] == "US-TST-1-1"


# ─── US-PM-64 criterion: the board lists decision-blocked tasks (US-PM-64-2) ───


@_TARGETS
def test_us_pm_64_criterion_board_lists_decision_blocked_task_under_blocked(
    tree, target
):
    """US-PM-64 criterion: the board lists decision-blocked tasks under blocked
    with the decision id and title rather than as available — whether the open
    decision blocks the task, its story or its epic — and the summary counts
    follow the rows."""
    baseline = _board()
    assert _ids(baseline["board"]["available"]) == ["US-TST-1-1", "US-TST-1-2"]
    assert baseline["summary"]["blocked"] == 0

    tree.create_decision("Which database?", blocks=[target])

    data = _board()
    board = data["board"]
    held = ["US-TST-1-1"] if target == "US-TST-1-1" else ["US-TST-1-1", "US-TST-1-2"]
    free = [t for t in ("US-TST-1-1", "US-TST-1-2") if t not in held]

    assert _ids(board["blocked"]) == held
    for row in board["blocked"]:
        assert row["decisions"] == [{"id": "DEC-TST-1", "title": "Which database?"}]
    assert _ids(board["available"]) == free
    assert not set(held) & set(_ids(board["not_ready"]))
    assert data["summary"] == {
        **baseline["summary"],
        "available": len(free),
        "not_ready": 0,
        "blocked": len(held),
    }


def test_us_pm_64_criterion_board_lists_both_open_decisions(tree):
    """US-PM-64 criterion: a task held by two open decisions lists both, each
    with its id and title; a resolved decision on the same task is not listed."""
    tree.create_decision("On the task?", blocks=["US-TST-1-1"])
    tree.create_decision("On the story?", blocks=["US-TST-1"])
    tree.create_decision("Already settled?", blocks=["US-TST-1-1"])
    tree.update_decision("DEC-TST-3", status="answered", answer="Yes")

    data = _board()
    rows = {row["id"]: row for row in data["board"]["blocked"]}

    assert rows["US-TST-1-1"]["decisions"] == [
        {"id": "DEC-TST-1", "title": "On the task?"},
        {"id": "DEC-TST-2", "title": "On the story?"},
    ]
    assert rows["US-TST-1-2"]["decisions"] == [
        {"id": "DEC-TST-2", "title": "On the story?"}
    ]
    assert data["board"]["available"] == []
    assert data["summary"]["blocked"] == 2


def test_us_pm_64_criterion_board_brief_and_fields_on_decision_rows(tree):
    """US-PM-64 criterion: brief keeps a decision-blocked task under blocked but
    drops `decisions` (it is not in BRIEF_BOARD_FIELDS); `fields="decisions"`
    returns them; the counts are the same in every projection."""
    from projectman.server import BRIEF_BOARD_FIELDS

    assert "decisions" not in BRIEF_BOARD_FIELDS
    tree.create_decision("Which database?", blocks=["US-TST-1-1"])
    full = _board()

    brief = _board(brief=True)
    assert _ids(brief["board"]["blocked"]) == ["US-TST-1-1"]
    assert "decisions" not in brief["board"]["blocked"][0]
    assert _ids(brief["board"]["available"]) == ["US-TST-1-2"]
    assert brief["summary"] == full["summary"]

    projected = _board(fields="title,decisions")
    assert projected["board"]["blocked"] == [
        {
            "id": "US-TST-1-1",
            "title": "Task one",
            "decisions": [{"id": "DEC-TST-1", "title": "Which database?"}],
        }
    ]
    assert projected["summary"] == full["summary"]

    # fields wins over brief, so naming decisions brings them back.
    both = _board(brief=True, fields="decisions")
    assert both["board"]["blocked"][0]["decisions"] == [
        {"id": "DEC-TST-1", "title": "Which database?"}
    ]
