"""Brief mode on `pm_batch_get` and `pm_list_sprints` (US-PM-10-7).

These are the two list-*everything* calls: `pm_batch_get(type="stories")` was
measured at 37,593 chars and `pm_list_sprints(status="completed")` at 27,079,
both dumping every body, every acceptance criterion and every sprint goal to a
caller that usually just wanted to see the shape of the backlog.

Two ways out, sharing one implementation with `pm_get`/`pm_grab` (US-PM-10-6):

* **`brief=True`** — a fixed, documented projection.  ``BRIEF_ITEM_FIELDS`` and
  ``BRIEF_SPRINT_FIELDS`` are module constants precisely so this file can
  import them instead of restating them, and keys a type does not have are
  simply absent rather than an error;
* **`fields=...`** — the same per-key projection as `pm_get`, same parsing,
  same always-keep-`id` rule, same loud failure on an unknown name.

`fields` wins over `brief`: explicit beats preset.

The properties pinned here: the default is **byte-identical** to before the
parameters existed; brief actually drops the free-text and keeps the rest; and
it actually *pays* — the size test measures the ratio on a realistic corpus
rather than asserting the saving by construction.
"""

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.server import BRIEF_ITEM_FIELDS, BRIEF_SPRINT_FIELDS

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


@pytest.fixture
def seeded(tmp_project):
    """One epic, one story with criteria and tasks, plus two sprints."""
    from projectman.store import Store

    store = Store(tmp_project)
    store.create_epic("An Epic", "Epic body text that is long enough to matter.")
    store.create_story(
        "Story",
        "Story body text long enough to matter.",
        points=3,
        tags=["alpha"],
        acceptance_criteria=["It works", "It is fast"],
    )
    store.update("US-TST-1", status="active", epic_id="EPIC-TST-1")
    for i in range(1, 4):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    store.create_sprint(
        "Sprint One",
        goal="Ship the first slice of the thing, end to end, with tests.",
        planned_stories=["US-TST-1"],
    )
    store.update_sprint("SPRINT-TST-1", status="completed")
    store.create_sprint("Sprint Two", goal="Then ship the second slice.")
    return store


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


# ═══ Default behaviour is unchanged ═════════════════════════════


@pytest.mark.parametrize("item_type", ["epics", "stories", "tasks"])
def test_batch_get_default_is_byte_identical(seeded, item_type):
    from projectman.server import pm_batch_get

    plain = pm_batch_get(type=item_type)
    assert plain == pm_batch_get(type=item_type, brief=False, fields=None)


def test_batch_get_ids_default_is_byte_identical(seeded):
    from projectman.server import pm_batch_get

    ids = "US-TST-1,US-TST-1-1,EPIC-TST-1"
    assert pm_batch_get(ids=ids) == pm_batch_get(ids=ids, brief=False, fields=None)


def test_list_sprints_default_is_byte_identical(seeded):
    from projectman.server import pm_list_sprints

    assert pm_list_sprints() == pm_list_sprints(brief=False, fields=None)
    assert pm_list_sprints(status="completed") == pm_list_sprints(
        status="completed", brief=False, fields=None
    )


@pytest.mark.parametrize("empty", ["", "   ", ",", " , , "])
def test_an_empty_fields_string_means_no_projection(seeded, empty):
    from projectman.server import pm_batch_get, pm_list_sprints

    assert pm_batch_get(type="stories", fields=empty) == pm_batch_get(type="stories")
    assert pm_list_sprints(fields=empty) == pm_list_sprints()


def test_the_default_still_carries_the_free_text(seeded):
    """The saving must come from `brief`, not from a quietly slimmed default."""
    from projectman.server import pm_batch_get, pm_list_sprints

    stories = yaml.safe_load(pm_batch_get(type="stories"))
    assert stories[0]["body"]
    assert stories[0]["acceptance_criteria"]
    sprints = yaml.safe_load(pm_list_sprints())["sprints"]
    assert sprints[0]["goal"]


# ═══ brief=True on pm_batch_get ═════════════════════════════════


@pytest.mark.parametrize("item_type", ["epics", "stories", "tasks"])
def test_brief_drops_the_free_text_on_every_item_type(seeded, item_type):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(type=item_type, brief=True))
    assert items
    for item in items:
        assert "body" not in item
        assert "acceptance_criteria" not in item
        assert "recent_run_log" not in item


