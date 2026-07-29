"""Every known failure class sets ``is_error`` (US-PM-2-5).

The exhaustive sweep behind three of US-PM-2's acceptance criteria:

1. "Tool failures raise a real MCP error rather than returning an error string body"
2. "is_error is set on every failure path"
3. "No tool returns a body beginning with the error prefix"  (AC 4)

``docs/reference/error-paths-inventory.md`` is the parameterisation source.
:data:`CASES` drives one live call per *failure class* it catalogues — not a
handful of examples — and each case is asserted at **both** layers that matter:

* the Python function raises :class:`~mcp.server.fastmcp.exceptions.ToolError`;
* the real low-level ``CallToolRequest`` handler renders ``isError=True``.

The second is the one the criterion actually claims.  ``pytest.raises(ToolError)``
only proves the function raises; it says nothing about what the caller on the
other side of the transport sees.  Both are run for every case.

Beyond the per-class sweep there are three whole-surface checks:

* :func:`test_no_registered_tool_can_return_an_error_prefixed_body` — a static
  scan of every ``return`` in every one of the 47 registered tools;
* two dynamic sweeps that *drive* all 47 tools (in a broken environment and
  against hostile arguments) and assert no response body begins with ``error:``;
* :func:`test_the_instrument_scores_every_converted_failure_as_a_hard_error` —
  the epic's own instrument, ``tools/usage_telemetry/classify.py``, run over the
  whole corpus of converted failures.

All three assert the *count* of things they checked against
``mcp.list_tools()`` / ``len(CASES)``, so none of them can silently degrade into
checking nothing.

Sibling coverage, deliberately not duplicated here:
``tests/test_genuine_failures_raise.py`` (US-PM-2-3, one representative per
class plus the hub-guard unit tests) and ``tests/test_expected_negatives.py``
(US-PM-2-4, the converse — the three sites that must *not* raise).
"""

import ast
import json
import re
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import mcp.types as types
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


# ===========================================================================
# The failure-class taxonomy, from the inventory.
# ===========================================================================


@dataclass(frozen=True)
class Case:
    """One live call that must fail, tagged with the class it represents.

    ``arguments`` is a wire-shaped mapping so the very same case can be driven
    through the Python function *and* through ``tools/call``; anything the world
    has to compute at runtime (a port number, say) arrives via the extra
    arguments :meth:`Worlds.enter` returns.
    """

    failure_class: str
    #: Inventory section this case comes from.
    inventory: str
    #: Registered MCP tool name.
    tool: str
    arguments: dict
    #: Fragment of the pre-conversion body text that must survive into the error.
    expect: str
    #: Which world the call is made in (see :class:`Worlds`).
    world: str = "project"
    #: Fragment expected on the wire, when FastMCP rejects the call before the
    #: tool body runs and so produces a different (schema-level) message.
    expect_wire: str = ""
    #: Extra arguments the world supplies at runtime, by name.
    from_world: tuple = field(default=())

    @property
    def wire_expect(self) -> str:
        return self.expect_wire or self.expect

    def __str__(self) -> str:  # pytest test id
        return f"{self.failure_class}:{self.tool}"


