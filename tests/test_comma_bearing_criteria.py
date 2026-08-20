"""Comma-bearing acceptance criteria survive both MCP story tools (US-PM-18).

Acceptance criteria are natural language: "Given a user, when they log in,
then the dashboard loads" is ONE criterion whose commas are punctuation.  The
tools used to ``.split(",")`` whatever they were handed, shredding that into
three fragments — and, because every criterion auto-generates a test task,
into three garbage tasks as well.

``tests/test_server.py`` pins the parameter contract itself (list in, bare
string as exactly one criterion, blanks dropped, docstrings and schema).  This
module is the story's regression home: it drives the tools **at the wire**
(``mcp.call_tool``, the path a real client takes) and then follows a
comma-bearing criterion all the way through test-task reconciliation — add,
remove, reorder, reword — which is where a re-introduced split would do its
real damage.
"""

import json

import anyio
import pytest
import yaml

from projectman.store import (
    Store,
    clear_all_caches,
    generate_test_task_body,
    generate_test_task_title,
)

# One criterion each.  Every comma below is punctuation.
GHERKIN = "Given a user, when they log in, then the dashboard loads"
GHERKIN_REWORDED = (
    "Given a user, when they log in, then the dashboard loads within two seconds"
)
RED_ERROR = "An invalid password shows an error, in red, above the form"
LOCKOUT = "After five failures, the account locks, and an email goes out"

# Fragments the old split() produced.  None of these may ever appear as a
# criterion or as a test task of its own.
FRAGMENTS = [
    "Given a user",
    "when they log in",
    "then the dashboard loads",
    "in red",
    "above the form",
]


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Server tools resolve the project from the cwd."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    _store_cache.clear()
    clear_all_caches()


def _wire(tool_name, **arguments):
    """Call a tool the way a client does — through ``mcp.call_tool``.

    This is the layer that matters for this story: it is where FastMCP
    coerces the argument before the tool body ever sees it.
    """
    from projectman.server import mcp as mcp_server

    return anyio.run(mcp_server.call_tool, tool_name, arguments)


def _criteria(tmp_project, story_id="US-TST-1"):
    """Criteria as they landed on disk, read through a fresh Store."""
    clear_all_caches()
    meta, _ = Store(tmp_project).get_story(story_id)
    return list(meta.acceptance_criteria)


def _live_test_task_criteria(tmp_project, story_id="US-TST-1"):
    """Criterion text each live auto-generated test task quotes."""
    clear_all_caches()
    store = Store(tmp_project)
    return [criterion for _meta, criterion in store._test_tasks_for_story(story_id)]


def _assert_no_fragments(tmp_project, story_id="US-TST-1"):
    """Nothing anywhere is a piece of a criterion torn off at a comma."""
    stored = _criteria(tmp_project, story_id)
    quoted = _live_test_task_criteria(tmp_project, story_id)
    for fragment in FRAGMENTS:
        assert fragment not in stored, (fragment, stored)
        assert fragment not in quoted, (fragment, quoted)


# ─── at the wire: pm_create_story ───────────────────────────────────────


def test_wire_create_story_bare_comma_string_is_one_criterion(tmp_project):
    """The string form survives ``call_tool`` intact — one criterion, one task."""
    _wire(
        "pm_create_story",
        title="Login",
        description="Desc",
        acceptance_criteria=GHERKIN,
    )
    assert _criteria(tmp_project) == [GHERKIN]
    assert _live_test_task_criteria(tmp_project) == [GHERKIN]
    _assert_no_fragments(tmp_project)


def test_wire_create_story_json_list_of_comma_bearing_criteria(tmp_project):
    """The JSON-list form keeps each criterion whole, commas and all."""
    _wire(
        "pm_create_story",
        title="Login",
        description="Desc",
        acceptance_criteria=json.dumps([GHERKIN, RED_ERROR]),
    )
    assert _criteria(tmp_project) == [GHERKIN, RED_ERROR]
    assert _live_test_task_criteria(tmp_project) == [GHERKIN, RED_ERROR]
    _assert_no_fragments(tmp_project)


def test_wire_create_story_spawns_one_task_per_criterion_not_per_fragment(tmp_project):
    """Two comma-heavy criteria mean two tasks — the old split() made seven."""
    _wire(
        "pm_create_story",
        title="Login",
        description="Desc",
        acceptance_criteria=[GHERKIN, RED_ERROR],
    )
    clear_all_caches()
    store = Store(tmp_project)
    tasks = store.list_tasks(story_id="US-TST-1")
    assert len(tasks) == 2, [t.title for t in tasks]
    for meta, criterion in zip(tasks, [GHERKIN, RED_ERROR]):
        _, body = store.get_task(meta.id)
        assert meta.title == generate_test_task_title(criterion)
        assert body == generate_test_task_body("US-TST-1", criterion)