@pytest.mark.parametrize("item_type", ["epics", "stories", "tasks"])
def test_brief_keeps_exactly_the_brief_keys_the_type_has(seeded, item_type):
    from projectman.server import pm_batch_get

    full = yaml.safe_load(pm_batch_get(type=item_type))
    brief = yaml.safe_load(pm_batch_get(type=item_type, brief=True))
    assert len(brief) == len(full)
    for full_item, brief_item in zip(full, brief):
        expected = [k for k in full_item if k in set(BRIEF_ITEM_FIELDS)]
        assert list(brief_item) == expected
        # Intersection, not demand: an epic has no story_id and that is fine.
        assert "id" in brief_item
        assert "title" in brief_item
        assert "status" in brief_item
        for key in expected:
            assert brief_item[key] == full_item[key]


def test_brief_keeps_the_wiring_keys_that_exist(seeded):
    from projectman.server import pm_batch_get

    story = yaml.safe_load(pm_batch_get(type="stories", brief=True))[0]
    assert story["epic_id"] == "EPIC-TST-1"
    assert story["points"] == 3
    assert story["tags"] == ["alpha"]
    task = yaml.safe_load(pm_batch_get(type="tasks", brief=True))[0]
    assert task["story_id"] == "US-TST-1"
    assert "assignee" in task
    assert "depends_on" in task


def test_the_ids_path_honours_brief(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(ids="US-TST-1,US-TST-1-1", brief=True))
    assert [i["id"] for i in items] == ["US-TST-1", "US-TST-1-1"]
    for item in items:
        assert "body" not in item
        assert set(item) <= set(BRIEF_ITEM_FIELDS)


def test_the_ids_path_still_reports_a_missing_id_under_brief(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(ids="US-TST-1,US-TST-9", brief=True))
    assert items[1]["id"] == "US-TST-9"
    assert "error" in items[1]


# ═══ fields on pm_batch_get ═════════════════════════════════════


def test_fields_returns_exactly_those_keys_plus_id(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(type="stories", fields="status,points"))
    assert items
    for item in items:
        assert set(item) == {"id", "status", "points"}


def test_fields_keeps_id_even_when_unnamed(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(type="tasks", fields="status"))
    assert items
    for item in items:
        assert set(item) == {"id", "status"}
        assert item["id"]


def test_fields_can_ask_for_the_body_back(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(type="stories", fields="body"))
    assert set(items[0]) == {"id", "body"}
    assert items[0]["body"]


def test_the_ids_path_honours_fields(seeded):
    from projectman.server import pm_batch_get

    items = yaml.safe_load(pm_batch_get(ids="US-TST-1-1,US-TST-1-2", fields="status"))
    assert [set(i) for i in items] == [{"id", "status"}, {"id", "status"}]


def test_fields_beats_brief_on_pm_batch_get(seeded):
    """Explicit beats preset — including asking for a key brief drops."""
    from projectman.server import pm_batch_get

    items = yaml.safe_load(
        pm_batch_get(type="stories", brief=True, fields="acceptance_criteria")
    )
    assert set(items[0]) == {"id", "acceptance_criteria"}
    assert items[0]["acceptance_criteria"] == ["It works", "It is fast"]


def test_an_unknown_field_on_pm_batch_get_is_an_error_naming_valid_keys(seeded):
    from projectman.server import pm_batch_get

    with pytest.raises(ToolError) as excinfo:
        pm_batch_get(type="stories", fields="stats")
    message = str(excinfo.value)
    assert "stats" in message
    assert "status" in message
    assert "acceptance_criteria" in message


def test_an_unknown_field_fails_the_whole_ids_call(seeded):
    """It is the caller's mistake about the call, not one item's not-found."""
    from projectman.server import pm_batch_get

    with pytest.raises(ToolError):
        pm_batch_get(ids="US-TST-1,US-TST-1-1", fields="nope")


# ═══ brief and fields on pm_list_sprints ════════════════════════


