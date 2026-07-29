"""Genuine failures raise real MCP errors (US-PM-2-3).

Closes three of US-PM-2's acceptance criteria:

* "Tool failures raise a real MCP error rather than returning an error string body"
* "is_error is set on every failure path"
* "No tool returns a body beginning with the error prefix"

``docs/reference/error-paths-inventory.md`` classifies 141 error-return sites,
of which 86 are GENUINE FAILURE and MCP-reachable: 45 generic
``except Exception as e: return f"error: {e}"`` handlers, 14 explicit
``server.py`` sites, and 27 in ``hub/registry.py`` reached through three call
sites.  All of them now raise.

The mechanism is ``mcp.server.fastmcp.exceptions.ToolError``.  FastMCP wraps
anything raised out of a tool body (``Tool.run``) and the low-level server
renders it as a ``CallToolResult`` with ``isError=True`` — so raising *is* how
this server sets ``is_error``.  ``projectman.server._failed`` is the one helper
every converted generic handler uses; see its docstring.

This file is US-PM-2-3's own proof: one representative case per failure class
named in the task, plus the two whole-surface checks (no ``error:`` body can be
produced at all, and the epic's own instrument no longer sees a soft error).
Sibling task US-PM-2-5 does the exhaustive per-class sweep, and
``tests/test_expected_negatives.py`` asserts the converse for the three
EXPECTED NEGATIVE sites, which must *not* raise.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from tools.usage_telemetry import classify as cf
from tools.usage_telemetry.extract import ToolCall, ToolResult

SERVER_PY = Path(__file__).resolve().parents[1] / "src" / "projectman" / "server.py"

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def _clear_store_cache():
    from projectman.server import _store_cache

    _store_cache.clear()
    yield
    _store_cache.clear()


def _in_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)


# --------------------------------------------------------------------------
# One representative failure per class named in the task.
# --------------------------------------------------------------------------


def test_config_not_found_raises(tmp_path_factory, monkeypatch):
    """Config-not-found — the highest-volume live genuine failure (observed x8).

    Reaches the caller through the generic handlers on pm_status / pm_docs /
    pm_repair / pm_list_sprints (inventory 2, 5.5).  Asserted on the real
    ``find_project_root`` failure, not a mock, so the whole path is exercised.
    """
    from projectman.server import pm_status

    monkeypatch.chdir(tmp_path_factory.mktemp("no_project_here"))
    with pytest.raises(ToolError) as excinfo:
        pm_status()
    assert "No .project/config.yaml found in any parent directory" in str(excinfo.value)


def test_malformed_input_raises(tmp_project, monkeypatch):
    """Malformed input — a doc name outside the enum (inventory 3.2, 5.1).

    The contrast that keeps this honest: an *unknown* doc name is a bad
    argument and raises, while an uncreated-but-valid doc is an expected
    negative and stays a success.  Both are asserted here.
    """
    _in_project(tmp_project, monkeypatch)
    from projectman.server import pm_docs

    with pytest.raises(ToolError) as excinfo:
        pm_docs("nonsense")
    message = str(excinfo.value)
    assert "unknown doc 'nonsense'" in message
    # The recovery hint the old body carried is preserved.
    assert "vision" in message and "architecture" in message

    # ... and the neighbouring expected negative is untouched by this change.
    body = pm_docs("vision")
    assert not body.lstrip().startswith("error:")
    assert yaml.safe_load(body)["outcome"] == "expected_negative"


def test_constraint_violation_raises(tmp_project, monkeypatch):
    """Constraint violation — a task dependency cycle (``store.py`` DFS check).

    Reaches the caller through pm_update's generic handler (inventory 3.1,
    line 1112).  A cycle is a rejected write: the store rolled back and the
    caller's requested state does not exist.
    """
    _in_project(tmp_project, monkeypatch)
    from projectman.server import (
        pm_create_story,
        pm_create_task,
        pm_update,
    )

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "First", READY_BODY, points=1)
    pm_create_task("US-TST-1", "Second", READY_BODY, points=1)
    pm_update("US-TST-1-2", depends_on="US-TST-1-1")

    with pytest.raises(ToolError) as excinfo:
        pm_update("US-TST-1-1", depends_on="US-TST-1-2")
    assert "Dependency cycle detected" in str(excinfo.value)


def test_nonexistent_id_raises(tmp_project, monkeypatch):
    """Nonexistent id — the caller asserted an id that does not exist.

    Inventory 5.5 classifies every single-id site this way.  Three tools are
    checked rather than one because the id is the caller's assertion in each
    and the message must still name the id it could not find.
    """
    _in_project(tmp_project, monkeypatch)
    from projectman.server import pm_archive, pm_get, pm_update

    for fn in (pm_get, pm_update, pm_archive):
        with pytest.raises(ToolError) as excinfo:
            fn("US-TST-9-9")
        assert "US-TST-9-9" in str(excinfo.value), fn.__name__


def test_constraint_violation_on_empty_argument_raises(tmp_project, monkeypatch):
    """An explicit (non-generic) site: pm_changeset_create with no projects.

    Inventory 3.3 — one of the four plain-string ``return "error: ..."`` sites
    the story's own grep does not find.
    """
    _in_project(tmp_project, monkeypatch)
    from projectman.server import pm_changeset_create

    with pytest.raises(ToolError) as excinfo:
        pm_changeset_create("no-projects", "")
    assert str(excinfo.value) == "at least one project is required"


def test_mutation_on_absent_malformed_file_raises(tmp_project, monkeypatch):
    """Inventory 5.3: a mutation whose target does not exist is a failure.

    Not a lookup over an optional set — the caller asserted the file exists by
    asking for it to be restored.  The listing is included in the message so
    the caller can recover in one turn.
    """
    _in_project(tmp_project, monkeypatch)
    from projectman.server import pm_restore

    (tmp_project / ".project" / "malformed").mkdir()
    (tmp_project / ".project" / "malformed" / "REAL-1.md").write_text("junk")

    with pytest.raises(ToolError) as excinfo:
        pm_restore("GHOST-1.md")
    message = str(excinfo.value)
    assert "GHOST-1.md not found in malformed/" in message
    assert "REAL-1.md" in message  # the recovery listing (inventory 5.3)


# --------------------------------------------------------------------------
# The hub call-site guards — 27 registry.py sites, 3 call sites.
# --------------------------------------------------------------------------


def test_hub_guard_converts_registrys_three_error_shapes():
    """Inventory 4: the guard covers exactly the shapes registry.py produces.

    ``registry.py`` keeps its in-band error contract because the CLI depends on
    it; the conversion happens at the MCP boundary.  This asserts the guard
    recognises all three shapes and passes everything else through untouched.
    """
    from projectman.server import _raise_on_hub_error

    # 1. repair() returns a bare string.
    with pytest.raises(ToolError) as excinfo:
        _raise_on_hub_error("error: not a hub project — run 'projectman init --hub'")
    assert str(excinfo.value).startswith("not a hub project")

    # 2. registry.pm_push folds push_hub / hub_push_with_rebase /
    #    _push_subproject errors into a top-level "error" key.
    with pytest.raises(ToolError) as excinfo:
        _raise_on_hub_error({"pushed": False, "error": "push failed: remote hung up"})
    assert str(excinfo.value) == "push failed: remote hung up"

    # 3. coordinated_push carries them in "report" and "hub_result".
    with pytest.raises(ToolError):
        _raise_on_hub_error({"pushed": False, "report": "error: not a hub project"})
    with pytest.raises(ToolError) as excinfo:
        _raise_on_hub_error(
            {"pushed": False, "hub_result": {"error": "push rejected after max retries"}}
        )
    assert str(excinfo.value) == "push rejected after max retries"


def test_hub_guard_passes_successes_and_partials_through():
    """The guard must not manufacture failures.

    A subproject failing while the hub push succeeds is a genuine *partial
    success*; raising would throw away the projects that did push.  Same
    reasoning the inventory applies to multi-id results in 7.2.
    """
    from projectman.server import _raise_on_hub_error

    ok = {"pushed": True, "scope": "hub", "error": None}
    assert _raise_on_hub_error(ok) is ok
    assert _raise_on_hub_error("repaired 3 projects") == "repaired 3 projects"

    partial = {
        "pushed": True,
        "hub_result": {"pushed": True, "error": None},
        "sub_result": [{"pushed": False, "error": "push failed"}],
    }
    assert _raise_on_hub_error(partial) is partial


def test_pm_repair_outside_a_hub_raises(tmp_project, monkeypatch):
    """A hub-only tool called in a non-hub repo (inventory 3.3)."""
    _in_project(tmp_project, monkeypatch)
    from projectman.server import pm_repair

    with pytest.raises(ToolError) as excinfo:
        pm_repair()
    assert "not a hub project" in str(excinfo.value)


# --------------------------------------------------------------------------
# Whole-surface checks — the acceptance criteria, asserted directly.
# --------------------------------------------------------------------------


def test_no_tool_can_return_an_error_prefixed_body():
    """AC: "No tool returns a body beginning with the error prefix".

    Static proof over the whole module rather than a sample of calls: a body
    beginning with ``error:`` can only be produced by a ``return`` of such a
    string, so if no such return statement exists, no such body can exist.
    Comments and docstrings are stripped first so the inventory references in
    the module's own documentation do not count.
    """
    source = SERVER_PY.read_text()
    # Drop docstrings/comments — only executable returns matter.
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            rendered = ast.unparse(node.value)
            assert not re.match(r"""^f?['"]error:""", rendered), (
                f"server.py:{node.lineno} still returns an error-prefixed body: {rendered}"
            )