CASES: list[Case] = [
    # -- config not found (inventory 2, 3.1, 5.5) — 8 observed calls, the
    #    highest-volume live genuine failure in the corpus.
    Case("config_not_found", "3.1", "pm_status", {}, "No .project/config.yaml", world="empty"),
    Case("config_not_found", "3.1", "pm_docs", {"doc": "project"}, "No .project/config.yaml", world="empty"),
    Case("config_not_found", "3.1", "pm_repair", {}, "No .project/config.yaml", world="empty"),
    Case("config_not_found", "3.1", "pm_list_sprints", {}, "No .project/config.yaml", world="empty"),
    # -- nonexistent id, one case per item type (inventory 5.5).
    Case("nonexistent_epic", "3.1", "pm_epic", {"id": "EPIC-TST-99"}, "Epic not found: EPIC-TST-99"),
    Case("nonexistent_story", "3.1", "pm_get", {"id": "US-TST-99"}, "Story not found: US-TST-99"),
    Case("nonexistent_story", "3.1", "pm_estimate", {"id": "US-TST-99"}, "Story not found: US-TST-99"),
    Case("nonexistent_story", "3.1", "pm_scope", {"id": "US-TST-99"}, "Story not found: US-TST-99"),
    Case("nonexistent_story", "3.1", "pm_create_task", {"story_id": "US-TST-99", "title": "T", "description": READY_BODY}, "Story not found: US-TST-99"),
    Case("nonexistent_task", "3.1", "pm_grab", {"task_id": "US-TST-9-9"}, "Task not found: US-TST-9-9"),
    Case("nonexistent_sprint", "3.1", "pm_get_sprint", {"sprint_id": "SPRINT-TST-99"}, "Sprint not found: SPRINT-TST-99"),
    Case("nonexistent_sprint", "3.1", "pm_update_sprint", {"sprint_id": "SPRINT-TST-99", "name": "x"}, "Sprint not found: SPRINT-TST-99"),
    Case("nonexistent_changeset", "3.1", "pm_changeset_status", {"changeset_id": "CS-TST-99"}, "Changeset not found: CS-TST-99"),
    Case("nonexistent_changeset", "3.1", "pm_changeset_add_project", {"changeset_id": "CS-TST-99", "name": "p", "ref": "b"}, "Changeset not found: CS-TST-99"),
    Case("nonexistent_changeset", "3.1", "pm_changeset_create_prs", {"changeset_id": "CS-TST-99"}, "Changeset not found: CS-TST-99"),
    Case("nonexistent_changeset", "3.1", "pm_changeset_push", {"changeset_id": "CS-TST-99"}, "Changeset not found: CS-TST-99"),
    Case("nonexistent_item", "3.1", "pm_update", {"id": "US-TST-99"}, "Item not found: US-TST-99"),
    Case("nonexistent_item", "3.1", "pm_archive", {"id": "US-TST-99"}, "Item not found: US-TST-99"),
    # -- malformed / invalid input (inventory 3.2).
    Case("bad_enum_value", "3.2", "pm_docs", {"doc": "nonsense"}, "unknown doc 'nonsense'"),
    Case("bad_enum_value", "3.2", "pm_update_doc", {"doc": "nonsense", "content": "x"}, "unknown doc 'nonsense'"),
    Case("bad_type", "3.1", "pm_batch_get", {"type": "task"}, "Unknown item type: task"),
    Case("bad_type", "3.1", "pm_batch_get", {"type": "widgets"}, "Unknown item type: widgets"),
    Case(
        "bad_type", "3.1", "pm_create_tasks",
        {"story_id": "US-TST-1", "tasks": "not-a-list"},
        "object has no attribute",
        # FastMCP validates the declared ``list[dict]`` before the body runs, so
        # the wire message is the schema's, not the body's.
        expect_wire="valid list",
    ),
    Case("unparseable_argument", "3.1", "pm_create_sprint", {"name": "S", "start_date": "not-a-date"}, "Invalid isoformat string"),
    # -- constraint violations (inventory 3.1, store.py validation).
    Case("dependency_cycle", "3.1", "pm_update", {"id": "US-TST-1-1", "depends_on": "US-TST-1-2"}, "Dependency cycle detected"),
    Case("unknown_dependency", "3.1", "pm_update", {"id": "US-TST-1-1", "depends_on": "US-TST-9-9"}, "US-TST-9-9 does not exist"),
    Case("invalid_status", "3.1", "pm_update", {"id": "US-TST-1-1", "status": "bogus"}, "Input should be 'todo'"),
    Case("invalid_status", "3.1", "pm_update", {"id": "US-TST-1", "status": "bogus"}, "Input should be 'backlog'"),
    Case("invalid_status", "3.1", "pm_update_sprint", {"sprint_id": "SPRINT-TST-1", "status": "bogus"}, "'bogus' is not a valid SprintStatus"),
    Case("invalid_points", "3.1", "pm_update", {"id": "US-TST-1-1", "points": 7}, "Points must be fibonacci"),
    Case("invalid_points", "3.1", "pm_create_task", {"story_id": "US-TST-1", "title": "T", "description": READY_BODY, "points": 7}, "Points must be fibonacci"),
    Case("invalid_priority", "3.1", "pm_create_story", {"title": "S", "description": "d", "priority": "urgent"}, "'urgent' is not a valid Priority"),
    # -- argument validation, the explicit plain-string sites (inventory 3.3).
    Case("empty_required_argument", "3.3", "pm_changeset_create", {"title": "cs", "projects": ""}, "at least one project is required"),
    Case(
        "missing_required_argument", "3.3", "pm_fix_malformed",
        {"filename": "REAL-1.md", "id": "US-TST-2-1", "title": "T", "item_type": "task"},
        "story_id is required for tasks",
    ),
    # -- a mutation whose target file is absent (inventory 3.2, 5.3).
    Case("not_found_file", "5.3", "pm_fix_malformed", {"filename": "GHOST-1.md", "id": "US-TST-2", "title": "T", "item_type": "story"}, "GHOST-1.md not found in malformed/"),
    Case("not_found_file", "5.3", "pm_restore", {"filename": "GHOST-1.md"}, "GHOST-1.md not found in malformed/"),
    # -- an asserted hub project that is not registered (inventory 3.2).
    Case("unregistered_hub_project", "3.2", "pm_audit", {"project": "nope"}, "project 'nope' not found in hub", world="hub"),
    Case("unregistered_hub_project", "3.2", "pm_git_status", {"project": "nope"}, "project 'nope' not found in hub status", world="hub"),
    # -- the three hub guards (inventory 4): one per shape registry.py produces.
    Case("hub_error_string", "4", "pm_repair", {}, "not a hub project"),
    Case("hub_error_dict", "4", "pm_push", {"scope": "bogus"}, "invalid scope 'bogus'", world="hub"),
    Case("hub_error_dict", "4", "pm_push", {"scope": "project:nope"}, "project 'nope' not registered in hub", world="hub"),
    Case("hub_error_report", "4", "pm_push_all", {"dry_run": True}, "not a hub project"),
    # -- web / port failures (inventory 3.4).
    Case("port_in_use", "3.4", "pm_web_start", {}, "is already in use", world="port_taken", from_world=("port",)),
    Case("missing_web_dependency", "3.4", "pm_web_start", {}, "Web dependencies not installed", world="no_web_deps", from_world=("port",)),
    Case("no_project_for_web", "3.4", "pm_web_start", {}, "No project found", world="empty"),
    Case("web_subprocess_failure", "3.4", "pm_web_start", {}, "no subprocess in tests", world="free_port", from_world=("port",)),
    Case("web_process_failure", "3.4", "pm_web_stop", {}, "cannot signal this process", world="web_running_broken"),
]

