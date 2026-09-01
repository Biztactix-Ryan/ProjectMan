"""The shared ID-alias resolver, and every tool wired to it (US-PM-3-5, -3-6).

Two conventions for the same argument grew side by side — the generic ``id``
and a typed one (``task_id``, ``sprint_id``, ``item_id``, ``changeset_id``) —
and callers guess wrong in both directions.  ``server._resolve_id`` is the one
mechanism that makes both spellings work; this file covers it in isolation
(every combination of the two spellings, including the empty ones) and then
drives **every aliased tool** end to end through the real ``tools/call``
handler, in both directions:

* canonical ``id``, typed alias — ``pm_get``, ``pm_update``, ``pm_archive``,
  ``pm_epic``, ``pm_estimate``, ``pm_scope``, ``pm_run_log``
* canonical typed name, alias ``id`` — ``pm_grab``, ``pm_get_sprint``,
  ``pm_update_sprint``, ``pm_activity``, and the four ``pm_changeset_*`` tools

``test_the_rollout_covers_every_id_taking_tool_that_should_have_one`` keeps the
table honest: a tool that takes an ID and is in neither the wired set nor the
justified-exclusion set fails.  The exclusions matter as much as the rollout —
``pm_update``'s ``epic_id`` and ``pm_create_task``'s ``story_id`` name a
*different* item from the one being acted on, so aliasing them would retarget
real calls.  That is asserted directly, not just left as a comment.

The conflict case is asserted at the protocol level as well as in Python:
US-PM-2 established that a genuine failure sets ``is_error`` rather than
returning an ``error:`` body, and a resolver that reported conflicts in the
body would quietly reintroduce exactly the class US-PM-2 removed.
"""

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.server import _resolve_id

#: The changeset and web families are hidden from ``tools/list`` by default
#: (US-PM-15-5).  Four of the nine aliased tools are ``pm_changeset_*``, and the
#: rollout checks read the alias set off a real ``tools/list``, so this
#: module needs the full surface registered.  ``tests/test_tool_gating.py`` asserts the gate itself.
pytestmark = pytest.mark.usefixtures("all_tool_families")



READY_TASK_BODY = """\
## Implementation

Do the thing properly.

## Testing

Run pytest.

## Definition of Done

- [ ] It is done
"""


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    _store_cache.clear()


# ===========================================================================
# The resolver in isolation — every combination of the two spellings.
# ===========================================================================


def test_canonical_only_resolves_to_the_canonical_value():
    """The pre-existing call shape, unchanged."""
    assert _resolve_id("task_id", "US-TST-1-1", id=None) == "US-TST-1-1"


def test_alias_only_resolves_to_the_alias_value():
    """The whole point of the story: the wrong spelling now works."""
    assert _resolve_id("task_id", None, id="US-TST-1-1") == "US-TST-1-1"


def test_both_spellings_with_the_same_value_is_not_an_error():
    """Unambiguous, so it is accepted — see the resolver's docstring.

    The model belt-and-braces this shape.  Rejecting it would trade one error
    class for another rather than removing one.
    """
    assert _resolve_id("task_id", "US-TST-1-1", id="US-TST-1-1") == "US-TST-1-1"


def test_both_spellings_agree_after_stripping():
    """Equality is compared on the stripped values, not the raw ones."""
    assert _resolve_id("task_id", " US-TST-1-1 ", id="US-TST-1-1") == "US-TST-1-1"


def test_both_spellings_with_different_values_is_a_hard_error():
    with pytest.raises(ToolError) as excinfo:
        _resolve_id("task_id", "US-TST-1-1", id="US-TST-2-2")
    message = str(excinfo.value)
    # Both values are named, so the caller can see which one it did not mean.
    assert "US-TST-1-1" in message and "US-TST-2-2" in message
    assert "task_id" in message and "id" in message
    # It is an error, not a body that merely says "error:" (US-PM-2 AC 4).
    assert not message.lstrip().startswith("error:")


def test_neither_spelling_is_the_missing_argument_error():
    """Aliasing moves this check out of schema validation, so it lives here."""
    with pytest.raises(ToolError) as excinfo:
        _resolve_id("task_id", None, id=None)
    message = str(excinfo.value)
    assert "task_id is required" in message
    # ...and the caller is told the other spelling exists.
    assert "id" in message


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_empty_alias_never_wins_over_a_real_canonical_value(blank):
    """Requirement 5: blank is 'not supplied', not a value that overrides."""
    assert _resolve_id("task_id", "US-TST-1-1", id=blank) == "US-TST-1-1"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_empty_canonical_never_wins_over_a_real_alias_value(blank):
    """The converse — the rule is symmetric, so neither spelling can blank the other."""
    assert _resolve_id("task_id", blank, id="US-TST-1-1") == "US-TST-1-1"


@pytest.mark.parametrize("blank", ["", "   "])
def test_two_blank_spellings_are_missing_not_conflicting(blank):
    """Two empties are not two different values — this must not read as a conflict."""
    with pytest.raises(ToolError) as excinfo:
        _resolve_id("task_id", blank, id="  ")
    assert "is required" in str(excinfo.value)
    assert "conflicting" not in str(excinfo.value)


def test_the_resolved_value_is_stripped():
    """An ID never legitimately carries whitespace; a stray space is a 'not found'."""
    assert _resolve_id("task_id", " US-TST-1-1\n", id=None) == "US-TST-1-1"


def test_more_than_one_alias_is_supported():
    """The signature takes any number of aliases, for tools that grow a third."""
    assert _resolve_id("id", None, task_id=None, story_id="US-TST-1") == "US-TST-1"
    with pytest.raises(ToolError) as excinfo:
        _resolve_id("id", None, task_id="US-TST-1-1", story_id="US-TST-1")
    assert "conflicting ids" in str(excinfo.value)


def test_the_canonical_value_is_the_one_returned_when_all_agree():
    """Nothing downstream of a tool body ever sees an alias."""
    assert _resolve_id("sprint_id", "SPRINT-TST-1", id="SPRINT-TST-1") == "SPRINT-TST-1"


def test_missing_argument_message_names_every_alias():
    message = str(pytest.raises(ToolError, _resolve_id, "id", None, task_id=None, story_id=None).value)
    assert "aliases: task_id, story_id" in message


# ---------------------------------------------------------------------------
# required=False — the IDs that are an optional filter, not the operand.
# ---------------------------------------------------------------------------


def test_an_optional_id_resolves_to_none_when_neither_spelling_is_given():
    """``pm_activity`` / ``pm_changeset_status`` mean "no filter", not "error"."""
    assert _resolve_id("item_id", None, required=False, id=None) is None


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_an_optional_id_treats_blank_spellings_as_no_filter(blank):
    assert _resolve_id("item_id", blank, required=False, id=blank) is None


def test_an_optional_id_still_resolves_either_spelling():
    assert _resolve_id("item_id", None, required=False, id="US-TST-1") == "US-TST-1"
    assert _resolve_id("item_id", "US-TST-1", required=False, id=None) == "US-TST-1"


def test_an_optional_id_still_rejects_a_conflict():
    """Two different filters are as unanswerable as two different operands."""
    with pytest.raises(ToolError) as excinfo:
        _resolve_id("item_id", "US-TST-1", required=False, id="US-TST-2")
    assert "conflicting ids" in str(excinfo.value)


# ===========================================================================
# The wired tools — one of each shape, through the real tool layer.
# ===========================================================================


def call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call``, so ``isError`` is what a client sees.

    Same handler the stdio/SSE transports dispatch to — nothing is mocked.
    Calling the Python function directly would prove the alias resolves but say
    nothing about whether FastMCP accepts the argument at the schema, which is
    half of what "the tool accepts both spellings" means.
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


@pytest.fixture
def seeded():
    """One target of every aliased shape: epic, story, tasks, sprints, changesets."""
    from projectman.server import (
        pm_changeset_create,
        pm_create_epic,
        pm_create_sprint,
        pm_create_story,
        pm_create_task,
        pm_update,
    )

    pm_create_epic("Epic One", "An epic")
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    for n in range(1, 5):
        pm_create_task("US-TST-1", f"Grab me {n}", READY_TASK_BODY, points=3)
    pm_create_sprint("Sprint One", goal="Ship it")
    pm_create_sprint("Sprint Two", goal="Ship it again")
    pm_changeset_create("cs-one", "alpha,beta")
    pm_changeset_create("cs-two", "alpha,beta")


class Wired:
    """One aliased tool, and everything the sweep below needs to drive it.

    ``ident``/``alias_ident`` differ only for the tools that **mutate** their
    target — ``pm_grab`` has no idempotent re-claim in this checkout, and
    archiving twice is a second, failing archive — so those two spellings are
    pointed at two different items.  ``other`` only has to differ from
    ``ident``: the resolver raises on a conflict before anything is looked up.
    """

    def __init__(
        self,
        tool,
        canonical,
        alias,
        ident,
        alias_ident=None,
        other="US-TST-9-9",
        extra=None,
        echoes=True,
        optional=False,
    ):
        self.tool = tool
        self.canonical = canonical
        self.alias = alias
        self.ident = ident
        self.alias_ident = alias_ident or ident
        self.other = other
        self.extra = extra or {}
        #: does a successful body contain the id it resolved?  ``pm_run_log``
        #: answers with a bare JSON array, so there is nothing to look for.
        self.echoes = echoes
        #: is omitting the id legal?  True where the ID is a *filter*, not the
        #: operand: ``pm_activity`` (no filter), ``pm_changeset_status`` (list all).
        self.optional = optional

    def args(self, **kwargs):
        return {**self.extra, **kwargs}

    def __repr__(self):
        return f"{self.tool}:{self.canonical}|{self.alias}"