# ─── at the wire: pm_update ─────────────────────────────────────────────


def test_wire_update_bare_comma_string_is_one_criterion(tmp_project):
    from projectman.server import pm_create_story

    pm_create_story("Login", "Desc")
    _wire("pm_update", id="US-TST-1", acceptance_criteria=GHERKIN)
    assert _criteria(tmp_project) == [GHERKIN]
    assert _live_test_task_criteria(tmp_project) == [GHERKIN]
    _assert_no_fragments(tmp_project)


def test_wire_update_json_list_of_comma_bearing_criteria(tmp_project):
    from projectman.server import pm_create_story

    pm_create_story("Login", "Desc")
    _wire(
        "pm_update",
        id="US-TST-1",
        acceptance_criteria=json.dumps([GHERKIN, RED_ERROR]),
    )
    assert _criteria(tmp_project) == [GHERKIN, RED_ERROR]
    assert _live_test_task_criteria(tmp_project) == [GHERKIN, RED_ERROR]
    _assert_no_fragments(tmp_project)


def test_wire_update_replacing_criteria_reconciles_at_the_wire(tmp_project):
    """A whole edit round trip through ``call_tool``: one in, one out, one left."""
    _wire(
        "pm_create_story",
        title="Login",
        description="Desc",
        acceptance_criteria=[GHERKIN],
    )
    _wire("pm_update", id="US-TST-1", acceptance_criteria=[RED_ERROR])
    assert _criteria(tmp_project) == [RED_ERROR]
    assert _live_test_task_criteria(tmp_project) == [RED_ERROR]
    _assert_no_fragments(tmp_project)


# ─── reconciliation with comma-bearing criteria ─────────────────────────
#
# The reconciliation suite (tests/test_criteria_task_reconciliation.py) proves
# add/remove/reorder/reword on short ASCII criteria.  These repeat the same
# moves with commas inside the text, through pm_update, so a re-introduced
# split shows up as reconciliation nonsense rather than a silent mess.


def _create(*criteria):
    from projectman.server import pm_create_story

    return yaml.safe_load(
        pm_create_story("Login", "Desc", acceptance_criteria=list(criteria))
    )


def _update(**kwargs):
    from projectman.server import pm_update

    return yaml.safe_load(pm_update("US-TST-1", **kwargs))


def test_adding_a_comma_bearing_criterion_creates_exactly_one_task(tmp_project):
    _create(GHERKIN)
    out = _update(acceptance_criteria=[GHERKIN, LOCKOUT])
    assert out["test_tasks"]["created"] == ["US-TST-1-2"]
    assert out["test_tasks"].get("orphaned", []) == []
    assert _live_test_task_criteria(tmp_project) == [GHERKIN, LOCKOUT]
    _assert_no_fragments(tmp_project)


def test_removing_a_comma_bearing_criterion_orphans_only_its_task(tmp_project):
    _create(GHERKIN, RED_ERROR)
    out = _update(acceptance_criteria=[GHERKIN])
    orphaned = out["test_tasks"]["orphaned"]
    assert [o["id"] for o in orphaned] == ["US-TST-1-2"]
    # The orphan is reported by its whole criterion, not by a fragment.
    assert orphaned[0]["criterion"] == RED_ERROR
    # Untouched, so the removal policy archives it rather than flagging it —
    # and only it: the surviving criterion's task is left alone.
    assert out["test_tasks"]["archived"] == ["US-TST-1-2"]
    assert out["test_tasks"]["flagged"] == []
    assert out["test_tasks"].get("created", []) == []
    clear_all_caches()
    store = Store(tmp_project)
    assert store.get_task("US-TST-1-2")[0].archived is True
    assert store.get_task("US-TST-1-1")[0].archived is not True
    assert _live_test_task_criteria(tmp_project) == [GHERKIN]
    _assert_no_fragments(tmp_project)


def test_reordering_comma_bearing_criteria_moves_no_tasks(tmp_project):
    _create(GHERKIN, RED_ERROR, LOCKOUT)
    out = _update(acceptance_criteria=[LOCKOUT, GHERKIN, RED_ERROR])
    assert "test_tasks" not in out, out
    assert _criteria(tmp_project) == [LOCKOUT, GHERKIN, RED_ERROR]
    # Reordering is not a rewrite: the tasks stay put, still one per criterion.
    assert sorted(_live_test_task_criteria(tmp_project)) == sorted(
        [GHERKIN, RED_ERROR, LOCKOUT]
    )


