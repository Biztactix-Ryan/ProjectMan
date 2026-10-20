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
    rows = {row["id"]: row for row in board["not_ready"]}
    assert rows["US-TST-1-1"]["blockers"] == [
        "blocked by open decision DEC-TST-1: Which database?"
    ]


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