#: Every ID-taking tool wired to the resolver (US-PM-3-5 seeded the first three).
#:
#: Two directions, one rule each.  A tool whose canonical is the *typed* name
#: accepts ``id``; a tool whose canonical is ``id`` accepts the typed name of
#: the thing it acts on.  Deliberately absent, and asserted absent below:
#: ``epic_id`` on ``pm_update`` and ``story_id`` on ``pm_create_task`` /
#: ``pm_fix_malformed``, which are parent links, not other spellings.
WIRED = [
    # canonical `id` → typed alias
    Wired("pm_get", "id", "task_id", "US-TST-1-1"),
    Wired("pm_update", "id", "task_id", "US-TST-1-1", extra={"status": "todo"}),
    Wired("pm_archive", "id", "task_id", "US-TST-1-3", alias_ident="US-TST-1-4"),
    Wired("pm_epic", "id", "epic_id", "EPIC-TST-1", other="EPIC-TST-9"),
    Wired("pm_estimate", "id", "task_id", "US-TST-1-1"),
    Wired("pm_scope", "id", "story_id", "US-TST-1", other="US-TST-9"),
    Wired("pm_run_log", "id", "task_id", "US-TST-1-1", echoes=False),
    # canonical typed name → `id`
    Wired("pm_grab", "task_id", "id", "US-TST-1-1", alias_ident="US-TST-1-2"),
    # Releasing is idempotent — an already-unassigned task releases fine — so
    # both spellings can be pointed at the same task.
    Wired("pm_release", "task_id", "id", "US-TST-1-1"),
    # Completing a task twice is idempotent, but the *second* spelling must
    # still find a task to complete — so it is pointed at a second task, as
    # for the other mutating tools.
    Wired("pm_done_next", "task_id", "id", "US-TST-1-1", alias_ident="US-TST-1-2"),
    # The four verdict verbs.  Each requires a non-blank `note` — the whole
    # point of the verb — so it travels in `extra`.  `pm_accept` completes its
    # target, so the alias spelling is pointed at a second task like the other
    # completing tools; retry/park/review accept any starting status, so a
    # second call on the same task still has work to do.
    Wired(
        "pm_accept",
        "task_id",
        "id",
        "US-TST-1-1",
        alias_ident="US-TST-1-2",
        extra={"note": "accepted by the alias sweep"},
    ),
    Wired("pm_retry", "task_id", "id", "US-TST-1-1", extra={"note": "retried by the alias sweep"}),
    Wired("pm_park", "task_id", "id", "US-TST-1-1", extra={"note": "parked by the alias sweep"}),
    Wired("pm_review", "task_id", "id", "US-TST-1-1", extra={"note": "reviewed by the alias sweep"}),
    Wired("pm_get_sprint", "sprint_id", "id", "SPRINT-TST-1", other="SPRINT-TST-9"),
    Wired("pm_update_sprint", "sprint_id", "id", "SPRINT-TST-1", other="SPRINT-TST-9"),
    Wired("pm_activity", "item_id", "id", "US-TST-1", other="US-TST-9", optional=True),
    Wired("pm_changeset_status", "changeset_id", "id", "CS-TST-1", other="CS-TST-9", optional=True),
    Wired(
        "pm_changeset_add_project",
        "changeset_id",
        "id",
        "CS-TST-1",
        alias_ident="CS-TST-2",
        other="CS-TST-9",
        extra={"name": "gamma"},
    ),
    Wired("pm_changeset_create_prs", "changeset_id", "id", "CS-TST-1", other="CS-TST-9"),
    Wired(
        "pm_changeset_push",
        "changeset_id",
        "id",
        "CS-TST-1",
        alias_ident="CS-TST-2",
        other="CS-TST-9",
    ),
]
WIRED_IDS = [repr(w) for w in WIRED]
REQUIRED = [w for w in WIRED if not w.optional]
REQUIRED_IDS = [repr(w) for w in REQUIRED]
OPTIONAL = [w for w in WIRED if w.optional]
OPTIONAL_IDS = [repr(w) for w in OPTIONAL]


def assert_clean(body):
    """A success may not smuggle a failure or an expected-negative into the body."""
    assert not body.lstrip().startswith("error:"), body
    try:
        data = yaml.safe_load(body) if body.strip() else None
    except yaml.YAMLError:
        data = None
    if isinstance(data, dict):
        assert data.get("outcome") != "expected_negative", body
        assert "error" not in data, body


@pytest.mark.parametrize("w", WIRED, ids=WIRED_IDS)
def test_each_wired_tool_accepts_both_spellings(w, seeded):
    """AC 1 and 2, tool by tool: both spellings work, neither errors."""
    canonical_error, canonical_body = call_over_the_wire(
        w.tool, w.args(**{w.canonical: w.ident})
    )
    alias_error, alias_body = call_over_the_wire(
        w.tool, w.args(**{w.alias: w.alias_ident})
    )

    assert canonical_error is False, canonical_body
    assert alias_error is False, alias_body
    if w.echoes:
        assert w.ident in canonical_body
        assert w.alias_ident in alias_body
    assert_clean(canonical_body)
    assert_clean(alias_body)


@pytest.mark.parametrize("w", WIRED, ids=WIRED_IDS)
def test_each_wired_tool_accepts_both_spellings_with_the_same_value(w, seeded):
    is_error, body = call_over_the_wire(
        w.tool, w.args(**{w.canonical: w.ident, w.alias: w.ident})
    )
    assert is_error is False, body
    if w.echoes:
        assert w.ident in body


@pytest.mark.parametrize("w", WIRED, ids=WIRED_IDS)
def test_each_wired_tool_rejects_conflicting_spellings_with_is_error(w, seeded):
    """AC 3, at the protocol: a conflict is a hard error, not an ``error:`` body."""
    is_error, body = call_over_the_wire(
        w.tool, w.args(**{w.canonical: w.ident, w.alias: w.other})
    )

    assert is_error is True, body
    assert not body.lstrip().startswith("error:"), body
    assert "conflicting ids" in body
    assert w.ident in body and w.other in body


@pytest.mark.parametrize("w", REQUIRED, ids=REQUIRED_IDS)
def test_each_wired_tool_still_fails_when_no_id_is_given(w, seeded):
    """Making the canonical optional must not turn a missing id into a success."""
    is_error, body = call_over_the_wire(w.tool, w.args())

    assert is_error is True, body
    assert not body.lstrip().startswith("error:"), body
    assert f"{w.canonical} is required" in body


@pytest.mark.parametrize("w", OPTIONAL, ids=OPTIONAL_IDS)
def test_a_filter_shaped_id_may_still_be_omitted_entirely(w, seeded):
    """``required=False``: omitting a *filter* keeps meaning "no filter"."""
    is_error, body = call_over_the_wire(w.tool, w.args())

    assert is_error is False, body
    assert_clean(body)


@pytest.mark.parametrize("w", WIRED, ids=WIRED_IDS)
def test_each_wired_tool_ignores_an_empty_alias(w, seeded):
    """The blank-spelling rule holds through the tool layer, not just the helper."""
    is_error, body = call_over_the_wire(
        w.tool, w.args(**{w.canonical: w.ident, w.alias: "   "})
    )
    assert is_error is False, body
    if w.echoes:
        assert w.ident in body


@pytest.mark.parametrize("w", WIRED, ids=WIRED_IDS)
def test_each_wired_tool_tolerates_an_explicit_null_alias(w, seeded):
    """A caller that fills in every declared parameter with ``null`` still works.

    This is why the alias is declared ``Optional[str] = None`` rather than
    ``str = ""``: an explicit ``null`` would otherwise be rejected by schema
    validation before the resolver ever ran.
    """
    is_error, body = call_over_the_wire(
        w.tool, w.args(**{w.canonical: w.ident, w.alias: None})
    )
    assert is_error is False, body
    if w.echoes:
        assert w.ident in body


# ===========================================================================
# The three confusions actually observed in the corpus.
# ===========================================================================


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("pm_grab", {"id": "US-TST-1-1"}),
        ("pm_get_sprint", {"id": "SPRINT-TST-1"}),
        ("pm_update", {"task_id": "US-TST-1-1", "status": "todo"}),
    ],
)
def test_the_observed_wrong_spellings_no_longer_fail(tool, arguments, seeded):
    """The literal call shapes that failed in the transcript corpus.

    ``pm_grab({'id': ...})`` is 15 hard errors, ``pm_update({'task_id': ...})``
    5, and ``pm_get_sprint({'id': ...})`` is the shape the other machines'
    studies recorded.  These are the error class the story exists to remove, so
    they are asserted as themselves rather than only through the sweep.
    """
    is_error, body = call_over_the_wire(tool, arguments)
    assert is_error is False, body
    assert_clean(body)


# ===========================================================================
# Aliasing must not eat a parameter that already means something else.
# ===========================================================================


def test_epic_id_on_pm_update_still_links_a_story_to_an_epic(seeded):
    """``pm_update``'s ``epic_id`` is a *link*, and must never be read as the id.

    The corpus contains a real ``pm_update(id=..., epic_id=...)`` call whose two
    values deliberately differ.  If ``epic_id`` had been added as an alias
    alongside ``task_id``, that call would now raise "conflicting ids" — trading
    one error class for another and silently breaking story→epic linking.
    """
    is_error, body = call_over_the_wire(
        "pm_update", {"id": "US-TST-1", "epic_id": "EPIC-TST-1"}
    )

    assert is_error is False, body
    assert "conflicting ids" not in body
    assert yaml.safe_load(body)["updated"]["epic_id"] == "EPIC-TST-1"


def test_story_id_on_pm_create_task_still_names_the_parent(seeded):
    """The same trap on the create path: ``story_id`` is the parent, not the id."""
    is_error, body = call_over_the_wire(
        "pm_create_task", {"story_id": "US-TST-1", "title": "Child", "description": "d"}
    )

    assert is_error is False, body
    assert yaml.safe_load(body)["created"]["story_id"] == "US-TST-1"


@pytest.mark.parametrize(
    "tool,parameter",
    [
        ("pm_update", "epic_id"),
        ("pm_create_story", "epic_id"),
        ("pm_create_task", "story_id"),
        ("pm_create_tasks", "story_id"),
        ("pm_fix_malformed", "story_id"),
    ],
)
def test_a_parent_link_parameter_is_never_documented_as_an_alias(tool, parameter):
    """A standing guard against the next rollout quietly aliasing a link.

    These five parameters name a *different* item from the one the tool acts
    on.  Aliasing any of them would retarget real calls, so the docstring the
    model reads must never claim they are interchangeable with the id.

    US-PM-3-7 gave the *canonical* entry an ``(alias: X)`` marker, which is a
    second way to make the same false claim — ``epic_id: Link a story to an
    epic (alias: id)`` would read as "pass either", so it is banned here too.
    """
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    description = tools[tool].description or ""

    assert f"{parameter}: Alias for" not in description, (tool, parameter)

    entry = args_entry(description, parameter)
    assert entry is not None, (tool, parameter, description)
    assert "(alias:" not in entry, (tool, parameter, entry)


# ===========================================================================
# The alias is discoverable — the reason it is a declared parameter.
# ===========================================================================