def test_brief_drops_the_sprint_goal(seeded):
    from projectman.server import pm_list_sprints

    payload = yaml.safe_load(pm_list_sprints(brief=True))
    assert payload["count"] == 2
    for sprint in payload["sprints"]:
        assert "goal" not in sprint
        # Key order follows the item, not the request.
        assert set(sprint) == set(BRIEF_SPRINT_FIELDS)


def test_brief_keeps_the_sprint_rollup_keys(seeded):
    from projectman.server import pm_list_sprints

    sprint = yaml.safe_load(pm_list_sprints(status="completed", brief=True))["sprints"][
        0
    ]
    assert set(sprint) == set(BRIEF_SPRINT_FIELDS)
    full = yaml.safe_load(pm_list_sprints(status="completed"))["sprints"][0]
    for key in BRIEF_SPRINT_FIELDS:
        assert sprint[key] == full[key]


def test_count_survives_every_mode(seeded):
    from projectman.server import pm_list_sprints

    for kwargs in ({}, {"brief": True}, {"fields": "status"}):
        assert yaml.safe_load(pm_list_sprints(**kwargs))["count"] == 2


def test_fields_on_pm_list_sprints_returns_those_keys_plus_id(seeded):
    from projectman.server import pm_list_sprints

    sprints = yaml.safe_load(pm_list_sprints(fields="status,completed_points"))[
        "sprints"
    ]
    for sprint in sprints:
        assert set(sprint) == {"id", "status", "completed_points"}


def test_fields_beats_brief_on_pm_list_sprints(seeded):
    from projectman.server import pm_list_sprints

    sprints = yaml.safe_load(pm_list_sprints(brief=True, fields="goal"))["sprints"]
    assert set(sprints[0]) == {"id", "goal"}
    assert sprints[0]["goal"]


def test_an_unknown_sprint_field_is_an_error_naming_valid_keys(seeded):
    from projectman.server import pm_list_sprints

    with pytest.raises(ToolError) as excinfo:
        pm_list_sprints(fields="goals")
    message = str(excinfo.value)
    assert "goals" in message
    assert "goal" in message
    assert "planned_points" in message


# ═══ Over the wire ══════════════════════════════════════════════


def test_brief_and_fields_are_declared_on_both_tool_schemas():
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    for name in ("pm_batch_get", "pm_list_sprints"):
        properties = tools[name].inputSchema["properties"]
        assert "brief" in properties
        assert "fields" in properties
        # Optional, so nothing that calls these tools today has to change.
        assert not tools[name].inputSchema.get("required")


def test_brief_over_the_wire_on_both_tools(seeded):
    is_error, text = _call_over_the_wire(
        "pm_batch_get", {"type": "stories", "brief": True}
    )
    assert not is_error, text
    assert "acceptance_criteria" not in text

    is_error, text = _call_over_the_wire("pm_list_sprints", {"brief": True})
    assert not is_error, text
    assert "goal" not in text


def test_fields_over_the_wire_on_both_tools(seeded):
    is_error, text = _call_over_the_wire(
        "pm_batch_get", {"type": "tasks", "fields": "status"}
    )
    assert not is_error, text
    for item in yaml.safe_load(text):
        assert set(item) == {"id", "status"}

    is_error, text = _call_over_the_wire(
        "pm_list_sprints", {"fields": "status,planned_points"}
    )
    assert not is_error, text
    for sprint in yaml.safe_load(text)["sprints"]:
        assert set(sprint) == {"id", "status", "planned_points"}


def test_an_unknown_field_over_the_wire_is_an_error_not_an_empty_projection(seeded):
    for name, arguments in (
        ("pm_batch_get", {"type": "stories", "fields": "stats"}),
        ("pm_list_sprints", {"fields": "goals"}),
    ):
        is_error, text = _call_over_the_wire(name, arguments)
        assert is_error, text
        assert "unknown field" in text


# ═══ It actually pays ═══════════════════════════════════════════


