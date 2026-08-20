"""Release and the field-clear affordances (US-PM-7-8).

Implements §1 and §3 of docs/reference/claim-release-contract.md.  The rule
behind every test here is the contract's governing principle: *no operation may
require the caller to spell emptiness*.  So releasing a task is said by a verb
(`pm_release`) or a boolean (`unassign`), and emptying `depends_on` / `tags` is
said by naming the field (`clear="depends_on"`) — never by an empty value.

The legacy `assignee=""` sentinel stays accepted (undocumented) and is asserted
here too: it must normalise to `None`, because writing a literal `''` bricks the
task — `readiness.py` tests `assignee is not None`, and `''` is not `None`.
"""

import inspect
import json

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.store import Store

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _story_with_task(store: Store, **task_kwargs) -> Store:
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    store.create_task("US-TST-1", "Task 1", READY_BODY, points=1, **task_kwargs)
    return store


def _tool_story_with_tasks(n: int = 1) -> None:
    """Same fixture, built through the tools, for server-level tests."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": f"Task {i}", "description": READY_BODY, "points": 1}
            for i in range(1, n + 1)
        ],
    )


def _tool_schemas() -> dict:
    """The tools/list payload — the schema and prose the model actually reads."""
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
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


def _assert_spellable(arguments: dict) -> None:
    """No value in this call payload is an empty string or a null.

    This is the acceptance criterion itself, mechanised: the malformed calls
    this story exists to end were all attempts to *spell emptiness* in an
    argument value.  A payload with no such value has no malformed form.
    """
    for key, value in arguments.items():
        assert value is not None, f"{key} is null — a sentinel the model cannot spell"
        assert value != "", f"{key} is an empty string — the sentinel that failed"


def _activity(store: Store) -> list[dict]:
    log_path = store.project_dir / "activity.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(ln) for ln in log_path.read_text().splitlines() if ln.strip()]


# ─── §0 — the "" → None normalisation ────────────────────────────


def test_store_update_empty_assignee_normalises_to_none(store):
    """`''` must never reach disk: readiness tests `is not None`."""
    _story_with_task(store)
    store.claim_task("US-TST-1-1", "claude")

    meta = store.update("US-TST-1-1", assignee="", status="todo")
    assert meta.assignee is None

    on_disk, _ = Store(store.root).get_task("US-TST-1-1")
    assert on_disk.assignee is None
    raw = (store.tasks_dir / "US-TST-1-1.md").read_text()
    assert "assignee: ''" not in raw
    assert 'assignee: ""' not in raw


def test_empty_assignee_leaves_the_task_grabbable(store):
    """The bug this guards: a literal '' bricks the task permanently."""
    from projectman.readiness import check_readiness

    _story_with_task(store)
    store.claim_task("US-TST-1-1", "claude")
    store.update("US-TST-1-1", assignee="", status="todo")

    meta, body = store.get_task("US-TST-1-1")
    readiness = check_readiness(meta, body, store)
    assert readiness["ready"] is True, readiness["blockers"]


def test_pm_update_empty_assignee_still_accepted(tmp_project):
    """Undocumented but accepted forever — removing it would strand callers."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="claude")
    result = yaml.safe_load(pm_update("US-TST-1-1", assignee="", status="todo"))
    assert result["updated"]["assignee"] is None


def test_pm_update_docstring_no_longer_documents_the_sentinel():
    """A *documented* sentinel is precisely what trained the malformed prior."""
    from projectman.server import pm_update

    doc = inspect.getdoc(pm_update) or ""
    assert 'pass "" to unassign' not in doc
    assert "unassign=true" in doc


# ─── §1.1 — pm_release, the primary ──────────────────────────────


def test_pm_release_has_no_assignee_parameter():
    """The failure is a value the model cannot spell — so remove the value."""
    from projectman.server import pm_release

    params = inspect.signature(pm_release).parameters
    assert "assignee" not in params
    assert params["task_id"].default is None
    assert params["status"].default == "todo"