def test_every_wired_alias_is_visible_in_the_tool_schema():
    """The alias must be in the schema the model reads, not hidden in kwargs.

    An alias accepted only via ``**kwargs`` is invisible in ``tools/list``, so
    the model can only find it by luck — which is the status quo this story
    exists to end.  Both spellings are declared parameters, and *neither* is in
    ``required`` — either one alone has to be a complete call, which is the
    whole point.  Other required parameters are none of this test's business
    (``pm_changeset_add_project`` still requires ``name``).
    """
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}

    for w in WIRED:
        schema = tools[w.tool].inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        assert w.canonical in properties, w
        assert w.alias in properties, w
        assert w.canonical not in required, (w, required)
        assert w.alias not in required, (w, required)
        # ...and the docstring the model reads says the two are interchangeable.
        assert f"{w.alias}: Alias for {w.canonical}" in (tools[w.tool].description or "")


def test_the_rollout_covers_every_id_taking_tool_that_should_have_one():
    """The sweep above is only as good as its table — so the table is checked.

    Any tool that declares one of the ID spellings and is *not* in ``WIRED`` has
    to be a deliberate exclusion, listed here with its reason.  A newly added
    ID-taking tool lands in neither set and fails this test, which is the point.
    """
    import inspect

    import projectman.server as server
    from projectman.server import mcp as mcp_server

    #: tool -> why it takes an ``*_id`` and is still not aliased.
    EXCLUDED = {
        # The typed name is a parent link, not the operand (see _resolve_id).
        "pm_create_story": "epic_id links the new story to an epic",
        "pm_create_task": "story_id is the parent story",
        "pm_create_tasks": "story_id is the parent story",
        # Both reasons: story_id is the parent, and `id` sits between required
        # parameters, so aliasing would drop title/item_type out of `required`.
        "pm_fix_malformed": "story_id is the parent; id is mid-signature",
    }
    spellings = {"id", "task_id", "story_id", "epic_id", "sprint_id", "item_id", "changeset_id"}
    wired = {w.tool for w in WIRED}

    id_taking = set()
    for tool in anyio.run(mcp_server.list_tools):
        parameters = inspect.signature(getattr(server, tool.name)).parameters
        if spellings & set(parameters):
            id_taking.add(tool.name)

    assert id_taking == wired | set(EXCLUDED), id_taking.symmetric_difference(
        wired | set(EXCLUDED)
    )


def resolver_call_sites():
    """Which registered tools are aliased, read out of their own source code.

    ``_resolve_id`` is the only mechanism that makes a second spelling work, so
    "is aliased" is decidable without asking any table: parse each registered
    tool's real source and look for the call.  Returns
    ``{tool: (canonical, alias, required)}``.
    """
    import ast
    import inspect
    import textwrap

    import projectman.server as server
    from projectman.server import mcp as mcp_server

    found = {}
    for tool in anyio.run(mcp_server.list_tools):
        source = textwrap.dedent(inspect.getsource(inspect.unwrap(getattr(server, tool.name))))
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None)) == "_resolve_id"
        ]
        if not calls:
            continue
        # One operand per tool; two would make "the" canonical name ambiguous.
        assert len(calls) == 1, (tool.name, len(calls))
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        required = keywords.pop("required", None)
        aliases = sorted(keywords)
        assert len(aliases) == 1, (tool.name, aliases)
        found[tool.name] = (
            calls[0].args[0].value,
            aliases[0],
            True if required is None else required.value,
        )
    return found


def test_the_wired_table_is_exactly_the_set_of_tools_wired_to_the_resolver():
    """The swept set is tied to the live code, not to a hand-kept exclusion list.

    ``test_the_rollout_covers_every_id_taking_tool_that_should_have_one`` above
    guards ``WIRED`` against a plain deletion, but it compares against
    ``wired | EXCLUDED`` — so deleting a tool from ``WIRED`` *and* adding it to
    ``EXCLUDED`` with a plausible-sounding reason keeps that test green while
    six parametrised sweeps quietly stop running for it.  Measured: dropping
    ``pm_changeset_push`` that way took the file from 193 tests to 187 with
    nothing failing.

    This closes that door.  A tool that calls ``_resolve_id`` *is* aliased, as a
    fact about the shipped code, and every one of them must be in ``WIRED`` —
    where the both-spellings sweeps pick it up.  ``EXCLUDED`` cannot launder
    anything past this, because a genuinely un-aliased tool has no call site.

    The canonical/alias/required triple is checked too: a table entry naming the
    wrong spelling would sweep an argument the tool does not treat as an alias.
    """
    from_code = resolver_call_sites()
    from_table = {w.tool: (w.canonical, w.alias, not w.optional) for w in WIRED}

    assert set(from_code) == set(from_table), set(from_code).symmetric_difference(from_table)
    assert from_code == from_table, {
        tool: (from_code[tool], from_table[tool])
        for tool in from_code
        if from_code[tool] != from_table[tool]
    }
    # ...and discovery is not silently finding nothing.
    assert len(from_code) >= MINIMUM_TYPED_ID_TOOLS, sorted(from_code)


# ---------------------------------------------------------------------------
# US-PM-3-7 — the Args block documents both spellings, in ONE wording.
#
# The test above already required the alias to be *named* in the description.
# Two gaps were left, and these close them:
#
# 1. Naming the alias never said what happens when both are passed.  "Alias
#    for id" is compatible with last-one-wins, with the alias being ignored,
#    and with a hard error — and it is a hard error, which is the one a caller
#    has to know before it happens.
# 2. Nothing was said on the *canonical* line.  A caller reading ``pm_update``
#    stops at ``id:`` and never learns that the ``task_id`` it was about to
#    send is accepted — and ``pm_update({'task_id': ...})`` is one of the
#    literal corpus failures this story exists to remove.  The marker costs
#    ~15 bytes and sits where that caller is already looking.
#
# The wording is a constant, formatted from the canonical/alias pair, so
# "consistent across all 15" is enforced rather than merely intended: a
# bespoke 16th sentence fails.  Per US-PM-3-7 these SUPPORT the schema — the
# schema assertions above are untouched, and commit 2261a0d is the standing
# reminder that a docstring on its own changes nothing.
# ---------------------------------------------------------------------------

#: The alias parameter's own Args entry.
ALIAS_LINE = (
    "{alias}: Alias for {canonical} — either spelling works; "
    "passing both with different values is an error"
)

#: What the canonical parameter's Args entry gains, so the fact is discoverable
#: from the spelling the caller is already reading.
CANONICAL_MARKER = "(alias: {alias})"


def documented_aliases():
    """``{tool: (canonical, alias, description)}`` for every aliased tool.

    Keyed off :func:`resolver_call_sites`, which reads the shipped source for
    ``_resolve_id`` calls — never off ``WIRED``.  A tool aliased tomorrow is
    therefore required to carry the docstring on the day it is wired, which is
    the whole point of testing this rather than reviewing it.
    """
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    return {
        name: (canonical, alias, tools[name].description or "")
        for name, (canonical, alias, _required) in resolver_call_sites().items()
    }


DOCUMENTED_ALIASES = documented_aliases()
DOCUMENTED_ALIAS_NAMES = sorted(DOCUMENTED_ALIASES)


def args_entry(description, parameter):
    """The Args line for one parameter, or ``None``.

    Matched on the stripped line so it does not depend on how FastMCP happens
    to indent a docstring it lifted off a function.
    """
    for line in description.splitlines():
        if line.strip().startswith(f"{parameter}: "):
            return line.strip()
    return None


@pytest.mark.parametrize("tool_name", DOCUMENTED_ALIAS_NAMES)
def test_every_aliased_tool_documents_both_spellings_in_its_args_block(tool_name):
    """Both entries, in the one wording — this is the description the model reads."""
    canonical, alias, description = DOCUMENTED_ALIASES[tool_name]

    assert "Args:" in description, tool_name

    alias_entry = args_entry(description, alias)
    assert alias_entry is not None, (tool_name, alias, description)
    assert alias_entry.startswith(
        ALIAS_LINE.format(alias=alias, canonical=canonical)
    ), (tool_name, alias_entry)

    canonical_entry = args_entry(description, canonical)
    assert canonical_entry is not None, (tool_name, canonical, description)
    assert CANONICAL_MARKER.format(alias=alias) in canonical_entry, (
        tool_name,
        canonical_entry,
    )
    # The canonical entry still says what the argument *is*, not only that it
    # has another name — the marker is an addition, never a replacement.
    assert len(canonical_entry) > len(
        f"{canonical}: " + CANONICAL_MARKER.format(alias=alias)
    ), (tool_name, canonical_entry)


def test_the_alias_is_documented_with_one_wording_everywhere():
    """15 bespoke sentences would be worse than one predictable pattern.

    Asserted by counting: every aliased tool contributes exactly one copy of
    the pattern, and no description carries a near-miss variant of it.  A tool
    that re-words its alias line drops the count and fails here even though its
    own parametrised case above would still pass on a hand-written equivalent.
    """
    assert len(DOCUMENTED_ALIASES) >= MINIMUM_TYPED_ID_TOOLS, sorted(DOCUMENTED_ALIASES)

    matched = sum(
        description.count(ALIAS_LINE.format(alias=alias, canonical=canonical))
        for canonical, alias, description in DOCUMENTED_ALIASES.values()
    )
    assert matched == len(DOCUMENTED_ALIASES), matched

    # "Alias for X" may only ever appear as the head of that one pattern, so a
    # second, looser sentence about aliasing cannot creep in beside it.
    for tool_name, (canonical, alias, description) in DOCUMENTED_ALIASES.items():
        assert description.count("Alias for ") == 1, (tool_name, description)