@pytest.fixture
def realistic(tmp_project):
    """A corpus shaped like the one that was measured at 37k/27k chars.

    Ten stories with ~1.5k-char bodies and five criteria each, and five
    completed sprints with paragraph-length goals.  The saving is *measured*
    off this, not asserted by construction.
    """
    from projectman.store import Store

    store = Store(tmp_project)
    body = (
        "As a user I want the thing to work so that my work is not blocked. "
        "This paragraph exists to make the body realistically long, because "
        "the whole point of brief mode is that bodies dominate the payload. "
    ) * 8
    assert len(body) >= 1500
    for n in range(1, 11):
        store.create_story(
            f"Story number {n}",
            body,
            points=3,
            acceptance_criteria=[
                f"Criterion {c} of story {n} — stated at realistic length "
                f"so the acceptance criteria weigh what they really weigh"
                for c in range(1, 6)
            ],
        )
    goal = (
        "Deliver the slice end to end with tests and documentation. "
        "This goal is a paragraph because real sprint goals are paragraphs. "
    ) * 4
    for n in range(1, 6):
        sprint = store.create_sprint(f"Sprint {n}", goal=goal)
        store.update_sprint(sprint.id, status="completed")
    return store


def test_brief_batch_get_is_at_most_a_quarter_of_the_full_listing(realistic):
    from projectman.server import pm_batch_get

    full = len(pm_batch_get(type="stories"))
    brief = len(pm_batch_get(type="stories", brief=True))
    ratio = brief / full
    assert ratio <= 0.25, (
        f"pm_batch_get(type='stories', brief=True) is {brief} chars vs "
        f"{full} full — ratio {ratio:.1%}, wanted <= 25%"
    )


def test_brief_list_sprints_is_at_most_a_quarter_of_the_full_listing(realistic):
    from projectman.server import pm_list_sprints

    full = len(pm_list_sprints(status="completed"))
    brief = len(pm_list_sprints(status="completed", brief=True))
    ratio = brief / full
    assert ratio <= 0.25, (
        f"pm_list_sprints(status='completed', brief=True) is {brief} chars vs "
        f"{full} full — ratio {ratio:.1%}, wanted <= 25%"
    )


# ═══ The published contract, over the wire ══════════════════════


def _declared_types(schema_property: dict) -> set:
    """The JSON types a published parameter accepts, flattened out of anyOf."""
    if "anyOf" in schema_property:
        return {branch.get("type") for branch in schema_property["anyOf"]}
    return {schema_property.get("type")}


@pytest.mark.parametrize("tool_name", ["pm_batch_get", "pm_list_sprints"])
def test_the_published_schema_types_brief_and_fields_as_documented(tool_name):
    """Presence is not the contract — a caller reads the types and defaults.

    `test_brief_and_fields_are_declared_on_both_tool_schemas` pins that the
    keys exist; this pins what the docs promise about them: `brief` is a
    boolean defaulting to false, `fields` is an optional string defaulting to
    nothing, so an existing caller that passes neither is unaffected.
    """
    from projectman.server import mcp as mcp_server

    tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    properties = tools[tool_name].inputSchema["properties"]

    assert _declared_types(properties["brief"]) == {"boolean"}
    assert properties["brief"]["default"] is False

    assert "string" in _declared_types(properties["fields"])
    assert properties["fields"]["default"] is None


# ═══ The mixed-type ids path ════════════════════════════════════


def test_a_mixed_type_ids_call_honours_brief_per_item_type(seeded):
    """One brief preset, three item types, one call — and no KeyError.

    The preset names keys no single type has all of (`epic_id` on a task,
    `story_id` on an epic), so the intersection rule has to hold across a
    heterogeneous batch, not just within one type.
    """
    from projectman.server import pm_batch_get

    ids = "EPIC-TST-1,US-TST-1,US-TST-1-2"
    full = yaml.safe_load(pm_batch_get(ids=ids))
    brief = yaml.safe_load(pm_batch_get(ids=ids, brief=True))

    # Order and count are the caller's, not the projection's.
    assert [i["id"] for i in brief] == ["EPIC-TST-1", "US-TST-1", "US-TST-1-2"]
    assert len(brief) == len(full)

    for full_item, brief_item in zip(full, brief):
        assert list(brief_item) == [k for k in full_item if k in set(BRIEF_ITEM_FIELDS)]
        assert "body" not in brief_item
        for key, value in brief_item.items():
            assert value == full_item[key]

    epic, story, task = brief
    assert "story_id" not in epic and "epic_id" not in epic
    assert story["epic_id"] == "EPIC-TST-1"
    assert task["story_id"] == "US-TST-1"