def test_no_tool_returns_a_structured_error_payload():
    """The six sites the story's grep cannot see (inventory 1, 3.4).

    ``_yaml_dump({"status": "error", ...})`` renders as ``status: error`` and
    matches neither of ``classify.py``'s anchored patterns, so it was invisible
    even to the telemetry scanner.  None may remain.
    """
    source = SERVER_PY.read_text()
    assert '"status": "error"' not in source


def _failing_calls(tmp_project):
    """Every representative failure, as ``(label, callable, args)``.

    ``pm_run_log`` is deliberately absent: ``store.get_run_log`` returns ``[]``
    for an unknown id rather than raising, so a missing id there is not an
    error-return site at all and is outside this task's scope (the inventory
    catalogues error *returns*).  It is a separate pre-existing gap — a silent
    empty result for an id the caller asserted — and is noted here rather than
    papered over by omission.
    """
    from projectman.server import (
        pm_archive,
        pm_batch_get,
        pm_changeset_create,
        pm_changeset_status,
        pm_docs,
        pm_estimate,
        pm_get,
        pm_get_sprint,
        pm_grab,
        pm_repair,
        pm_restore,
        pm_scope,
        pm_update,
        pm_update_doc,
    )

    return [
        ("pm_get missing id", pm_get, ("US-TST-9-9",)),
        ("pm_grab missing id", pm_grab, ("US-TST-9-9",)),
        ("pm_update missing id", pm_update, ("US-TST-9-9",)),
        ("pm_archive missing id", pm_archive, ("US-TST-9-9",)),
        ("pm_estimate missing id", pm_estimate, ("US-TST-9-9",)),
        ("pm_scope missing id", pm_scope, ("US-TST-9-9",)),
        ("pm_get_sprint missing id", pm_get_sprint, ("SPRINT-999",)),
        ("pm_changeset_status missing id", pm_changeset_status, ("CS-TST-999",)),
        ("pm_batch_get bad type", pm_batch_get, ("task",)),
        ("pm_docs unknown name", pm_docs, ("nonsense",)),
        ("pm_update_doc unknown name", pm_update_doc, ("nonsense", "x")),
        ("pm_changeset_create no projects", pm_changeset_create, ("cs", "")),
        ("pm_restore absent file", pm_restore, ("GHOST-1.md",)),
        ("pm_repair not a hub", pm_repair, ()),
    ]