#: Every failure class the inventory catalogues as MCP-reachable.  Asserted
#: against :data:`CASES` so a class can never be quietly dropped from the sweep.
EXPECTED_CLASSES = {
    "config_not_found",
    "nonexistent_epic",
    "nonexistent_story",
    "nonexistent_task",
    "nonexistent_sprint",
    "nonexistent_changeset",
    "nonexistent_item",
    "bad_enum_value",
    "bad_type",
    "unparseable_argument",
    "dependency_cycle",
    "unknown_dependency",
    "invalid_status",
    "invalid_points",
    "invalid_priority",
    "empty_required_argument",
    "missing_required_argument",
    "not_found_file",
    "unregistered_hub_project",
    "hub_error_string",
    "hub_error_dict",
    "hub_error_report",
    "port_in_use",
    "missing_web_dependency",
    "no_project_for_web",
    "web_subprocess_failure",
    "web_process_failure",
}


# ===========================================================================
# Worlds — the environment each class needs in order to fail for real.
# ===========================================================================


PROJECT_CONFIG = {
    "name": "test-project",
    "prefix": "TST",
    "description": "A test project",
    "hub": False,
    "next_story_id": 1,
    "projects": [],
}


def _no_subprocess(*args, **kwargs):
    """Stand-in for ``subprocess.Popen``.

    Nothing in this file may spawn a real uvicorn: the point is to exercise the
    *failure* paths, and a leaked server process would outlive the test session.
    It doubles as the ``web_subprocess_failure`` case's trigger.
    """
    raise RuntimeError("no subprocess in tests")