def test_pm_release_clears_the_assignee_and_resets_status(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")

    result = yaml.safe_load(pm_release("US-TST-1-1"))
    released = result["released"]
    assert released["from_assignee"] == "worker-1"
    assert released["task"]["assignee"] is None
    assert released["task"]["status"] == "todo"

    on_disk, _ = Store(tmp_project).get_task("US-TST-1-1")
    assert on_disk.assignee is None
    assert on_disk.status.value == "todo"


def test_pm_release_is_a_successful_response(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    body = pm_release("US-TST-1-1", note="worker stopped")
    assert not body.startswith("error:")
    assert "released:" in body


def test_pm_release_accepts_the_id_alias(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(pm_release(id="US-TST-1-1"))
    assert result["released"]["task"]["assignee"] is None


def test_pm_release_of_an_unassigned_task_succeeds(tmp_project):
    """Idempotent: a cleanup loop must not branch on a condition it ignores."""
    from projectman.server import pm_release

    _tool_story_with_tasks()
    result = yaml.safe_load(pm_release("US-TST-1-1"))
    assert result["released"]["from_assignee"] is None
    assert result["released"]["task"]["assignee"] is None


def test_pm_release_logs_the_reason(tmp_project):
    """The measured hot path: 'Released by orchestrator...' as a run-log note."""
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_release("US-TST-1-1", note="Released by orchestrator: worker stopped")

    entries = Store(tmp_project).get_run_log("US-TST-1-1")
    assert entries[0].note == "Released by orchestrator: worker stopped"
    assert entries[0].outcome.value == "info"  # defaults to info, like pm_update


def test_pm_release_honours_an_explicit_outcome(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_release("US-TST-1-1", note="ran out of budget", outcome="blocked")

    entries = Store(tmp_project).get_run_log("US-TST-1-1")
    assert entries[0].outcome.value == "blocked"


def test_pm_release_without_a_note_writes_no_run_log(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_release("US-TST-1-1")
    assert Store(tmp_project).get_run_log("US-TST-1-1") == []


def test_pm_release_can_leave_another_status(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(pm_release("US-TST-1-1", status="blocked"))
    assert result["released"]["task"]["status"] == "blocked"


def test_pm_release_guard_matches_and_releases(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(
        pm_release("US-TST-1-1", expected_assignee="worker-1")
    )
    assert result["released"]["from_assignee"] == "worker-1"
    assert result["released"]["task"]["assignee"] is None


def test_pm_release_guard_mismatch_is_an_expected_negative(tmp_project):
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-2")
    path = tmp_project / ".project" / "tasks" / "US-TST-1-1.md"
    before = path.read_bytes()

    body = pm_release("US-TST-1-1", expected_assignee="worker-1")
    result = yaml.safe_load(body)

    assert not body.startswith("error:")
    assert result["outcome"] == "expected_negative"
    assert result["status"] == "not_holder"
    assert result["holder"] == "worker-2"
    assert result["expected"] == "worker-1"
    assert "released" not in result
    assert path.read_bytes() == before, "a lost guard must not touch the task"


def test_pm_release_rejects_a_story_id(tmp_project):
    """assignee is a task-only field, so a story id is a genuine failure."""
    from projectman.server import pm_release

    _tool_story_with_tasks()
    with pytest.raises(ToolError) as exc:
        pm_release("US-TST-1")
    assert "tasks only" in str(exc.value)


def test_pm_release_rejects_an_epic_id(tmp_project):
    from projectman.server import pm_create_epic, pm_release

    pm_create_epic("Epic", "An epic body long enough to matter.")
    with pytest.raises(ToolError):
        pm_release("EPIC-TST-1")


def test_pm_release_missing_task_raises(tmp_project):
    from projectman.server import pm_release

    _tool_story_with_tasks()
    with pytest.raises(ToolError):
        pm_release("US-TST-1-99")


def test_pm_release_then_grab_round_trips(tmp_project):
    """grab / release is a symmetry a caller can predict."""
    from projectman.server import pm_grab, pm_release

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_release("US-TST-1-1", note="handing back")
    regrabbed = yaml.safe_load(pm_grab("US-TST-1-1", assignee="worker-2"))
    assert regrabbed["grabbed"]["task"]["assignee"] == "worker-2"


# ─── §1.2 — unassign, the secondary ──────────────────────────────


def test_pm_update_unassign_clears_the_assignee(tmp_project):
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(pm_update("US-TST-1-1", unassign=True))
    assert result["updated"]["assignee"] is None
    assert Store(tmp_project).get_task("US-TST-1-1")[0].assignee is None


def test_unassign_default_is_false_not_none():
    """`null` must not be this parameter's 'leave unchanged' — that prior is
    exactly what defeated the `""` sentinel."""
    from projectman.server import pm_update

    assert inspect.signature(pm_update).parameters["unassign"].default is False


def test_pm_update_unassign_touches_nothing_else(tmp_project):
    """The field-level primitive: no status reset, no run-log entry."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_update("US-TST-1-1", unassign=True)

    meta, _ = Store(tmp_project).get_task("US-TST-1-1")
    assert meta.status.value == "in-progress"
    assert Store(tmp_project).get_run_log("US-TST-1-1") == []


def test_pm_update_unassign_with_an_assignee_is_a_failure(tmp_project):
    """A silent winner would let a release quietly become an assignment."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    with pytest.raises(ToolError) as exc:
        pm_update("US-TST-1-1", unassign=True, assignee="worker-2")
    assert "conflicting" in str(exc.value)
    assert Store(tmp_project).get_task("US-TST-1-1")[0].assignee == "worker-1"


def test_pm_update_unassign_with_the_legacy_sentinel_agrees(tmp_project):
    """`unassign=True` plus `assignee=""` are the same intent, not a conflict."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(pm_update("US-TST-1-1", unassign=True, assignee=""))
    assert result["updated"]["assignee"] is None


def test_pm_update_unassign_false_is_a_no_op(tmp_project):
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    pm_update("US-TST-1-1", unassign=False, status="review")
    assert Store(tmp_project).get_task("US-TST-1-1")[0].assignee == "worker-1"


# ─── §1 — the criterion, at the wire ─────────────────────────────
#
# The story's acceptance criterion is "releasing a task is expressible without
# an empty-string or null sentinel".  The tests above pin the behaviour from
# inside the process; these pin it where the model meets it — the `tools/list`
# schema it reads and the `tools/call` payload it emits.


def test_a_wire_release_needs_only_the_task_id(tmp_project):
    """The whole call is one content-bearing string the model already holds."""
    from projectman.server import pm_grab

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")

    arguments = {"task_id": "US-TST-1-1"}
    _assert_spellable(arguments)

    is_error, body = _call_over_the_wire("pm_release", arguments)
    assert not is_error, body
    assert yaml.safe_load(body)["released"]["task"]["assignee"] is None
    assert Store(tmp_project).get_task("US-TST-1-1")[0].assignee is None


def test_a_wire_release_with_a_reason_still_spells_no_emptiness(tmp_project):
    """The measured hot path — id plus a reason — is sentinel-free end to end."""
    from projectman.server import pm_grab

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")

    arguments = {
        "task_id": "US-TST-1-1",
        "note": "Released by orchestrator: worker stopped",
        "outcome": "info",
    }
    _assert_spellable(arguments)

    is_error, body = _call_over_the_wire("pm_release", arguments)
    assert not is_error, body
    assert yaml.safe_load(body)["released"]["from_assignee"] == "worker-1"


def test_a_wire_unassign_needs_no_empty_value(tmp_project):
    """The secondary landing spot: `true` is a token, not an absence."""
    from projectman.server import pm_grab

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")

    arguments = {"id": "US-TST-1-1", "unassign": True}
    _assert_spellable(arguments)

    is_error, body = _call_over_the_wire("pm_update", arguments)
    assert not is_error, body
    assert yaml.safe_load(body)["updated"]["assignee"] is None


def test_the_release_schema_offers_no_assignee_to_empty():
    """`{"assignee": }` is not discouraged on pm_release — it is unreachable."""
    schema = _tool_schemas()["pm_release"].inputSchema
    properties = schema.get("properties", {})

    assert "assignee" not in properties
    # Nothing is required, so `{"task_id": ...}` alone is a complete call and
    # no other parameter has to be filled with a placeholder.
    assert not schema.get("required"), schema.get("required")
    assert "task_id" in properties and "id" in properties


def test_the_unassign_schema_is_a_boolean_that_defaults_to_false():
    """`null` must not be this parameter's "leave unchanged", at the wire too."""
    schema = _tool_schemas()["pm_update"].inputSchema["properties"]["unassign"]

    assert schema.get("type") == "boolean", schema
    assert "anyOf" not in schema, schema  # i.e. null is not an accepted value
    assert schema.get("default") is False, schema


@pytest.mark.parametrize("tool", ["pm_release", "pm_update", "pm_grab", "pm_done_next"])
def test_no_release_facing_tool_documents_the_empty_sentinel(tool):
    """A *documented* sentinel is what trained the malformed prior — so the
    prose the model reads must not carry one anywhere on the release path."""
    description = _tool_schemas()[tool].description or ""

    for sentinel in ('assignee=""', "assignee=''", 'assignee: ""', "assignee: ''"):
        assert sentinel not in description, (tool, sentinel)
    assert 'pass "" to unassign' not in description, tool
    assert "empty string" not in description.lower(), tool


def test_the_release_verb_is_the_documented_form():
    """Removing the sentinel is only half of it — the replacement has to be
    the thing the model finds instead."""
    descriptions = _tool_schemas()

    # Wrapped prose: compare on collapsed whitespace, not on line breaks.
    release = " ".join((descriptions["pm_release"].description or "").split())
    assert "pm_release(" in release
    assert "There is no assignee parameter here" in release

    update = descriptions["pm_update"].description or ""
    assert "pm_release(<id>)" in update  # the pointer to the primary
    assert "unassign=true" in update  # ...and the in-place spelling


# ─── §3 — clear, the field-name affordance ───────────────────────


def test_store_update_clear_empties_depends_on(store):
    _story_with_task(store)
    store.create_task("US-TST-1", "Task 2", READY_BODY, points=1)
    store.update("US-TST-1-2", depends_on=["US-TST-1-1"])

    meta = store.update("US-TST-1-2", clear="depends_on")
    assert meta.depends_on == []
    assert Store(store.root).get_task("US-TST-1-2")[0].depends_on == []


def test_store_update_clear_accepts_an_iterable(store):
    _story_with_task(store, tags=["a", "b"])
    meta = store.update("US-TST-1-1", clear=["tags"])
    assert meta.tags == []


def test_pm_update_clear_empties_tags(tmp_project):
    from projectman.server import pm_update

    _tool_story_with_tasks()
    pm_update("US-TST-1-1", tags="security,mvp")
    result = yaml.safe_load(pm_update("US-TST-1-1", clear="tags"))
    assert result["updated"]["tags"] == []
    assert Store(tmp_project).get_task("US-TST-1-1")[0].tags == []


def test_pm_update_clear_takes_several_field_names(tmp_project):
    from projectman.server import pm_update

    _tool_story_with_tasks(n=2)
    pm_update("US-TST-1-2", tags="a,b", depends_on="US-TST-1-1")
    result = yaml.safe_load(pm_update("US-TST-1-2", clear="depends_on,tags"))
    assert result["updated"]["depends_on"] == []
    assert result["updated"]["tags"] == []


def test_pm_update_clear_tolerates_whitespace(tmp_project):
    from projectman.server import pm_update

    _tool_story_with_tasks(n=2)
    pm_update("US-TST-1-2", tags="a,b", depends_on="US-TST-1-1")
    pm_update("US-TST-1-2", clear="depends_on, tags")
    meta, _ = Store(tmp_project).get_task("US-TST-1-2")
    assert meta.depends_on == []
    assert meta.tags == []


def test_pm_update_clear_assignee_is_a_third_spelling_of_release(tmp_project):
    """A model generalising from `clear="depends_on"` must land somewhere valid."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks()
    pm_grab("US-TST-1-1", assignee="worker-1")
    result = yaml.safe_load(pm_update("US-TST-1-1", clear="assignee"))
    assert result["updated"]["assignee"] is None
    assert Store(tmp_project).get_task("US-TST-1-1")[0].assignee is None


def test_pm_update_clear_points_and_epic_id_on_a_story(tmp_project):
    from projectman.server import pm_create_epic, pm_update

    _tool_story_with_tasks()
    pm_create_epic("Epic", "An epic body long enough to matter.")
    pm_update("US-TST-1", points=5, epic_id="EPIC-TST-1")

    result = yaml.safe_load(pm_update("US-TST-1", clear="points,epic_id"))
    assert result["updated"]["points"] is None
    assert result["updated"]["epic_id"] is None


def test_pm_update_clear_unknown_field_lists_the_valid_names(tmp_project):
    from projectman.server import pm_update

    _tool_story_with_tasks()
    with pytest.raises(ToolError) as exc:
        pm_update("US-TST-1-1", clear="asignee")
    message = str(exc.value)
    assert "asignee" in message
    for name in ("assignee", "depends_on", "epic_id", "points", "tags"):
        assert name in message


def test_pm_update_clear_wrong_item_type_raises(tmp_project):
    """assignee is task-only; naming it on a story is a caller bug."""
    from projectman.server import pm_update

    _tool_story_with_tasks()
    with pytest.raises(ToolError) as exc:
        pm_update("US-TST-1", clear="assignee")
    assert "assignee" in str(exc.value)


def test_pm_update_clear_conflicting_with_a_set_field_raises(tmp_project):
    """Loud and deterministic beats a silent precedence rule."""
    from projectman.server import pm_update

    _tool_story_with_tasks()
    pm_update("US-TST-1-1", tags="keep-me")
    with pytest.raises(ToolError) as exc:
        pm_update("US-TST-1-1", clear="tags", tags="a,b")
    assert "conflicting" in str(exc.value)
    assert Store(tmp_project).get_task("US-TST-1-1")[0].tags == ["keep-me"]


def test_pm_update_clear_conflict_leaves_the_file_untouched(tmp_project):
    from projectman.server import pm_update

    _tool_story_with_tasks()
    path = tmp_project / ".project" / "tasks" / "US-TST-1-1.md"
    before = path.read_bytes()
    with pytest.raises(ToolError):
        pm_update("US-TST-1-1", clear="depends_on", depends_on="US-TST-1-1")
    assert path.read_bytes() == before


def test_pm_update_clear_an_already_empty_field_succeeds(tmp_project):
    """`clear` is declarative — the requested end state already holds."""
    from projectman.server import pm_update

    _tool_story_with_tasks()
    result = yaml.safe_load(pm_update("US-TST-1-1", clear="tags,depends_on"))
    assert result["updated"]["tags"] == []
    assert result["updated"]["depends_on"] == []


def test_clear_is_recorded_in_the_activity_log(store):
    """The kwargs diff loop skips None, so clears need their own diff."""
    _story_with_task(store, tags=["security", "mvp"])
    store.update("US-TST-1-1", clear="tags")

    updates = [e for e in _activity(store) if e["event_type"] == "update"]
    changes = updates[-1]["changes"]
    assert changes["tags"] == {"before": ["security", "mvp"], "after": []}


def test_clearing_an_already_empty_field_logs_no_change(store):
    _story_with_task(store)
    store.update("US-TST-1-1", clear="tags")

    updates = [e for e in _activity(store) if e["event_type"] == "update"]
    assert "tags" not in updates[-1]["changes"]


def test_clear_skips_depends_on_validation(store):
    """An empty depends_on is trivially valid — nothing to check or cycle."""
    _story_with_task(store)
    store.create_task("US-TST-1", "Task 2", READY_BODY, points=1)
    store.update("US-TST-1-2", depends_on=["US-TST-1-1"])
    meta = store.update("US-TST-1-2", clear="depends_on")
    assert meta.depends_on == []


def test_clear_and_a_different_field_in_one_call(store):
    _story_with_task(store, tags=["a"])
    meta = store.update("US-TST-1-1", clear="tags", status="review")
    assert meta.tags == []
    assert meta.status.value == "review"


def test_cleared_lists_are_not_shared_between_items(store):
    """`_empty_value` hands out a fresh list each time."""
    _story_with_task(store, tags=["a"])
    store.create_task("US-TST-1", "Task 2", READY_BODY, points=1, tags=["b"])
    first = store.update("US-TST-1-1", clear="tags")
    second = store.update("US-TST-1-2", clear="tags")
    first.tags.append("leak")
    assert second.tags == []


# ─── §3 — the criterion, at the wire ─────────────────────────────
#
# The story's other acceptance criterion is "clearing depends_on and tags has
# an explicit affordance".  *Explicit* is a property of what the model reads
# and emits, so — as in §1 — these pin it at the boundary: the `tools/list`
# schema and prose that advertise the affordance, and a real `tools/call`
# payload that empties both fields without spelling emptiness once.  The last
# test pins the consequence that makes clearing depends_on worth having.


def test_a_wire_clear_of_depends_on_and_tags_needs_no_empty_value(tmp_project):
    """The measured malformed call — 17 attempts to empty depends_on with no
    documented sentinel — has a sentinel-free spelling end to end."""
    from projectman.server import pm_update

    _tool_story_with_tasks(n=2)
    pm_update("US-TST-1-2", depends_on="US-TST-1-1", tags="security,mvp")

    arguments = {"id": "US-TST-1-2", "clear": "depends_on,tags"}
    _assert_spellable(arguments)

    is_error, body = _call_over_the_wire("pm_update", arguments)
    assert not is_error, body
    updated = yaml.safe_load(body)["updated"]
    assert updated["depends_on"] == []
    assert updated["tags"] == []

    meta, _ = Store(tmp_project).get_task("US-TST-1-2")
    assert meta.depends_on == []
    assert meta.tags == []


def test_the_clear_schema_is_a_string_of_field_names():
    """The affordance is reachable at the wire, and its value is content —
    a field name the model already holds, never a placeholder for absence."""
    schema = _tool_schemas()["pm_update"].inputSchema
    clear = schema["properties"]["clear"]

    types_offered = [
        entry.get("type") for entry in clear.get("anyOf", [{"type": clear.get("type")}])
    ]
    assert "string" in types_offered, clear
    assert not schema.get("required"), schema.get("required")


def test_the_clear_affordance_is_documented_for_depends_on_and_tags():
    """An affordance the prose does not name is not explicit: the docstring is
    where a model looks for the spelling, and both fields must be in it."""
    # Wrapped prose: compare on collapsed whitespace, not on line breaks.
    update = " ".join((_tool_schemas()["pm_update"].description or "").split())

    assert "clear:" in update
    assert '"depends_on"' in update
    assert '"tags"' in update
    assert '"depends_on,tags"' in update  # both at once is spelled out
    for name in ("assignee", "depends_on", "epic_id", "points", "tags"):
        assert name in update


def test_clearing_depends_on_unblocks_the_dependent(tmp_project):
    """Clearing is not cosmetic — the readiness gate reads the same field."""
    from projectman.server import pm_grab, pm_update

    _tool_story_with_tasks(n=2)
    pm_update("US-TST-1-2", depends_on="US-TST-1-1")

    blocked = yaml.safe_load(pm_grab("US-TST-1-2"))
    assert blocked["status"] == "not_ready"
    assert any("US-TST-1-1" in b for b in blocked["blockers"])

    pm_update("US-TST-1-2", clear="depends_on")

    assert "grabbed" in yaml.safe_load(pm_grab("US-TST-1-2"))