def test_every_representative_failure_raises(tmp_project, monkeypatch):
    """AC: "is_error is set on every failure path".

    Raising is how ``is_error`` gets set here (see the module docstring), so
    asserting the raise asserts the criterion.  Each case is asserted to raise
    ``ToolError`` specifically — not merely "something" — because a raw
    ``FileNotFoundError`` escaping a tool would also set ``is_error`` but would
    mean the site had simply been deleted rather than converted.
    """
    _in_project(tmp_project, monkeypatch)
    for label, fn, args in _failing_calls(tmp_project):
        with pytest.raises(ToolError) as excinfo:
            fn(*args)
        # Requirement: the human-readable message survives the conversion.
        assert str(excinfo.value).strip(), label
        assert not str(excinfo.value).startswith("error:"), label


def test_is_error_is_actually_set_on_the_wire(tmp_project, monkeypatch):
    """AC: "is_error is set on every failure path" — asserted end to end.

    Every other test here asserts the *raise*; this one drives a real
    ``tools/call`` request through the low-level server's own request handler
    and reads ``isError`` off the ``CallToolResult``.  That closes the gap
    between "the function raises" and "the caller sees a hard error", which is
    the criterion actually being claimed.

    The same request is made for an expected negative and a plain success, so
    the test would also catch the opposite failure mode — converting so
    aggressively that valid answers start reporting ``is_error`` (US-PM-2-4's
    work, which this task must not undo).
    """
    import anyio
    import mcp.types as types

    monkeypatch.chdir(tmp_project)
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def call(name: str, arguments: dict):
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        return bool(result.isError), result.content[0].text

    async def main():
        # 1. Genuine failures -> isError, with the message preserved.
        for name, arguments, expected in (
            ("pm_get", {"id": "US-TST-9-9"}, "Task not found: US-TST-9-9"),
            ("pm_docs", {"doc": "nonsense"}, "unknown doc 'nonsense'"),
            ("pm_changeset_create", {"title": "cs", "projects": ""},
             "at least one project is required"),
        ):
            is_error, text = await call(name, arguments)
            assert is_error is True, name
            assert expected in text, (name, text)

        # 2. An expected negative stays a success (US-PM-2-4 must survive).
        is_error, text = await call("pm_docs", {"doc": "vision"})
        assert is_error is False
        assert yaml.safe_load(text)["outcome"] == "expected_negative"

        # 3. A plain success is still a plain success.
        is_error, text = await call("pm_status", {})
        assert is_error is False
        assert not text.lstrip().startswith("error:")

    anyio.run(main)