class _UnkillableProcess:
    """A running web process whose ``terminate()`` fails (inventory 3.4, 2424)."""

    pid = 4242

    def poll(self):
        return None

    def terminate(self):
        raise PermissionError("cannot signal this process")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Worlds:
    """Builds and enters the environment a :class:`Case` needs.

    Memoised per test, so a test that walks every case pays for each world once
    and repeated cases in the same world share it.
    """

    def __init__(self, tmp_path_factory, monkeypatch):
        self._factory = tmp_path_factory
        self._mp = monkeypatch
        self._roots: dict[str, Path] = {}
        self._sockets: list[socket.socket] = []

    # -- construction -------------------------------------------------------

    def _project_root(self) -> Path:
        if "project" not in self._roots:
            root = self._factory.mktemp("project")
            proj = root / ".project"
            (proj / "stories").mkdir(parents=True)
            (proj / "tasks").mkdir()
            (proj / "config.yaml").write_text(yaml.safe_dump(PROJECT_CONFIG))
            self._roots["project"] = root
            self._seed(root)
        return self._roots["project"]

    def _seed(self, root: Path) -> None:
        """Populate the project with the items the cases assert against.

        A story, an epic, a sprint, and two tasks where the second already
        depends on the first — that last edge is what makes the
        ``dependency_cycle`` case a real cycle rather than a missing id.
        """
        import os

        cwd = os.getcwd()
        os.chdir(root)
        try:
            from projectman.server import (
                _store_cache,
                pm_create_epic,
                pm_create_sprint,
                pm_create_story,
                pm_create_task,
                pm_update,
            )

            _store_cache.clear()
            pm_create_story("Story", "Description")
            pm_update("US-TST-1", status="active")
            pm_create_task("US-TST-1", "First", READY_BODY, points=1)
            pm_create_task("US-TST-1", "Second", READY_BODY, points=1)
            pm_update("US-TST-1-2", depends_on="US-TST-1-1")
            pm_create_epic("Epic", "Description")
            pm_create_sprint("Sprint 1")
            _store_cache.clear()
        finally:
            os.chdir(cwd)

        malformed = root / ".project" / "malformed"
        malformed.mkdir(exist_ok=True)
        (malformed / "REAL-1.md").write_text("junk with no frontmatter\n")

    def _hub_root(self) -> Path:
        if "hub" not in self._roots:
            root = self._factory.mktemp("hub")
            proj = root / ".project"
            for sub in ("stories", "tasks", "projects", "roadmap", "dashboards"):
                (proj / sub).mkdir(parents=True)
            (proj / "config.yaml").write_text(
                yaml.safe_dump({**PROJECT_CONFIG, "name": "test-hub", "prefix": "HUB", "hub": True})
            )
            self._roots["hub"] = root
        return self._roots["hub"]

    def _empty_root(self) -> Path:
        if "empty" not in self._roots:
            self._roots["empty"] = self._factory.mktemp("no_project_anywhere")
        return self._roots["empty"]

    # -- entry --------------------------------------------------------------

    def enter(self, name: str) -> dict:
        """chdir into world *name* and return the arguments only it can supply."""
        from projectman.server import _store_cache

        _store_cache.clear()

        if name == "empty":
            self._mp.chdir(self._empty_root())
            return {}
        if name == "hub":
            self._mp.chdir(self._hub_root())
            return {}

        self._mp.chdir(self._project_root())
        if name == "project":
            return {}
        if name == "free_port":
            return {"port": _free_port()}
        if name == "port_taken":
            taken = socket.socket()
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            self._sockets.append(taken)
            return {"port": taken.getsockname()[1]}
        if name == "no_web_deps":
            # ``None`` in sys.modules is the documented way to make an import
            # raise ImportError without uninstalling anything.
            self._mp.setitem(sys.modules, "uvicorn", None)
            return {"port": _free_port()}
        if name == "web_running_broken":
            import projectman.server as server

            self._mp.setattr(server, "_web_process", _UnkillableProcess())
            self._mp.setattr(server, "_web_host", "127.0.0.1")
            self._mp.setattr(server, "_web_port", 8000)
            return {}
        raise AssertionError(f"unknown world: {name}")

    def close(self):
        for sock in self._sockets:
            sock.close()


@pytest.fixture
def worlds(tmp_path_factory, monkeypatch):
    import projectman.server as server

    # Belt and braces: no test in this file may spawn a process.
    monkeypatch.setattr(server.subprocess, "Popen", _no_subprocess)
    built = Worlds(tmp_path_factory, monkeypatch)
    yield built
    built.close()
    server._store_cache.clear()