def test_the_human_docs_agree_with_the_docstrings_about_every_alias():
    """docs/reference/mcp-tools.md is the other place a reader looks (US-PM-3-6).

    It documented exactly one of the aliases, so a human reading it would
    conclude fourteen tools do not have one.  Every aliased tool must carry the
    same ``(alias: X)`` marker there as in its docstring.

    ``UNDOCUMENTED_TOOLS`` is asserted *exactly*, not skipped: a tool with no
    section in the file at all is a documentation gap wider than this story, and
    pinning the set means the day someone writes its section without the marker,
    this fails rather than passing on an exemption.  It is empty now — the
    ``pm_get_sprint`` / ``pm_update_sprint`` sections that were missing have
    since been written, and carry the marker.
    """
    import pathlib

    #: Aliased tools the reference does not document at all.
    UNDOCUMENTED_TOOLS: set[str] = set()

    docs = pathlib.Path(__file__).resolve().parents[1] / "docs/reference/mcp-tools.md"
    text = docs.read_text()

    missing_section, missing_marker = set(), []
    for tool_name, (canonical, alias, _description) in sorted(DOCUMENTED_ALIASES.items()):
        heading = f"### {tool_name}("
        start = text.find(heading)
        if start < 0:
            missing_section.add(tool_name)
            continue
        end = text.find("\n### ", start + 1)
        section = text[start : end if end > 0 else len(text)]
        if f"(alias: `{alias}`)" not in section:
            missing_marker.append((tool_name, alias))

    assert not missing_marker, missing_marker
    assert missing_section == UNDOCUMENTED_TOOLS, missing_section.symmetric_difference(
        UNDOCUMENTED_TOOLS
    )
    # ...and the convention itself is stated once, rather than only implied by
    # fifteen markers a reader has to reverse-engineer.
    assert "## ID argument aliases" in text


# ===========================================================================
# US-PM-3-1 — "every tool taking a typed ID also accepts the generic ``id``".
#
# Everything above this line is driven by ``WIRED``, a table maintained by
# hand.  A table can be wrong in a way its own tests cannot see: a tool added
# to ``EXCLUDED`` with a plausible-sounding reason satisfies the rollout check
# above without ever accepting ``id``, and the sweep would never notice because
# the sweep only iterates the table.  The tests below never read ``WIRED``.
# They ask the live registry which tools take a typed identifier and then
# require ``id`` of each one, so a *new* typed-ID tool fails until it is
# aliased — which is what makes the acceptance criterion stick rather than
# merely describe the state of the code on the day it was written.
# ===========================================================================

#: The typed spellings of "the identifier of the item this tool acts on".
TYPED_ID_PARAMETERS = frozenset(
    {"task_id", "story_id", "epic_id", "sprint_id", "item_id", "changeset_id"}
)

#: ``(tool, parameter)`` pairs where a typed name is a *parent link* and so
#: names a different item from the operand.  Whether a parameter is a link is
#: a fact about meaning, not about syntax, so it cannot be derived — but it is
#: the one hand-written input here, it is tiny, and every pair in it is already
#: locked from the other side by
#: ``test_a_parent_link_parameter_is_never_documented_as_an_alias``.
PARENT_LINK_PARAMETERS = frozenset(
    {
        ("pm_update", "epic_id"),
        ("pm_create_story", "epic_id"),
        ("pm_create_task", "story_id"),
        ("pm_create_tasks", "story_id"),
        ("pm_fix_malformed", "story_id"),
    }
)

#: The rollout covered 15 tools.  Asserting the floor is what stops the whole
#: section passing vacuously if discovery silently stops finding anything.
MINIMUM_TYPED_ID_TOOLS = 15

#: A real item of each shape, as created by ``seeded``.
SAMPLE_FOR_TYPED_PARAMETER = {
    "task_id": "US-TST-1-1",
    "story_id": "US-TST-1",
    "epic_id": "EPIC-TST-1",
    "sprint_id": "SPRINT-TST-1",
    "item_id": "US-TST-1",
    "changeset_id": "CS-TST-1",
}

#: Well-formed but absent — used to prove the value was actually *used*.
ABSENT_FOR_TYPED_PARAMETER = {
    "task_id": "US-TST-9-9",
    "story_id": "US-TST-9",
    "epic_id": "EPIC-TST-9",
    "sprint_id": "SPRINT-TST-9",
    "item_id": "US-TST-9",
    "changeset_id": "CS-TST-9",
}

#: Values for a discovered tool's *other* required parameters.  A tool that
#: grows one this does not know about fails loudly rather than being skipped.
SAMPLE_FOR_OTHER_REQUIRED_PARAMETER = {
    "name": "gamma",
    # The verdict verbs require a non-blank run-log note (US-PM-8-7).
    "note": "exercised by the typed-id sweep",
}


def discover_typed_id_tools():
    """Ask the live registry which tools take a typed identifier as their operand.

    Returns ``{tool_name: (tool, typed_parameter)}``.  Derived from
    ``list_tools`` and the real signatures, never from ``WIRED``, so a tool
    added tomorrow is discovered the moment it is registered.
    """
    import inspect

    import projectman.server as server
    from projectman.server import mcp as mcp_server

    discovered = {}
    for tool in anyio.run(mcp_server.list_tools):
        parameters = inspect.signature(getattr(server, tool.name)).parameters
        typed = sorted(
            parameter
            for parameter in TYPED_ID_PARAMETERS & set(parameters)
            if (tool.name, parameter) not in PARENT_LINK_PARAMETERS
        )
        if not typed:
            continue
        # One operand per tool.  If a tool ever takes two typed spellings of
        # its own id, the sample/absent tables below become ambiguous and this
        # test has to be revisited rather than guess.
        assert len(typed) == 1, (tool.name, typed)
        discovered[tool.name] = (tool, typed[0])
    return discovered


#: Collected once, at import, so each tool is its own parametrised case and a
#: newly added one appears in the run without anyone editing this file.
TYPED_ID_TOOLS = discover_typed_id_tools()
TYPED_ID_TOOL_NAMES = sorted(TYPED_ID_TOOLS)


def other_required_arguments(tool_name):
    """Whatever else the tool insists on, so ``id`` can be exercised alone."""
    import inspect

    import projectman.server as server

    arguments = {}
    for name, parameter in inspect.signature(getattr(server, tool_name)).parameters.items():
        # `= ...` is how a parameter that must follow a defaulted one is still
        # declared *required* in the tool schema (the verdict verbs' `note`).
        # It is a Python default but not an optional argument, so the sweep
        # has to supply it like any other required parameter.
        if parameter.default is not inspect.Parameter.empty and parameter.default is not ...:
            continue
        if name == "id" or name in TYPED_ID_PARAMETERS:
            continue
        if name not in SAMPLE_FOR_OTHER_REQUIRED_PARAMETER:
            pytest.fail(
                f"{tool_name} requires {name!r}, which this test has no sample for — "
                f"add one to SAMPLE_FOR_OTHER_REQUIRED_PARAMETER"
            )
        arguments[name] = SAMPLE_FOR_OTHER_REQUIRED_PARAMETER[name]
    return arguments


def test_every_tool_taking_a_typed_id_also_accepts_the_generic_id():
    """AC 1, as a property of the registry rather than of a table.

    For every registered tool whose operand can be named by a typed spelling:
    ``id`` is a declared parameter, it is visible in the schema the model
    reads, and *neither* spelling is in ``required`` — because "also accepts
    ``id``" means ``id`` on its own is a complete call, not that ``id`` may be
    passed alongside the typed name.
    """
    discovered = discover_typed_id_tools()
    assert discovered, "discovery found no typed-ID tools at all — the scan is broken"
    assert len(discovered) >= MINIMUM_TYPED_ID_TOOLS, sorted(discovered)

    import inspect

    import projectman.server as server

    checked = []
    for tool_name, (tool, typed) in sorted(discovered.items()):
        parameters = inspect.signature(getattr(server, tool_name)).parameters
        assert "id" in parameters, (tool_name, typed)

        schema = tool.inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        assert "id" in properties, (tool_name, sorted(properties))
        assert "id" not in required, (tool_name, required)
        assert typed in properties, (tool_name, sorted(properties))
        assert typed not in required, (tool_name, required)
        checked.append(tool_name)

    # It checked what it found, and it found something.
    assert checked == sorted(discovered)
    assert len(checked) == len(discovered) >= MINIMUM_TYPED_ID_TOOLS


@pytest.mark.parametrize("tool_name", TYPED_ID_TOOL_NAMES)
def test_every_discovered_typed_id_tool_takes_id_alone_over_the_wire(tool_name, seeded):
    """The schema says ``id`` is enough; this proves a real ``tools/call`` agrees.

    Same registry-derived list as above, one case per tool, so a new typed-ID
    tool is exercised here too without anyone adding it to a table.
    """
    typed = TYPED_ID_TOOLS[tool_name][1]
    arguments = {
        **other_required_arguments(tool_name),
        "id": SAMPLE_FOR_TYPED_PARAMETER[typed],
    }

    is_error, body = call_over_the_wire(tool_name, arguments)

    assert is_error is False, (tool_name, body)
    assert_clean(body)


@pytest.mark.parametrize("tool_name", TYPED_ID_TOOL_NAMES)
def test_the_generic_id_actually_reaches_the_operand(tool_name, seeded):
    """A tool could declare ``id``, ignore it, and pass every test above.

    ``pm_activity`` and ``pm_changeset_status`` are the ones this really
    catches: their id is a *filter*, so "no error, and the id appears in the
    body" is satisfied by an unfiltered listing that happens to contain the
    item.  Passing an id that exists nowhere separates the two — the value
    either reaches a lookup that fails on it, or reaches a filter that then
    matches nothing.  A tool that discards ``id`` does neither.
    """
    typed = TYPED_ID_TOOLS[tool_name][1]
    absent = ABSENT_FOR_TYPED_PARAMETER[typed]
    extras = other_required_arguments(tool_name)

    is_error, body = call_over_the_wire(tool_name, {**extras, "id": absent})

    if is_error:
        # It looked the value up and could not find it — so it used it.
        assert absent in body, (tool_name, body)
        return

    # Not an error.  Either the id is the operand and simply has an empty
    # answer (``pm_run_log`` of an item with no entries), or it is a filter
    # that matched nothing.  The two are told apart by what happens with no id
    # at all.
    unfiltered_error, unfiltered_body = call_over_the_wire(tool_name, extras)

    if unfiltered_error:
        # Omitting the id is a hard failure, so the call above could only have
        # got as far as an empty answer by consuming the ``id`` it was given.
        assert "is required" in unfiltered_body, (tool_name, unfiltered_body)
        return

    # A filter, then — so it must have filtered.  It may not return the same
    # thing as the unfiltered call, nor mention the items it excluded.
    assert body != unfiltered_body, f"{tool_name} ignored id={absent!r}"
    assert SAMPLE_FOR_TYPED_PARAMETER[typed] not in body, (tool_name, body)


# ---------------------------------------------------------------------------
# ...and the tools whose canonical name is the typed one did the right thing.
#
# The sweep asserts "no error, and the id came back in the body", which is a
# weak read of "it worked" for a tool that mutates: the body is written by the
# same call that is under test.  These check the *effect*, from the outside,
# after a call made with nothing but ``id``.
# ---------------------------------------------------------------------------