# ═══ An empty goal is still a goal ══════════════════════════════


def test_brief_omits_the_goal_key_even_when_the_goal_is_empty(tmp_project):
    """Absent, not empty: `goal: ''` would still cost bytes and still leak.

    A sprint's goal is `str` in the model, so "" is as empty as it gets; the
    projection must drop the key rather than pass an empty one through.
    """
    from projectman.server import pm_list_sprints
    from projectman.store import Store

    store = Store(tmp_project)
    store.create_sprint("Goalless Sprint")

    full = yaml.safe_load(pm_list_sprints())["sprints"][0]
    assert full["goal"] == ""  # the key really is there to be dropped

    text = pm_list_sprints(brief=True)
    assert "goal" not in text
    assert "goal" not in yaml.safe_load(text)["sprints"][0]


def test_brief_preserves_sprint_order_and_count(seeded):
    """The listing is the same listing — brief only narrows each row."""
    from projectman.server import pm_list_sprints

    full = yaml.safe_load(pm_list_sprints())
    brief = yaml.safe_load(pm_list_sprints(brief=True))
    assert brief["count"] == full["count"]
    assert [s["id"] for s in brief["sprints"]] == [s["id"] for s in full["sprints"]]


# ═══ It pays on this repository's own data ══════════════════════
#
# The `realistic` corpus above is shaped like the measured one, but it is
# still a fixture written by the same hand that wrote the assertion.  These
# two run the scan-the-backlog and scan-the-history calls against a copy of
# *this repository's* `.project/` tree — 85 stories and 4 sprints of real,
# unchosen prose.  The copy is what is measured; the live tree is only read.


@pytest.fixture
def live_project(tmp_path, monkeypatch, chdir_to_project):
    """A throwaway copy of this repo's real ``.project/`` (see test_field_projection).

    ``chdir_to_project`` is requested only for ordering: the autouse fixture
    chdirs to the synthetic project, and this must chdir *after* it.
    """
    import shutil
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / ".project"
    if not source.is_dir():
        pytest.skip("no live .project/ tree here (packaged install)")

    root = tmp_path / "live"
    root.mkdir()
    shutil.copytree(source, root / ".project")
    monkeypatch.chdir(root)

    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()
    return root


def test_real_brief_batch_get_is_a_small_fraction_of_this_repos_backlog(live_project):
    """`pm_batch_get(type="stories")` is the 37,593-char call the study flagged."""
    from projectman.server import pm_batch_get

    stories = yaml.safe_load(pm_batch_get(type="stories"))
    assert len(stories) >= 20, (
        f"only {len(stories)} stories in the copied project — too small a "
        "corpus for the ratio below to mean anything"
    )

    full = len(pm_batch_get(type="stories"))
    brief = len(pm_batch_get(type="stories", brief=True))
    ratio = brief / full

    assert full >= 10000, (
        f"full pm_batch_get(type='stories') is only {full} chars — not the "
        "list-everything payload the budget is about"
    )
    assert ratio <= 0.25, (
        f"brief pm_batch_get(type='stories') is {brief} of {full} chars over "
        f"{len(stories)} real stories = {ratio:.2%}; budget is 25%"
    )


def test_real_brief_list_sprints_drops_the_goals_on_this_repos_history(live_project):
    """The same measurement on the real sprint history, goals and all."""
    from projectman.server import pm_list_sprints

    payload = yaml.safe_load(pm_list_sprints())
    count = payload["count"]
    assert count >= 3, f"only {count} sprints here — nothing to measure"

    full = len(pm_list_sprints())
    brief = len(pm_list_sprints(brief=True))
    ratio = brief / full

    for sprint in yaml.safe_load(pm_list_sprints(brief=True))["sprints"]:
        assert "goal" not in sprint

    # A short history of short-goal sprints cannot reach the 25% the stories
    # listing does — that budget is pinned on `realistic` above.  What the
    # real data has to show is that the saving is real and substantial.
    assert ratio <= 0.75, (
        f"brief pm_list_sprints() is {brief} of {full} chars over {count} "
        f"real sprints = {ratio:.2%}; budget is 75% on a history this short"
    )