def test_rewording_after_the_last_comma_resyncs_the_same_task(tmp_project):
    """An edit inside a comma-bearing criterion is an edit, not a new criterion."""
    _create(GHERKIN)
    out = _update(acceptance_criteria=[GHERKIN_REWORDED])
    # Resynced in place: the SAME task is rewritten, not archived and recreated.
    assert out["test_tasks"]["resynced"] == ["US-TST-1-1"]
    assert out["test_tasks"].get("created", []) == []
    assert out["test_tasks"].get("orphaned", []) == []
    assert out["test_tasks"].get("archived", []) == []
    clear_all_caches()
    store = Store(tmp_project)
    tasks = store.list_tasks(story_id="US-TST-1")
    assert len(tasks) == 1, [t.title for t in tasks]
    assert tasks[0].id == "US-TST-1-1"
    _, body = store.get_task(tasks[0].id)
    assert tasks[0].title == generate_test_task_title(GHERKIN_REWORDED)
    assert body == generate_test_task_body("US-TST-1", GHERKIN_REWORDED)
    _assert_no_fragments(tmp_project)


def test_bare_comma_string_update_collapses_to_a_single_test_task(tmp_project):
    """The string form on pm_update reconciles as one criterion, not several."""
    _create(GHERKIN, RED_ERROR)
    _update(acceptance_criteria=LOCKOUT)
    assert _criteria(tmp_project) == [LOCKOUT]
    assert _live_test_task_criteria(tmp_project) == [LOCKOUT]
    _assert_no_fragments(tmp_project)


def test_empty_list_clears_comma_bearing_criteria_and_their_tasks(tmp_project):
    """Clearing is an edit too: every criterion goes, so every task orphans.

    ``[]`` is "no criteria", not "not supplied" — and the tasks the
    comma-bearing criteria spawned must be reconciled away with them, not
    left behind quoting criteria the story no longer has.
    """
    _create(GHERKIN, RED_ERROR)
    out = _update(acceptance_criteria=[])
    assert _criteria(tmp_project) == []
    orphaned = out["test_tasks"]["orphaned"]
    assert [o["id"] for o in orphaned] == ["US-TST-1-1", "US-TST-1-2"]
    # Reported by whole criteria, never by a piece torn off at a comma.
    assert [o["criterion"] for o in orphaned] == [GHERKIN, RED_ERROR]
    assert out["test_tasks"]["archived"] == ["US-TST-1-1", "US-TST-1-2"]
    assert out["test_tasks"].get("created", []) == []
    assert _live_test_task_criteria(tmp_project) == []
    _assert_no_fragments(tmp_project)


def test_empty_string_clears_criteria_rather_than_storing_a_blank_one(tmp_project):
    """The string form's empty case is "no criteria", not one blank criterion.

    A blank criterion would breed an unparseable test-task body (US-PM-5-8),
    so the bare-string path must drop it — the same rule the list path uses.
    """
    _create(GHERKIN)
    _update(acceptance_criteria="")
    assert _criteria(tmp_project) == []
    assert _live_test_task_criteria(tmp_project) == []


def test_unchanged_comma_bearing_criteria_are_a_no_op(tmp_project):
    """Re-sending the same criteria must not churn tasks on every write."""
    _create(GHERKIN, RED_ERROR)
    out = _update(acceptance_criteria=[GHERKIN, RED_ERROR])
    assert "test_tasks" not in out, out
    assert _live_test_task_criteria(tmp_project) == [GHERKIN, RED_ERROR]


# ─── the guidance the model actually reads ──────────────────────────────
#
# Behaviour is only half the fix.  The tool *description* served over the
# wire is what a model reads before it decides how to shape the argument, so
# if it still says "comma-separated" the bug comes back as caller behaviour
# even with the split() gone.  tests/test_server.py pins the raw docstrings;
# this pins the rendered descriptions FastMCP publishes.


def _tool_descriptions():
    """acceptance_criteria guidance as published by the registered tools."""
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    out = {}
    for name in ("pm_create_story", "pm_update"):
        description = tools[name].description or ""
        out[name] = next(
            line.strip()
            for line in description.splitlines()
            if line.strip().startswith("acceptance_criteria:")
        )
    return out


@pytest.mark.parametrize("tool_name", ["pm_create_story", "pm_update"])
def test_published_description_never_instructs_comma_separation(tool_name):
    line = _tool_descriptions()[tool_name]
    lowered = line.lower()
    assert "comma-separated" not in lowered, line
    assert "comma separated" not in lowered, line
    assert "comma-delimited" not in lowered, line


@pytest.mark.parametrize("tool_name", ["pm_create_story", "pm_update"])
def test_published_description_asks_for_a_list(tool_name):
    line = _tool_descriptions()[tool_name]
    assert "list" in line.lower(), line