def test_pm_grab_called_with_id_claims_that_exact_task(seeded):
    from projectman.server import pm_get

    is_error, body = call_over_the_wire("pm_grab", {"id": "US-TST-1-2"})
    assert is_error is False, body

    claimed = yaml.safe_load(pm_get("US-TST-1-2"))
    assert claimed["id"] == "US-TST-1-2"
    assert claimed["status"] == "in-progress"
    assert claimed["assignee"] == "claude"
    # ...and it claimed only that one.
    assert yaml.safe_load(pm_get("US-TST-1-1"))["status"] == "todo"


def test_pm_update_sprint_called_with_id_updates_that_exact_sprint(seeded):
    from projectman.server import pm_get_sprint

    is_error, body = call_over_the_wire(
        "pm_update_sprint", {"id": "SPRINT-TST-1", "goal": "Reached via id"}
    )
    assert is_error is False, body

    assert yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))["goal"] == "Reached via id"
    assert yaml.safe_load(pm_get_sprint("SPRINT-TST-2"))["goal"] == "Ship it again"


def test_pm_get_sprint_called_with_id_returns_that_exact_sprint(seeded):
    is_error, body = call_over_the_wire("pm_get_sprint", {"id": "SPRINT-TST-2"})

    assert is_error is False, body
    fetched = yaml.safe_load(body)
    assert fetched["id"] == "SPRINT-TST-2"
    assert fetched["goal"] == "Ship it again"


def test_pm_changeset_add_project_called_with_id_updates_that_exact_changeset(seeded):
    from projectman.server import pm_changeset_status

    is_error, body = call_over_the_wire(
        "pm_changeset_add_project", {"id": "CS-TST-1", "name": "gamma"}
    )
    assert is_error is False, body

    projects = {e["project"] for e in yaml.safe_load(pm_changeset_status("CS-TST-1"))["entries"]}
    assert "gamma" in projects
    untouched = {e["project"] for e in yaml.safe_load(pm_changeset_status("CS-TST-2"))["entries"]}
    assert "gamma" not in untouched


def test_pm_changeset_status_called_with_id_returns_only_that_changeset(seeded):
    """The filter-shaped case, positively: one changeset, not the listing."""
    is_error, body = call_over_the_wire("pm_changeset_status", {"id": "CS-TST-2"})

    assert is_error is False, body
    fetched = yaml.safe_load(body)
    assert fetched["id"] == "CS-TST-2"
    assert "changesets" not in fetched  # i.e. not the list-all response


def test_pm_activity_called_with_id_filters_to_that_item(seeded):
    """The other filter-shaped case — and the one the sweep cannot see."""
    is_error, body = call_over_the_wire("pm_activity", {"id": "US-TST-1-1"})

    assert is_error is False, body
    filtered = yaml.safe_load(body)
    assert filtered["entries"], body
    # Entries are rendered lines; every one of them has to be about this item.
    assert all("US-TST-1-1" in entry for entry in filtered["entries"]), body

    _, unfiltered = call_over_the_wire("pm_activity", {})
    assert yaml.safe_load(unfiltered)["total"] > filtered["total"]


def test_pm_changeset_push_called_with_id_reports_on_that_exact_changeset(seeded):
    """Both changesets are otherwise identical, so only the id can tell them apart."""
    from projectman.server import pm_changeset_add_project

    pm_changeset_add_project("delta", "CS-TST-1")

    is_error, body = call_over_the_wire("pm_changeset_push", {"id": "CS-TST-1"})

    assert is_error is False, body
    report = yaml.safe_load(body)
    assert report["changeset"] == "CS-TST-1"
    assert "delta" in {entry["project"] for entry in report["pending"]}

    # The sibling changeset, reached the same way, does not know about delta.
    is_error, sibling = call_over_the_wire("pm_changeset_push", {"id": "CS-TST-2"})
    assert is_error is False, sibling
    assert "delta" not in {
        entry["project"] for entry in yaml.safe_load(sibling)["pending"]
    }


def test_pm_changeset_create_prs_called_with_id_describes_that_exact_changeset(seeded):
    from projectman.server import pm_changeset_add_project

    pm_changeset_add_project("delta", "CS-TST-2")

    is_error, body = call_over_the_wire("pm_changeset_create_prs", {"id": "CS-TST-2"})

    assert is_error is False, body
    assert "CS-TST-2" in body
    assert "delta" in body


# ===========================================================================
# US-PM-3-2 — "tools taking ``id`` also accept the typed alias where one
# exists", proved by EFFECT rather than by absence of an error.
#
# The sweep above asserts, for the seven ``id``-canonical tools, that an
# alias-spelled call does not error and that the id it was given comes back in
# the body.  That is close to vacuous for a *mutating* tool: the body is
# written by the same call under test, so a ``pm_update`` that resolved the
# alias to the wrong item — or to nothing, and updated some default — could
# still echo the id it was handed.  The tests below never trust the response of
# the call under test as evidence.  They read the effect back from a source the
# call cannot fake: the ``.md`` and ``.jsonl`` files on disk, parsed here
# without the Store, without its cache, and without any ProjectMan tool.
#
# Every project below holds *two* of everything, alpha and beta, alike in every
# way except an opaque ``MARKER-<id>`` token in the body.  So "it operated on
# some item" and "it operated on the item the alias named" are different
# observations, which is the only way these tests can bite.  Each case is run
# in both directions — alpha named, beta named — so a resolver hard-wired to
# either twin fails half of them.
# ===========================================================================


ALPHA_TASK, BETA_TASK = "US-TST-1-1", "US-TST-2-1"
ALPHA_STORY, BETA_STORY = "US-TST-1", "US-TST-2"
ALPHA_EPIC, BETA_EPIC = "EPIC-TST-1", "EPIC-TST-2"

#: alpha -> its beta twin, for the "and left the other alone" half of each test.
TWIN = {
    ALPHA_TASK: BETA_TASK,
    BETA_TASK: ALPHA_TASK,
    ALPHA_STORY: BETA_STORY,
    BETA_STORY: ALPHA_STORY,
    ALPHA_EPIC: BETA_EPIC,
    BETA_EPIC: ALPHA_EPIC,
}


def marker(item_id):
    """The token that distinguishes one twin from the other, and nothing else."""
    return f"MARKER-{item_id}"


def item_file(root, item_id):
    """The path an item lives at — derived from the id, not asked of the Store."""
    if item_id.startswith("EPIC-"):
        folder = "epics"
    else:
        parts = item_id.split("-")
        is_task = len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()
        folder = "tasks" if is_task else "stories"
    return root / ".project" / folder / f"{item_id}.md"


def on_disk(root, item_id):
    """Frontmatter and body straight off the filesystem.

    Deliberately hand-rolled: no ``Store``, no ``_store_cache``, no ProjectMan
    tool.  If the effect is not on disk, it did not happen, and a tool cannot
    make this function agree with it by writing a convincing response body.
    """
    text = item_file(root, item_id).read_text()
    assert text.startswith("---"), (item_id, text[:40])
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body


def run_log_on_disk(root, item_id):
    """The item's run-log entries, read from its own ``.jsonl``."""
    import json

    path = root / ".project" / "logs" / f"{item_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def marker_from_disk(root, item_id, source="item"):
    """Re-derive the twin's distinguishing token from the filesystem.

    The token is never taken from a constant in the assertion — it is read back
    out of the file (or log) the fixture wrote, so the test is comparing the
    tool's answer against the project's actual state.
    """
    if source == "log":
        entries = run_log_on_disk(root, item_id)
        assert entries, f"{item_id} has no run log on disk to distinguish it by"
        found = [e["note"] for e in entries if marker(item_id) in e["note"]]
    else:
        _, body = on_disk(root, item_id)
        found = [line for line in body.splitlines() if marker(item_id) in line]
    assert found, (item_id, source)
    return marker(item_id)


@pytest.fixture
def twins(tmp_project):
    """Two of everything: alpha and beta, distinguishable only by their marker.

    Two epics, one story each, one task each, and a run-log entry on each task.
    Nothing here uses an alias — the fixture builds the project through the
    canonical spellings so that the alias is the only thing under test.
    """
    from projectman.server import pm_create_epic, pm_create_story, pm_create_task, pm_update

    def task_body(item_id):
        return (
            f"## Implementation\n\n{marker(item_id)} — do the thing properly.\n\n"
            "## Testing\n\nRun pytest.\n\n## Definition of Done\n\n- [ ] It is done\n"
        )

    for epic, story, task in (
        (ALPHA_EPIC, ALPHA_STORY, ALPHA_TASK),
        (BETA_EPIC, BETA_STORY, BETA_TASK),
    ):
        pm_create_epic(f"Epic for {epic}", f"{marker(epic)} epic body")
        pm_create_story(f"Story for {story}", f"{marker(story)} story body", epic_id=epic)
        pm_update(story, status="active")
        pm_create_task(story, f"Task for {task}", task_body(task), points=3)
        pm_update(task, outcome="info", note=f"{marker(task)} was here")

    # The ids the fixture believes it made are the ids the tests name.
    for item_id in (ALPHA_EPIC, BETA_EPIC, ALPHA_STORY, BETA_STORY, ALPHA_TASK, BETA_TASK):
        assert item_file(tmp_project, item_id).exists(), item_id
    return tmp_project


# ---------------------------------------------------------------------------
# The two mutating tools — verified by re-reading the file, not the response.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", [ALPHA_TASK, BETA_TASK])
def test_pm_update_via_task_id_mutates_exactly_the_task_the_alias_named(target, twins):
    """``pm_update(task_id=X, status=...)`` — proved from the file, not the body.

    The observed corpus failure was ``pm_update({'task_id': ...})``.  Accepting
    it is only half the fix; it has to update *that* task.
    """
    twin = TWIN[target]
    assert on_disk(twins, target)[0]["status"] == "todo"
    assert on_disk(twins, twin)[0]["status"] == "todo"

    is_error, body = call_over_the_wire(
        "pm_update", {"task_id": target, "status": "done", "points": 8}
    )
    assert is_error is False, body

    updated, _ = on_disk(twins, target)
    assert updated["id"] == target
    assert updated["status"] == "done"
    assert updated["points"] == 8

    # ...and the twin, identical but for its marker, was not touched.
    untouched, _ = on_disk(twins, twin)
    assert untouched["status"] == "todo", untouched
    assert untouched["points"] == 3, untouched


