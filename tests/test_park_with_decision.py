"""pm_park raises a decision blocking the parked task, in one call (US-PM-64-9).

Every test runs against the tmp_path-isolated ``tmp_project`` fixture, with the
working directory moved there and the server's store root asserted to be the
tmp dir before anything is written — nothing here touches the real
``.project``.
"""

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

BODY = (
    "## Implementation\n\nDo the thing properly and completely.\n\n"
    "## Testing\n\nTest the thing properly.\n"
)

QUESTION = {
    "title": "Which queue backend?",
    "context": "The worker needs a queue; nothing is chosen yet.",
    "options": [
        {"label": "redis", "summary": "already deployed"},
        "sqs",
    ],
    "recommendation": "redis",
}


@pytest.fixture
def tree(tmp_project, monkeypatch):
    """US-TST-1 > US-TST-1-1, US-TST-1-2 — identical, ready, 1 point each."""
    from projectman.server import (
        _store,
        _store_cache,
        pm_create_story,
        pm_create_tasks,
        pm_update,
    )
    from projectman.store import clear_all_caches

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    clear_all_caches()
    _store_cache.clear()
    # Guard before any write: the server must resolve to the tmp store.
    assert _store().project_dir == tmp_project / ".project"

    pm_create_story("Story", "Story description long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": "Task", "description": BODY, "points": 1},
            {"title": "Task", "description": BODY, "points": 1},
        ],
    )
    yield _store()
    clear_all_caches()
    _store_cache.clear()


def _grab(task_id, assignee="claude"):
    from projectman.server import pm_grab

    return yaml.safe_load(pm_grab(task_id, assignee=assignee))


def _park(task_id, **kwargs):
    from projectman.server import pm_park

    return yaml.safe_load(pm_park(task_id, **kwargs))


def _tree_bytes(store):
    """Every file under .project, by relative path, as bytes."""
    root = store.project_dir
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_park_with_decision_creates_a_decision_blocking_the_task(tree):
    _grab("US-TST-1-1", assignee="worker-7")

    data = _park("US-TST-1-1", note="needs a human call", decision=QUESTION)

    decision_id = data["decision_id"]
    assert decision_id == "DEC-TST-1"
    meta, body = tree.get_decision(decision_id)
    assert meta.blocks == ["US-TST-1-1"]
    assert meta.raised_by == "worker-7"
    assert meta.raised_from == "US-TST-1-1"
    assert meta.status.value == "open"
    assert meta.title == QUESTION["title"]
    assert [o.label for o in meta.options] == ["redis", "sqs"]
    assert meta.recommendation == "redis"
    assert body.strip() == QUESTION["context"]


def test_response_carries_the_decision_id_alongside_parked(tree):
    _grab("US-TST-1-1", assignee="worker-7")

    data = _park("US-TST-1-1", note="needs a human call", decision=QUESTION)

    assert set(data) == {"parked", "decision_id"}
    assert data["parked"]["from_assignee"] == "worker-7"
    assert data["parked"]["from_status"] == "in-progress"
    task = data["parked"]["task"]
    assert task["id"] == "US-TST-1-1"
    assert task["status"] == "review"
    assert task.get("assignee") is None
    # The park itself is the ordinary one: review + blocked, note logged.
    entry = tree.get_run_log("US-TST-1-1", limit=1)[0]
    assert entry.note == "needs a human call"
    assert entry.outcome.value == "blocked"


def test_unassigned_task_raises_with_no_raised_by(tree):
    data = _park("US-TST-1-1", note="needs a human call", decision={"title": "Q?"})

    meta, _ = tree.get_decision(data["decision_id"])
    assert meta.raised_by is None
    assert meta.raised_from == "US-TST-1-1"


def test_parked_task_is_held_by_the_decision(tree):
    from projectman.server import pm_board, pm_update

    _grab("US-TST-1-1", assignee="worker-7")
    data = _park("US-TST-1-1", note="needs a human call", decision=QUESTION)
    decision_id = data["decision_id"]
    blocker = f"blocked by open decision {decision_id}: {QUESTION['title']}"
    assert blocker in _grab("US-TST-1-1")["blockers"]
    # Even handed back to todo, the open decision keeps the task unclaimable.
    pm_update("US-TST-1-1", status="todo")

    refused = _grab("US-TST-1-1")
    assert refused["status"] == "not_ready"
    assert (
        f"blocked by open decision {decision_id}: {QUESTION['title']}"
        in refused["blockers"]
    )
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.assignee is None

    board = yaml.safe_load(pm_board())
    blocked = {row["id"]: row for row in board["board"]["blocked"]}
    assert blocked["US-TST-1-1"]["decisions"] == [
        {"id": decision_id, "title": QUESTION["title"]}
    ]

    # Answering the decision frees it.
    pm_update(decision_id, status="answered", answer="redis")
    assert _grab("US-TST-1-1")["grabbed"]["task"]["id"] == "US-TST-1-1"