def arguments_for(case: Case, extra: dict) -> dict:
    return {**case.arguments, **{k: extra[k] for k in case.from_world}}


# ===========================================================================
# Layer 1 — the Python function raises a real MCP error.
# ===========================================================================


@pytest.mark.parametrize("case", CASES, ids=str)
def test_failure_class_raises_a_real_mcp_error(case, worlds):
    """AC 1: "Tool failures raise a real MCP error rather than returning a body".

    ``ToolError`` specifically, not merely "something": a raw ``FileNotFoundError``
    escaping a tool would also reach the caller as an error, but it would mean
    the site had been deleted rather than converted, and the message contract
    below would be at the mercy of whatever exception happened to escape.
    """
    import projectman.server as server

    extra = worlds.enter(case.world)
    tool = getattr(server, case.tool)

    with pytest.raises(ToolError) as excinfo:
        tool(**arguments_for(case, extra))

    message = str(excinfo.value)
    # AC 3, at the message level: the prefix is gone, not merely relocated.
    assert not message.lstrip().startswith("error:"), message
    assert message.strip(), case.failure_class


@pytest.mark.parametrize("case", CASES, ids=str)
def test_failure_class_keeps_the_human_readable_message(case, worlds):
    """The text that used to be in the response body is still reachable.

    Converting a body into an error is only a win if nothing the caller relied
    on is lost.  Each case pins the fragment that carried the actual
    information — the id that was not found, the enum values that *are* valid,
    the port to try instead.
    """
    import projectman.server as server

    extra = worlds.enter(case.world)
    with pytest.raises(ToolError) as excinfo:
        getattr(server, case.tool)(**arguments_for(case, extra))
    assert case.expect in str(excinfo.value), (case.failure_class, str(excinfo.value))


# ===========================================================================
# Layer 2 — the protocol.  This is the criterion actually being claimed.
# ===========================================================================