@pytest.mark.parametrize("target", [ALPHA_TASK, BETA_TASK])
def test_pm_archive_via_task_id_archives_exactly_the_task_the_alias_named(target, twins):
    """Archiving a *task* sets ``archived: true`` on disk, per ``Store.archive``.

    It used to write ``status: done`` — abandoned work booked as delivered
    (US-PM-16).  Status is now left exactly where the task stopped.
    """
    twin = TWIN[target]

    is_error, body = call_over_the_wire("pm_archive", {"task_id": target})
    assert is_error is False, body

    archived_front = on_disk(twins, target)[0]
    assert archived_front["archived"] is True
    assert archived_front["status"] == "todo"

    twin_front = on_disk(twins, twin)[0]
    assert twin_front.get("archived", False) is False
    assert twin_front["status"] == "todo"


@pytest.mark.parametrize("target", [ALPHA_STORY, BETA_STORY])
def test_pm_archive_via_task_id_archives_exactly_the_story_the_alias_named(target, twins):
    """The same tool on a story, where "archived" is literally the status written.

    ``task_id`` is a spelling of "the id of the thing to archive", not a claim
    about the item's type — so it has to archive a story too, and the story
    path is the one where the effect is unambiguous on disk.
    """
    twin = TWIN[target]

    is_error, body = call_over_the_wire("pm_archive", {"task_id": target})
    assert is_error is False, body

    assert on_disk(twins, target)[0]["status"] == "archived"
    assert on_disk(twins, twin)[0]["status"] == "active"


def test_pm_update_via_task_id_appends_the_run_log_entry_to_that_task(twins):
    """The alias also has to carry through to the *side* effect, not just status.

    ``pm_update``'s note lands in a separate ``.jsonl`` keyed by item id, so a
    misresolved alias would file the note against the wrong task while the
    status write still looked right.
    """
    before = len(run_log_on_disk(twins, BETA_TASK))

    is_error, body = call_over_the_wire(
        "pm_update",
        {"task_id": BETA_TASK, "outcome": "success", "note": "filed against beta"},
    )
    assert is_error is False, body

    notes = [e["note"] for e in run_log_on_disk(twins, BETA_TASK)]
    assert len(notes) == before + 1
    assert "filed against beta" in notes
    assert "filed against beta" not in [e["note"] for e in run_log_on_disk(twins, ALPHA_TASK)]


# ---------------------------------------------------------------------------
# The five read-shaped tools — the "effect" is the answer, so the answer is
# checked against disk truth and against the twin it must not be about.
# ---------------------------------------------------------------------------

#: ``(tool, alias, alpha, beta, where the distinguishing marker lives)``.
READ_VIA_ALIAS = [
    ("pm_get", "task_id", ALPHA_TASK, BETA_TASK, "item"),
    ("pm_estimate", "task_id", ALPHA_TASK, BETA_TASK, "item"),
    ("pm_run_log", "task_id", ALPHA_TASK, BETA_TASK, "log"),
    ("pm_epic", "epic_id", ALPHA_EPIC, BETA_EPIC, "item"),
    ("pm_scope", "story_id", ALPHA_STORY, BETA_STORY, "item"),
]
READ_VIA_ALIAS_CASES = [
    pytest.param(tool, alias, target, TWIN[target], source, id=f"{tool}:{target}")
    for tool, alias, alpha, beta, source in READ_VIA_ALIAS
    for target in (alpha, beta)
]


@pytest.mark.parametrize("tool,alias,target,twin,source", READ_VIA_ALIAS_CASES)
def test_a_read_tool_called_with_only_the_typed_alias_answers_about_that_item(
    tool, alias, target, twin, source, twins
):
    """Both twins exist, so "returned something" and "returned *this*" differ.

    The marker is re-read from the file the fixture wrote — the tool's answer
    is compared against the project's state on disk, not against a literal
    repeated in the assertion.  Running each tool for both twins is what makes
    this a discrimination: a resolver that ignored the alias and always reached
    the first item would pass the alpha case and fail the beta one.
    """
    expected = marker_from_disk(twins, target, source)
    forbidden = marker_from_disk(twins, twin, source)

    is_error, body = call_over_the_wire(tool, {alias: target})

    assert is_error is False, body
    assert_clean(body)
    assert expected in body, (tool, target, body)
    assert forbidden not in body, (tool, twin, body)
    # ...and the twin is not named anywhere in the answer either.
    assert twin not in body, (tool, twin, body)


@pytest.mark.parametrize("target", [ALPHA_TASK, BETA_TASK])
def test_pm_get_via_task_id_returns_the_frontmatter_that_is_on_disk(target, twins):
    """Not merely "about the right task" — the same values the file holds."""
    front, disk_body = on_disk(twins, target)

    is_error, body = call_over_the_wire("pm_get", {"task_id": target})
    assert is_error is False, body

    fetched = yaml.safe_load(body)
    assert fetched["id"] == front["id"] == target
    assert fetched["title"] == front["title"]
    assert fetched["status"] == front["status"]
    assert fetched["points"] == front["points"]
    assert fetched["body"].strip() == disk_body.strip()


@pytest.mark.parametrize("target", [ALPHA_TASK, BETA_TASK])
def test_pm_estimate_via_task_id_estimates_the_item_the_alias_named(target, twins):
    front, _ = on_disk(twins, target)

    is_error, body = call_over_the_wire("pm_estimate", {"task_id": target})
    assert is_error is False, body

    context = yaml.safe_load(body)
    assert context["item"]["id"] == target
    assert context["item"]["title"] == front["title"]
    assert context["current_points"] == front["points"]


@pytest.mark.parametrize("target", [ALPHA_TASK, BETA_TASK])
def test_pm_run_log_via_task_id_returns_that_task_s_own_log_file(target, twins):
    """The response has to be the ``.jsonl`` keyed by the id the alias named."""
    import json

    expected = run_log_on_disk(twins, target)
    assert expected, target

    is_error, body = call_over_the_wire("pm_run_log", {"task_id": target})
    assert is_error is False, body

    returned = json.loads(body)
    assert [e["note"] for e in returned] == [e["note"] for e in expected]
    assert [e["note"] for e in returned] != [
        e["note"] for e in run_log_on_disk(twins, TWIN[target])
    ]


@pytest.mark.parametrize("target", [ALPHA_EPIC, BETA_EPIC])
def test_pm_epic_via_epic_id_rolls_up_only_that_epic_s_stories(target, twins):
    """Each epic has exactly one story; rolling up the wrong one is visible."""
    expected_story = ALPHA_STORY if target == ALPHA_EPIC else BETA_STORY

    is_error, body = call_over_the_wire("pm_epic", {"epic_id": target})
    assert is_error is False, body

    rollup = yaml.safe_load(body)
    assert rollup["epic"]["id"] == target
    assert [s["id"] for s in rollup["stories"]] == [expected_story]
    assert rollup["rollup"]["story_count"] == 1


@pytest.mark.parametrize("target", [ALPHA_STORY, BETA_STORY])
def test_pm_scope_via_story_id_scopes_only_that_story_s_tasks(target, twins):
    expected_task = ALPHA_TASK if target == ALPHA_STORY else BETA_TASK

    is_error, body = call_over_the_wire("pm_scope", {"story_id": target})
    assert is_error is False, body

    context = yaml.safe_load(body)
    assert context["story"]["id"] == target
    assert [t["id"] for t in context["existing_tasks"]] == [expected_task]
    assert context["task_count"] == 1


def test_the_effect_tests_cover_every_id_canonical_tool_that_gained_an_alias():
    """The gap this section closes was "no test asserts the *effect* of an alias".

    So the set of tools whose effect is asserted here is checked against the
    set of ``id``-canonical tools in ``WIRED``, rather than left to drift: a
    tool aliased tomorrow lands in ``WIRED`` and fails here until its effect is
    proved too.
    """
    id_canonical = {w.tool for w in WIRED if w.canonical == "id"}
    proved_by_effect = {tool for tool, *_ in READ_VIA_ALIAS} | {"pm_update", "pm_archive"}

    assert id_canonical == proved_by_effect, id_canonical.symmetric_difference(
        proved_by_effect
    )


# ===========================================================================
# US-PM-3-3 — "passing both a typed ID and ``id`` with conflicting values is a
# clear error".
#
# The *error* half is already well covered: the sweep above proves every wired
# tool sets ``is_error``, keeps the failure out of the body, says "conflicting
# ids", and echoes both values and both spellings.  Two gaps are left, and this
# section closes them.
#
# 1. NO SIDE EFFECT — nothing anywhere asserted that a rejected call left the
#    project alone.  "It raised" and "it raised *before doing anything*" are
#    different claims, and only the second one is safe: a caller that sees an
#    error reasonably assumes nothing happened, so a conflict caught after the
#    write is a far worse bug than a confusing message.  ``_resolve_id`` is
#    called on the first line of every tool body, which is exactly the kind of
#    fact that holds until someone moves it.  So the rejection is checked from
#    the outside — the whole ``.project`` tree, byte for byte, before and after
#    — for every wired tool, in both orderings.
# 2. CLARITY beyond "it mentions the two values".  The message also names which
#    spelling is canonical and what the caller should do instead, and it is a
#    single stable line; none of that was asserted, so all of it could be
#    dropped without a test noticing.
#
# Both halves are driven off ``WIRED``, so the day a sixteenth tool is aliased
# it has to prove it is inert on conflict too.
# ===========================================================================


#: The two shapes ``twins`` does not build.  Two of each, for the same reason:
#: a conflicting call has to be shown to leave *both* named items alone, which
#: is only observable when both of them exist and hold different state.
ALPHA_SPRINT, BETA_SPRINT = "SPRINT-TST-1", "SPRINT-TST-2"
ALPHA_CHANGESET, BETA_CHANGESET = "CS-TST-1", "CS-TST-2"


def any_item_file(root, item_id):
    """``item_file`` extended to sprints and changesets.

    Same rule as ``item_file``: the path is derived from the id, never asked of
    the Store, so a tool cannot make this agree with it.
    """
    if item_id.startswith("SPRINT-"):
        return root / ".project" / "sprints" / f"{item_id}.md"
    if item_id.startswith("CS-"):
        return root / ".project" / "changesets" / f"{item_id}.md"
    return item_file(root, item_id)


def full_state(root, item_id):
    """``(frontmatter, body)`` for any of the five item shapes.

    Tasks, stories and epics go through US-PM-3-2's ``on_disk`` unchanged —
    the same hand-rolled reader, no Store, no cache, no ProjectMan tool.
    Sprints and changesets are parsed identically, they just live elsewhere.
    """
    if item_id.startswith(("SPRINT-", "CS-")):
        text = any_item_file(root, item_id).read_text()
        assert text.startswith("---"), (item_id, text[:40])
        _, front, body = text.split("---", 2)
        return yaml.safe_load(front), body
    return on_disk(root, item_id)