@pytest.mark.parametrize(
    "decision",
    [
        {"context": "no title"},
        {"title": "   "},
        {"title": 7},
        {"title": "Q?", "blocks": ["US-TST-1-2"]},
        {"title": "Q?", "raised_by": "someone"},
        {"title": "Q?", "options": [{"label": "a"}, {"label": "a"}]},
        {"title": "Q?", "options": ["a"], "recommendation": "b"},
        {"title": "Q?", "options": "a,b"},
        {"title": "Q?", "context": ["not", "text"]},
        "just a string",
    ],
    ids=[
        "missing-title",
        "blank-title",
        "non-string-title",
        "blocks-supplied",
        "raised-by-supplied",
        "duplicate-labels",
        "unknown-recommendation",
        "options-not-a-list",
        "context-not-text",
        "not-an-object",
    ],
)
def test_invalid_decision_is_an_error_and_nothing_is_written(tree, decision):
    from projectman.server import pm_park

    _grab("US-TST-1-1", assignee="worker-7")
    before = _tree_bytes(tree)

    with pytest.raises(ToolError):
        pm_park("US-TST-1-1", note="needs a human call", decision=decision)

    assert _tree_bytes(tree) == before
    assert not tree.decisions_dir.exists() or not list(
        tree.decisions_dir.glob("*.md")
    )
    meta, _ = tree.get_task("US-TST-1-1")
    assert meta.status.value == "in-progress"
    assert meta.assignee == "worker-7"


@pytest.mark.parametrize(
    "task_id, note",
    [("US-TST-1-1", "   "), ("US-TST-1", "a story"), ("US-TST-1-9", "missing")],
    ids=["blank-note", "story-id", "unknown-task"],
)
def test_refused_park_leaves_no_decision(tree, task_id, note):
    from projectman.server import pm_park

    before = _tree_bytes(tree)

    with pytest.raises(ToolError):
        pm_park(task_id, note=note, decision={"title": "Q?"})

    assert _tree_bytes(tree) == before


def test_plain_park_output_is_byte_identical_to_before(tree):
    """Without `decision`, pm_park is exactly the pre-US-PM-64-9 code path."""
    from projectman.server import _do_verdict, _yaml_dump, pm_park

    _grab("US-TST-1-1", assignee="worker-7")
    _grab("US-TST-1-2", assignee="worker-7")

    new = pm_park("US-TST-1-1", note="needs a human call")
    old = _yaml_dump(_do_verdict(tree, "pm_park", "US-TST-1-2", "needs a human call"))

    assert "decision" not in new
    assert new == old.replace("US-TST-1-2", "US-TST-1-1")
    assert not tree.decisions_dir.exists() or not list(
        tree.decisions_dir.glob("*.md")
    )


def test_dry_run_create_decision_writes_nothing(tree):
    before = _tree_bytes(tree)

    meta = tree.create_decision("Q?", blocks=["US-TST-1-1"], dry_run=True)

    assert meta.title == "Q?"
    assert _tree_bytes(tree) == before
    with pytest.raises(Exception):
        tree.create_decision("Q?", blocks=["US-TST-9-9"], dry_run=True)


# ═══ US-PM-64-4 — the story criterion, end to end over the wire ═══


def _call_over_the_wire(name, arguments):
    """Drive one real ``tools/call`` through the low-level request handler."""
    import anyio
    from mcp import types

    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


def test_us_pm_64_criterion_park_with_decision_over_the_wire(tree):
    """pm_park with a decision argument creates the decision blocking that
    task and returns its id alongside the parked task."""
    _grab("US-TST-1-1", assignee="worker-7")

    is_error, text = _call_over_the_wire(
        "pm_park",
        {"task_id": "US-TST-1-1", "note": "needs a human call", "decision": QUESTION},
    )

    assert not is_error, text
    data = yaml.safe_load(text)
    assert set(data) == {"parked", "decision_id"}
    assert data["parked"]["task"]["id"] == "US-TST-1-1"
    assert data["parked"]["task"]["status"] == "review"
    assert data["parked"]["from_assignee"] == "worker-7"
    # The id the response names is a real open decision blocking the task.
    meta, _ = tree.get_decision(data["decision_id"])
    assert meta.blocks == ["US-TST-1-1"]
    assert meta.status.value == "open"
    assert meta.raised_by == "worker-7"
    assert meta.raised_from == "US-TST-1-1"


def test_us_pm_64_criterion_bad_decision_over_the_wire_is_an_error(tree):
    _grab("US-TST-1-1", assignee="worker-7")
    before = _tree_bytes(tree)

    is_error, text = _call_over_the_wire(
        "pm_park",
        {
            "task_id": "US-TST-1-1",
            "note": "needs a human call",
            "decision": {"context": "no title"},
        },
    )

    assert is_error, text
    assert _tree_bytes(tree) == before