def call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler.

    ``mcp._mcp_server.request_handlers[CallToolRequest]`` is the same callable
    the stdio/SSE transports dispatch to, so ``isError`` here is exactly the
    ``is_error`` a client would observe.  Nothing about the tool is mocked.
    """
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


@pytest.mark.parametrize("case", CASES, ids=str)
def test_failure_class_sets_is_error_on_the_wire(case, worlds):
    """AC 2: "is_error is set on every failure path" — asserted at the protocol.

    A ``pytest.raises(ToolError)`` proves the *function* raises.  It does not
    prove the caller sees ``is_error``: FastMCP could catch and render the
    exception as a successful result, which is precisely the bug this story
    exists to fix.  This drives the real handler and reads ``isError`` off the
    ``CallToolResult``, for every class.
    """
    extra = worlds.enter(case.world)
    is_error, text = call_over_the_wire(case.tool, arguments_for(case, extra))

    assert is_error is True, (case.failure_class, text)
    # AC 3 on a real response body from a real failure.
    assert not text.lstrip().startswith("error:"), (case.failure_class, text)
    # Requirement: the message reaches the caller, in the error rather than the body.
    assert case.wire_expect in text, (case.failure_class, text)


def test_every_inventory_failure_class_is_covered():
    """The parameterisation cannot silently shrink.

    Without this, deleting cases from :data:`CASES` would make the whole sweep
    above pass trivially.  The class set is pinned, and so is a floor on the
    number of live calls behind it.
    """
    covered = {case.failure_class for case in CASES}
    assert covered == EXPECTED_CLASSES, covered.symmetric_difference(EXPECTED_CLASSES)
    assert len(CASES) >= 45, len(CASES)
    # Every case names the inventory section it came from.
    assert all(case.inventory for case in CASES)
    # The sweep spans the tool surface, not one convenient tool.
    assert len({case.tool for case in CASES}) >= 20


# ===========================================================================
# AC 4, as a standing guard — structural.
# ===========================================================================


def _tool_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    """Every function carrying an ``@mcp.tool(...)`` decorator, by name."""
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                found[node.name] = node
    return found


def registered_tool_names() -> set[str]:
    from projectman.server import mcp as mcp_server

    return {tool.name for tool in anyio.run(mcp_server.list_tools)}


ERROR_PREFIX_RETURN = re.compile(r"""^f?['"]\s*error\s*:""")


def test_no_registered_tool_can_return_an_error_prefixed_body():
    """AC 4 as a standing guard: a future ``return f"error: {e}"`` fails CI.

    Structural rather than sampled.  A body beginning with ``error:`` can only
    come from a ``return`` of such a string, so if no tool contains such a
    return, no such body can exist — including on paths no test happens to
    reach.  The scan also rejects the six structured payloads the story's own
    grep could not see (inventory 1, 3.4): a ``_yaml_dump`` of a dict whose
    first key is ``error``, or which carries ``status: "error"``, renders as an
    error report while matching neither anchored pattern in ``classify.py``.

    The guard cannot pass vacuously: the set of ``@mcp.tool``-decorated
    functions it found is asserted equal to the set the server actually
    registers, and every one of them is asserted to contain at least one
    ``return``.
    """
    tree = ast.parse(SERVER_PY.read_text())
    tools = _tool_functions(tree)

    # 1. The scan is looking at every registered tool — no more, no fewer.
    assert set(tools) == registered_tool_names(), set(tools).symmetric_difference(
        registered_tool_names()
    )
    assert len(tools) == 47, len(tools)

    # 2. Every return in every tool.
    checked_returns = 0
    for name, func in tools.items():
        returns = [n for n in ast.walk(func) if isinstance(n, ast.Return) and n.value]
        assert returns, f"{name} has no return to check — the scan would be vacuous"
        for node in returns:
            checked_returns += 1
            rendered = ast.unparse(node.value)
            assert not ERROR_PREFIX_RETURN.match(rendered), (
                f"server.py:{node.lineno} ({name}) returns an error-prefixed body: {rendered}"
            )
            for key, value in _literal_pairs(node.value):
                assert key != "error", (
                    f"server.py:{node.lineno} ({name}) returns a payload keyed on "
                    f"'error' — it renders as an 'error:' body: {rendered}"
                )
                assert not (key == "status" and value == "error"), (
                    f"server.py:{node.lineno} ({name}) returns status: error, which "
                    f"is a failure the telemetry scanner cannot see: {rendered}"
                )

    # 47 tools carry 65 returns after US-PM-2-3 turned the failure paths into
    # raises; the floor is a guard against the scan quietly emptying out.
    assert checked_returns >= 60, checked_returns


def _literal_pairs(value: ast.expr):
    """String key/value pairs of a dict literal returned (possibly via a call)."""
    node = value
    if isinstance(node, ast.Call) and node.args:
        node = node.args[0]
    if not isinstance(node, ast.Dict):
        return
    for key, val in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            yield key.value, val.value if isinstance(val, ast.Constant) else None


# ===========================================================================
# AC 4, as a standing guard — dynamic.
# ===========================================================================


def placeholder_arguments(schema: dict) -> dict:
    """The minimum arguments a tool will accept, all of them nonsense.

    Derived from the tool's own input schema so a newly added tool is swept
    automatically rather than needing to be listed here.
    """
    arguments = {}
    for name in schema.get("required", []):
        declared = schema.get("properties", {}).get(name, {}).get("type")
        arguments[name] = {"integer": 0, "number": 0, "boolean": False}.get(declared, "NOPE-1")
    return arguments


def sweep_every_tool() -> tuple[dict[str, tuple[bool, str]], int]:
    from projectman.server import mcp as mcp_server

    tools = anyio.run(mcp_server.list_tools)
    responses = {}
    for tool in tools:
        responses[tool.name] = call_over_the_wire(
            tool.name, placeholder_arguments(tool.inputSchema or {})
        )
    return responses, len(tools)


def assert_sweep_is_clean(responses: dict[str, tuple[bool, str]], total: int):
    assert len(responses) == total, (len(responses), total)
    assert total == 47, total
    for name, (is_error, text) in responses.items():
        assert not text.lstrip().startswith("error:"), (name, text[:200])
        if not is_error:
            # A success may not smuggle a failure into the body either.
            try:
                data = yaml.safe_load(text) if text.strip() else None
            except yaml.YAMLError:
                data = None  # pm_audit answers in markdown, not YAML
            if isinstance(data, dict):
                assert "error" not in data, (name, text[:200])
                assert data.get("status") != "error", (name, text[:200])


def test_driving_every_tool_in_a_broken_environment_yields_no_error_body(worlds):
    """AC 4 driven, not inferred: all 47 tools, in a directory with no project.

    Every tool's generic handler is reached here — that is 46 of the 62
    ``server.py`` sites in one sweep — and every response is checked.  The two
    tools that legitimately answer without a project (``pm_web_stop``,
    ``pm_web_status``) return their idempotent no-op bodies, which is why the
    assertion is "no ``error:`` body", not "everything errors".
    """
    worlds.enter("empty")
    responses, total = sweep_every_tool()
    assert_sweep_is_clean(responses, total)

    # The sweep really did exercise the failure paths, rather than finding a
    # working project by accident.
    errored = [name for name, (is_error, _) in responses.items() if is_error]
    assert len(errored) == 45, sorted(set(responses) - set(errored))


def test_driving_every_tool_with_hostile_arguments_yields_no_error_body(worlds):
    """The same sweep in a *valid* project, so the explicit sites are reached.

    The broken-environment sweep above only ever reaches each tool's generic
    handler.  Here every tool runs for real against ids and enum values that do
    not exist, which is what drives the 17 explicit ``server.py`` sites of
    inventory 3.2-3.4 and the id-lookup failures inside the store.
    """
    worlds.enter("project")
    responses, total = sweep_every_tool()
    assert_sweep_is_clean(responses, total)

    # A mix, by construction: some tools have a valid answer to a nonsense
    # argument (pm_search finds nothing), others fail.  Both must be clean.
    errored = [name for name, (is_error, _) in responses.items() if is_error]
    assert 15 <= len(errored) < total, len(errored)


# ===========================================================================
# The instrument agrees — tools/usage_telemetry/classify.py.
# ===========================================================================


def recorded_failure(tool: str, text: str, seq: int) -> ToolCall:
    """A joined :class:`ToolCall` exactly as the harness records a raised tool."""
    call = ToolCall(
        tool_use_id=f"tu-{seq}",
        name=f"mcp__projectman__{tool}",
        input={},
        timestamp="2026-07-29T00:00:00Z",
        session="sess-a",
        session_id="sess-a",
        project="proj",
        source_file="proj/sess-a.jsonl",
        line_no=seq + 1,
        seq=seq,
    )
    call.result = ToolResult(tool_use_id=f"tu-{seq}", is_error=True, text=text)
    return call


def test_the_instrument_scores_every_converted_failure_as_a_hard_error(worlds):
    """Requirement: the epic's measurement loop closes from the failure side.

    ``tools/usage_telemetry/classify.py`` is the instrument every number in this
    story comes from.  US-PM-2-6 proved it no longer counts the *expected
    negatives*; this proves the converse for the whole corpus of converted
    failures — each one is now a **hard** error (``is_error``), none is soft,
    and the true failure rate is unchanged at 100% of this corpus.  A conversion
    that merely stopped the instrument seeing the failure would fail here.
    """
    import projectman.server as server

    corpus = []
    for seq, case in enumerate(CASES):
        extra = worlds.enter(case.world)
        with pytest.raises(ToolError) as excinfo:
            getattr(server, case.tool)(**arguments_for(case, extra))
        message = str(excinfo.value)

        # 1. Nothing here can be read as a soft error any more: there is no
        #    body at all, and the message itself carries no error envelope.
        assert cf.soft_error_pattern(json.dumps({"result": message})) is None, case.failure_class
        # 2. ...and the instrument *would* have caught the old shape, so the
        #    clean result above is a real change rather than a blind spot.
        assert cf.soft_error_pattern(json.dumps({"result": f"error: {message}"})) == "envelope"

        corpus.append(recorded_failure(case.tool, message, seq))

    report = cf.classify_all(corpus)
    assert report.total == len(CASES)
    assert report.hard == len(CASES)
    assert report.soft == 0
    assert report.failures == len(CASES)
    assert report.failure_rate == 1.0
    assert report.primary_counts[cf.SOFT_ERROR] == 0
    assert report.primary_counts[cf.HARD_ERROR] == len(CASES)
    # top_messages() only ranks soft errors; every failure has moved out of it.
    assert report.top_messages() == []
    # Per-tool, because a study quotes the per-tool table.
    for tool, row in report.by_tool().items():
        assert row.failures == row.calls, tool
        assert row.soft == 0, tool