def item_trace(root, item_id):
    """Everything one item carries: its file, *and* its run log.

    ``full_state`` alone is not the whole of an item's state.  A verdict verb
    whose target is already in the status it sets (``pm_retry`` on a task that
    is already ``todo`` and unheld) leaves the frontmatter byte-identical while
    still filing a run-log entry — which is the write that verb exists to make.
    Observing both means "the item it was pointed at is the one that moved"
    stays a real assertion for every mutator, and a strictly stronger one for
    the tools that move both.
    """
    log = root / ".project" / "logs" / f"{item_id}.jsonl"
    return full_state(root, item_id), log.read_bytes() if log.exists() else None


def project_snapshot(root):
    """Every byte of every file under ``.project/``, keyed by relative path.

    The broadest observation available: item files, sprint and changeset files,
    the run-log ``.jsonl``s, ``activity.jsonl``, ``index.yaml``, the rendered
    ``INDEX*.md``, and ``config.yaml`` (whose id counters a create would bump).
    A rejected call has to leave all of it identical — including files it might
    have *created*, which a per-item comparison could not see.
    """
    project = root / ".project"
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def activity_log_on_disk(root):
    """The project-wide activity log, read from its own ``.jsonl``."""
    import json

    path = root / ".project" / "activity.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def conflict_twins(twins):
    """``twins``, plus a twinned sprint pair and changeset pair.

    ``pm_update_sprint`` and the three changeset tools act on items ``twins``
    does not build.  One entry of each changeset is marked merged *on disk*
    because ``pm_changeset_push`` only writes when it has something to move to
    ``partial`` — without that, the control test below could not show that the
    call mutates when it is *not* rejected, and every "nothing changed"
    assertion for that tool would be vacuous.
    """
    from projectman.server import pm_changeset_create, pm_create_sprint

    pm_create_sprint("Sprint Alpha", goal=f"{marker(ALPHA_SPRINT)} goal")
    pm_create_sprint("Sprint Beta", goal=f"{marker(BETA_SPRINT)} goal")
    pm_changeset_create("cs-alpha", "alpha,beta")
    pm_changeset_create("cs-beta", "alpha,beta")

    for changeset in (ALPHA_CHANGESET, BETA_CHANGESET):
        path = any_item_file(twins, changeset)
        text = path.read_text()
        assert "status: pending" in text, (changeset, text)
        path.write_text(text.replace("status: pending", "status: merged", 1))

    for item_id in (ALPHA_SPRINT, BETA_SPRINT, ALPHA_CHANGESET, BETA_CHANGESET):
        assert any_item_file(twins, item_id).exists(), item_id
    return twins


#: A real, existing pair of items for every wired tool.  ``WIRED``'s own
#: ``other`` is a well-formed id that exists nowhere, which is right for "the
#: resolver raises before any lookup" but useless here: an item that does not
#: exist cannot be shown to be undamaged.  Both ids below are real, so a call
#: that resolved the conflict either way would visibly act on one of them.
CONFLICT_PAIR = {
    "pm_get": (ALPHA_TASK, BETA_TASK),
    "pm_update": (ALPHA_TASK, BETA_TASK),
    "pm_archive": (ALPHA_TASK, BETA_TASK),
    "pm_epic": (ALPHA_EPIC, BETA_EPIC),
    "pm_estimate": (ALPHA_TASK, BETA_TASK),
    "pm_scope": (ALPHA_STORY, BETA_STORY),
    "pm_run_log": (ALPHA_TASK, BETA_TASK),
    "pm_grab": (ALPHA_TASK, BETA_TASK),
    "pm_release": (ALPHA_TASK, BETA_TASK),
    "pm_done_next": (ALPHA_TASK, BETA_TASK),
    "pm_accept": (ALPHA_TASK, BETA_TASK),
    "pm_retry": (ALPHA_TASK, BETA_TASK),
    "pm_park": (ALPHA_TASK, BETA_TASK),
    "pm_review": (ALPHA_TASK, BETA_TASK),
    "pm_get_sprint": (ALPHA_SPRINT, BETA_SPRINT),
    "pm_update_sprint": (ALPHA_SPRINT, BETA_SPRINT),
    "pm_activity": (ALPHA_TASK, BETA_TASK),
    "pm_changeset_status": (ALPHA_CHANGESET, BETA_CHANGESET),
    "pm_changeset_add_project": (ALPHA_CHANGESET, BETA_CHANGESET),
    "pm_changeset_create_prs": (ALPHA_CHANGESET, BETA_CHANGESET),
    "pm_changeset_push": (ALPHA_CHANGESET, BETA_CHANGESET),
}

#: The rest of the call, chosen to be as *damaging* as the tool allows.  A
#: conflicting ``pm_update`` that carried no fields would leave nothing behind
#: even if the resolver ran last, so every mutator is handed real work to do:
#: a status change, a points change, a run-log note, a new changeset entry.
CONFLICT_EXTRA = {
    "pm_update": {
        "status": "done",
        "points": 8,
        "outcome": "success",
        "note": "MUST NEVER BE FILED",
    },
    "pm_update_sprint": {"status": "active", "goal": "MUST NEVER BE WRITTEN"},
    "pm_changeset_add_project": {"name": "gamma"},
    # Completes the task *and* files a run-log entry, so a resolver that ran
    # late would leave two separate traces behind.
    "pm_done_next": {"outcome": "success", "note": "MUST NEVER BE FILED"},
    # Every verdict verb writes a status change *and* a run-log entry on every
    # call, so each has two distinct traces to fail to leave.  The note is
    # required, so it is not optional here either.
    "pm_accept": {"note": "MUST NEVER BE FILED"},
    "pm_retry": {"note": "MUST NEVER BE FILED"},
    "pm_park": {"note": "MUST NEVER BE FILED"},
    "pm_review": {"note": "MUST NEVER BE FILED"},
    # A bare release of an unassigned task is a same-day no-op on disk, which
    # would make its "nothing changed" case vacuous.  A status move plus a
    # run-log entry gives it two distinct traces to fail to leave.
    "pm_release": {
        "status": "blocked",
        "outcome": "blocked",
        "note": "MUST NEVER BE FILED",
    },
}

#: The wired tools that write.  Kept honest from two sides: the guard below
#: ties it to each tool's own ``readOnlyHint`` declaration, and the control
#: test proves every member really does change the project when it is allowed
#: to run.  Tools outside it are still swept — a "read" tool that mutated on a
#: rejected call would fail the snapshot test just the same.
MUTATING = [
    "pm_update",
    "pm_archive",
    "pm_grab",
    "pm_release",
    "pm_done_next",
    "pm_accept",
    "pm_retry",
    "pm_park",
    "pm_review",
    "pm_update_sprint",
    "pm_changeset_add_project",
    "pm_changeset_push",
]

#: ``(wired tool, canonical value, alias value)`` — every wired tool, with the
#: conflicting pair given in BOTH orderings.  Order-independence is a property
#: of the criterion, not a detail: a resolver that compared ``canonical or
#: alias`` against the alias, or that only checked one direction, would pass
#: half of these and fail the other half.
def conflict_cases(tools):
    cases = []
    for name in tools:
        alpha, beta = CONFLICT_PAIR[name]
        w = next(w for w in WIRED if w.tool == name)
        cases.append(pytest.param(w, alpha, beta, id=f"{name}:canonical-first"))
        cases.append(pytest.param(w, beta, alpha, id=f"{name}:alias-first"))
    return cases


ALL_CONFLICT_CASES = conflict_cases([w.tool for w in WIRED])
MUTATING_CONFLICT_CASES = conflict_cases(MUTATING)


def conflicting_call(w, canonical_value, alias_value):
    """One rejected call: the tool's own two spellings, naming two real items."""
    return call_over_the_wire(
        w.tool,
        {
            **CONFLICT_EXTRA.get(w.tool, {}),
            w.canonical: canonical_value,
            w.alias: alias_value,
        },
    )


def test_the_conflict_pairs_cover_every_wired_tool():
    """The sweeps below are only as good as their table, so the table is tied.

    ``CONFLICT_PAIR`` is the one hand-written input to this section — a real
    pair of items per tool cannot be derived — so a tool aliased tomorrow lands
    in ``WIRED``, is missing here, and fails immediately rather than quietly
    dropping out of the no-side-effect sweep.
    """
    assert set(CONFLICT_PAIR) == {w.tool for w in WIRED}, set(
        CONFLICT_PAIR
    ).symmetric_difference({w.tool for w in WIRED})
    # Both halves of every pair are genuinely two different items.
    for tool_name, (alpha, beta) in CONFLICT_PAIR.items():
        assert alpha != beta, tool_name
    # ...and every extra names a tool that is actually wired.
    assert set(CONFLICT_EXTRA) <= set(CONFLICT_PAIR), set(CONFLICT_EXTRA)


def test_the_mutating_set_is_exactly_what_the_tools_declare_themselves_to_be():
    """``MUTATING`` is checked against each tool's own ``readOnlyHint``.

    The control test below only runs for tools in ``MUTATING``, so a writer
    left out of it would never be shown to mutate — and its "nothing changed
    on conflict" case would then be passing for the wrong reason.  The
    annotation is the tool's own declaration to clients, so it is the right
    thing to tie to: a tool that starts writing has to flip the hint, and the
    day it does, this fails until it is added here.
    """
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    declared_writers = {
        w.tool
        for w in WIRED
        if not getattr(tools[w.tool].annotations, "readOnlyHint", False)
    }

    assert set(MUTATING) == declared_writers, set(MUTATING).symmetric_difference(
        declared_writers
    )