def test_the_epics_instrument_sees_no_soft_error_from_any_of_them(
    tmp_project, monkeypatch
):
    """Requirement 8 — checked with ``tools/usage_telemetry/classify.py`` itself.

    These paths no longer produce a response body at all, so there is nothing
    for ``soft_error_pattern`` to match.  The corpus below is what the harness
    would record for them now: ``is_error=True`` results.  Every one must
    classify as a *hard* error and none as soft — the failure is still counted,
    it has simply moved into the column a transport-level metric can see.
    """
    _in_project(tmp_project, monkeypatch)

    calls = []
    for seq, (label, fn, args) in enumerate(_failing_calls(tmp_project)):
        with pytest.raises(ToolError) as excinfo:
            fn(*args)
        call = ToolCall(
            tool_use_id=f"tu-{seq}",
            name=f"mcp__projectman__{label.split()[0]}",
            input={},
            timestamp="2026-07-29T00:00:00Z",
            session="sess-a",
            session_id="sess-a",
            project="proj",
            source_file="proj/sess-a.jsonl",
            line_no=seq + 1,
            seq=seq,
        )
        call.result = ToolResult(
            tool_use_id=f"tu-{seq}", is_error=True, text=str(excinfo.value)
        )
        calls.append(call)

        # The message, had it still been a body, is not what matters — there is
        # no body.  Assert the classifier's body-level predicate sees nothing.
        assert cf.soft_error_pattern(json.dumps({"result": str(excinfo.value)})) is None, label

    report = cf.classify_all(calls)
    assert report.total == len(calls)
    assert report.soft == 0
    assert report.hard == len(calls)
    assert report.failures == len(calls)
    assert report.top_messages() == []