# ---------------------------------------------------------------------------
# NO SIDE EFFECT — the half of the criterion nothing asserted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("w,canonical_value,alias_value", ALL_CONFLICT_CASES)
def test_a_conflicting_call_leaves_both_named_items_exactly_as_they_were(
    w, canonical_value, alias_value, conflict_twins
):
    """The core of US-PM-3-3: rejected means *nothing happened*, to either item.

    Full frontmatter and full body are compared, not one field — a resolver
    that ran late could touch ``updated``, ``assignee`` or the body while
    leaving ``status`` alone and a single-field assertion would miss it.  Read
    back off the filesystem before and after, by ``on_disk``, so the evidence
    never comes from the call under test.
    """
    before = {
        item: full_state(conflict_twins, item)
        for item in (canonical_value, alias_value)
    }
    before_logs = {
        item: run_log_on_disk(conflict_twins, item)
        for item in (canonical_value, alias_value)
    }

    is_error, body = conflicting_call(w, canonical_value, alias_value)

    assert is_error is True, body
    assert "conflicting ids" in body, body

    for item in (canonical_value, alias_value):
        front, item_body = full_state(conflict_twins, item)
        assert front == before[item][0], (w.tool, item, front, before[item][0])
        assert item_body == before[item][1], (w.tool, item)
        # ...and requirement 2: no run-log entry was filed against either one.
        assert run_log_on_disk(conflict_twins, item) == before_logs[item], (w.tool, item)


@pytest.mark.parametrize("w,canonical_value,alias_value", ALL_CONFLICT_CASES)
def test_a_conflicting_call_leaves_the_whole_project_byte_identical(
    w, canonical_value, alias_value, conflict_twins
):
    """Wider than the two named items: nothing under ``.project/`` may move.

    A rejected call must not touch the index, the rendered ``INDEX*.md``, the
    id counters in ``config.yaml``, any *other* item, or create a file that was
    not there before — which is the failure mode a per-item comparison cannot
    see at all.  ``pm_changeset_add_project`` is the sharp case: its effect is
    an appended entry in a file the test would otherwise never look at.
    """
    before = project_snapshot(conflict_twins)

    is_error, body = conflicting_call(w, canonical_value, alias_value)

    assert is_error is True, body
    after = project_snapshot(conflict_twins)

    assert set(after) == set(before), (
        w.tool,
        set(after).symmetric_difference(before),
    )
    changed = sorted(path for path in before if before[path] != after[path])
    assert not changed, (w.tool, canonical_value, alias_value, changed)


@pytest.mark.parametrize("w,canonical_value,alias_value", MUTATING_CONFLICT_CASES)
def test_a_conflicting_call_writes_no_activity_log_entry(
    w, canonical_value, alias_value, conflict_twins
):
    """The project-wide log is the other observable a late rejection would dirty.

    ``Store._emit_log`` swallows its own failures, so an activity entry written
    by a call that then raised would leave a permanent record of an event that
    never happened, with nothing anywhere to flag it.
    """
    before = activity_log_on_disk(conflict_twins)

    is_error, body = conflicting_call(w, canonical_value, alias_value)

    assert is_error is True, body
    assert activity_log_on_disk(conflict_twins) == before, w.tool


@pytest.mark.parametrize("w,canonical_value,alias_value", MUTATING_CONFLICT_CASES)
def test_the_same_call_without_the_conflict_really_does_change_the_project(
    w, canonical_value, alias_value, conflict_twins
):
    """The control — without it, every assertion above could be vacuous.

    Identical arguments, minus the second spelling.  If this call leaves the
    project untouched too, then "nothing changed" proves nothing about the
    conflict and the case above is asserting a tautology.  Run in both
    orderings so each tool is shown to have real work to do on *each* of its
    two items, which is what makes "it left both alone" meaningful.
    """
    before = project_snapshot(conflict_twins)
    before_state = item_trace(conflict_twins, canonical_value)

    is_error, body = call_over_the_wire(
        w.tool, {**CONFLICT_EXTRA.get(w.tool, {}), w.canonical: canonical_value}
    )

    assert is_error is False, (w.tool, body)
    after = project_snapshot(conflict_twins)
    assert after != before, f"{w.tool} changed nothing — the conflict tests are vacuous"
    # ...and specifically, the item it was pointed at is the one that moved —
    # in its file, in its run log, or both.
    assert item_trace(conflict_twins, canonical_value) != before_state, (
        w.tool,
        canonical_value,
    )


def test_a_conflicting_pm_update_files_nothing_against_either_task(conflict_twins):
    """The named-in-the-brief case, spelled out rather than only swept.

    ``pm_update(id=A, task_id=B, status='done')`` is the call that must leave A
    unmodified — and it carries a run-log note as well as a status, so it has
    two distinct ways to leave a trace.  The note text appears nowhere in the
    project afterwards, which is a stronger statement than "the two logs are
    the same length".
    """
    is_error, body = call_over_the_wire(
        "pm_update",
        {
            "id": ALPHA_TASK,
            "task_id": BETA_TASK,
            "status": "done",
            "outcome": "success",
            "note": "MUST NEVER BE FILED",
        },
    )

    assert is_error is True, body
    for item in (ALPHA_TASK, BETA_TASK):
        assert full_state(conflict_twins, item)[0]["status"] == "todo"
        assert full_state(conflict_twins, item)[0]["points"] == 3
        assert "MUST NEVER BE FILED" not in str(run_log_on_disk(conflict_twins, item))
    assert not [
        path
        for path, content in project_snapshot(conflict_twins).items()
        if b"MUST NEVER BE FILED" in content
    ]


def test_a_conflicting_call_is_rejected_before_the_id_is_even_looked_up(conflict_twins):
    """Why "no side effect" holds at all: the conflict is decided first.

    A conflict between two ids that do not exist is still a conflict — it is
    not reported as "not found", and it does not depend on the Store having
    been consulted.  That is the ordering the no-side-effect property rests on,
    so it is asserted directly rather than inferred from the sweeps.
    """
    is_error, body = call_over_the_wire(
        "pm_update", {"id": "US-TST-8-8", "task_id": "US-TST-9-9", "status": "done"}
    )

    assert is_error is True, body
    assert "conflicting ids" in body, body
    assert "not found" not in body.lower(), body


# ---------------------------------------------------------------------------
# CLEAR — the other half of the criterion.
#
# Already covered elsewhere: ``is_error`` rather than an ``error:`` body, the
# words "conflicting ids", both values echoed, both spelling names present.
# What follows is only what those do not say.
# ---------------------------------------------------------------------------


def test_the_conflict_message_names_which_spelling_is_canonical():
    """"Both are wrong" is not actionable; "send this one" is.

    The caller has to fix the call, and to do that it needs to know which of
    the two names to keep.  Naming both spellings — which is all that was
    asserted before — leaves that to a coin flip.
    """
    message = str(
        pytest.raises(
            ToolError, _resolve_id, "task_id", "US-TST-1-1", id="US-TST-2-1"
        ).value
    )

    assert "canonical: task_id" in message, message
    # ...and the canonical name is the tool's own, not always the literal "id".
    other = str(
        pytest.raises(ToolError, _resolve_id, "id", "US-TST-1-1", task_id="US-TST-2-1").value
    )
    assert "canonical: id" in other, other
    assert "canonical: task_id" not in other, other


def test_the_conflict_message_says_what_to_do_instead():
    """Both recoveries are named: drop one spelling, or make them agree.

    The second one matters because "pass the same value for both" is not
    obviously allowed — a caller told only that two spellings conflict could
    reasonably conclude the tool rejects the duplicate shape outright, which is
    the belt-and-braces call the resolver deliberately accepts.
    """
    message = str(
        pytest.raises(
            ToolError, _resolve_id, "task_id", "US-TST-1-1", id="US-TST-2-1"
        ).value
    )

    assert "Pass one of them" in message, message
    assert "same value for both" in message, message


def test_the_conflict_message_is_one_stable_parseable_line():
    """A caller — human or model — reads this in a log line, so it has a shape.

    Exact, because "clear" is not a property that survives being asserted
    loosely: the two values are quoted so an empty or whitespace-carrying one
    is visible, the canonical spelling comes first so the pair reads in a fixed
    order, and there are no newlines to be truncated at.
    """
    message = str(
        pytest.raises(
            ToolError, _resolve_id, "task_id", "US-TST-1-1", id="US-TST-2-1"
        ).value
    )

    assert message.startswith("conflicting ids: task_id='US-TST-1-1' and id='US-TST-2-1'"), message
    assert "\n" not in message, message


def test_the_conflict_message_is_the_same_shape_in_either_order():
    """Requirement 4 at the resolver: which spelling holds which value is irrelevant.

    The canonical name leads the pair either way, so the message a caller
    learns to read does not change depending on how it made the mistake.
    """
    forwards = str(
        pytest.raises(ToolError, _resolve_id, "task_id", "A-1", id="B-1").value
    )
    backwards = str(
        pytest.raises(ToolError, _resolve_id, "task_id", "B-1", id="A-1").value
    )

    assert forwards.replace("A-1", "X").replace("B-1", "Y") == backwards.replace(
        "B-1", "X"
    ).replace("A-1", "Y")
    assert "canonical: task_id" in forwards and "canonical: task_id" in backwards


@pytest.mark.parametrize("canonical_first", [True, False])
def test_an_optional_id_conflict_is_reported_as_clearly_as_a_required_one(
    canonical_first,
):
    """``required=False`` changes only the *missing* rule, never the conflict one.

    The optional shape is the one where a silent fallback would be most
    tempting — "no filter" is a defensible answer to an unanswerable filter —
    so the same message, with the same canonical marker, is required of it.
    """
    values = ("US-TST-1", "US-TST-2") if canonical_first else ("US-TST-2", "US-TST-1")
    message = str(
        pytest.raises(
            ToolError, _resolve_id, "item_id", values[0], required=False, id=values[1]
        ).value
    )

    assert message.startswith(f"conflicting ids: item_id='{values[0]}' and id='{values[1]}'")
    assert "canonical: item_id" in message, message
    assert "Pass one of them" in message, message


@pytest.mark.parametrize("w,canonical_value,alias_value", ALL_CONFLICT_CASES)
def test_every_wired_tool_reports_a_conflict_with_the_full_clear_message(
    w, canonical_value, alias_value, conflict_twins
):
    """The clarity assertions hold at the protocol, for every tool, both ways round.

    The existing sweep checks "conflicting ids" and the two values.  This adds
    the parts a caller acts on — its own canonical spelling, both names, and
    the recovery — and runs the reversed ordering the existing sweep never
    exercises.
    """
    is_error, body = conflicting_call(w, canonical_value, alias_value)

    assert is_error is True, body
    assert not body.lstrip().startswith("error:"), body
    # The one stable line, intact inside whatever the transport wraps it in.
    assert (
        f"conflicting ids: {w.canonical}={canonical_value!r} and "
        f"{w.alias}={alias_value!r} — " in body
    ), body
    assert f"canonical: {w.canonical}" in body, body
    assert "Pass one of them" in body, body
