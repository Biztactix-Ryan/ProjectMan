"""Token-list parameters accept a real list, not just a comma string (US-PRJ-58).

Tags, dependency IDs, item IDs and field names are *tokens*: a comma inside
one is a separator, so the server has always split a string on commas.  What
it did not do was accept the list an MCP client already had in hand — clients
were joining ``["a", "b"]`` into ``"a,b"`` purely so the server could split it
straight back apart.

``_as_list`` is the one normaliser both shapes go through.  Every test below
is a *pair*: the same call made once with a comma string and once with the
equivalent list, asserting the two land identically on disk.  The string half
is the backwards-compatibility guard — it must keep behaving exactly as it
did.

Acceptance criteria are deliberately NOT here.  They are natural language, not
tokens, and ``_criteria_list`` (see ``tests/test_comma_bearing_criteria.py``)
is their normaliser precisely because they must never be split on commas.
"""

import anyio
import pytest

from projectman.server import _as_list, _as_csv
from projectman.store import Store, clear_all_caches


# ─── _as_list itself ────────────────────────────────────────────────────


def test_as_list_passes_none_through():
    """``None`` is "not supplied" and must stay distinguishable from empty."""
    assert _as_list(None) is None


def test_as_list_empty_string_is_the_empty_list():
    """"Supplied, but empty" — the shape the update path reads as "clear it"."""
    assert _as_list("") == []


def test_as_list_empty_list_is_the_empty_list():
    assert _as_list([]) == []


def test_as_list_splits_a_comma_string_stripping_and_dropping_blanks():
    assert _as_list("a, b,,c") == ["a", "b", "c"]


def test_as_list_takes_a_list_entry_per_entry_and_strips_it():
    assert _as_list(["a ", " b"]) == ["a", "b"]


def test_as_list_drops_blank_entries_of_a_list():
    assert _as_list(["a", "", "  ", "b"]) == ["a", "b"]


def test_as_list_does_not_split_inside_a_list_entry():
    """A list says where the boundaries are; the server must not second-guess.

    This is the one place the two input shapes genuinely differ, and it is the
    reason to prefer the list form: an entry may contain a comma.
    """
    assert _as_list(["a,b"]) == ["a,b"]


def test_as_list_string_and_equivalent_list_agree():
    assert _as_list("a,b,c") == _as_list(["a", "b", "c"]) == ["a", "b", "c"]


def test_as_csv_rejoins_both_shapes_to_the_same_string():
    assert _as_csv(" a , b ") == _as_csv(["a", "b"]) == "a,b"
    assert _as_csv(None) is None
    assert _as_csv("") == ""


# ─── the tools, string vs list ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Server tools resolve the project from the cwd."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    _store_cache.clear()
    clear_all_caches()


def _wire(tool_name, **arguments):
    """Call a tool the way a client does — through ``mcp.call_tool``."""
    from projectman.server import mcp as mcp_server

    return anyio.run(mcp_server.call_tool, tool_name, arguments)


def _text(result):
    """The text payload of a ``call_tool`` result, whatever tuple shape it has."""
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        return "\n".join(getattr(block, "text", str(block)) for block in result)
    return str(result)


def _fresh(tmp_project):
    clear_all_caches()
    return Store(tmp_project)


def _story(tmp_project, story_id):
    meta, _ = _fresh(tmp_project).get_story(story_id)
    return meta


def _task(tmp_project, task_id):
    meta, _ = _fresh(tmp_project).get_task(task_id)
    return meta


def _epic(tmp_project, epic_id):
    meta, _ = _fresh(tmp_project).get_epic(epic_id)
    return meta


def _seed_story(title="Story"):
    _wire("pm_create_story", title=title, description="Desc")


# --- pm_create_story.tags / .depends_on ---


@pytest.mark.parametrize(
    "tags, depends_on",
    [
        ("alpha,beta", "US-TST-1"),
        (["alpha", "beta"], ["US-TST-1"]),
    ],
    ids=["string", "list"],
)
def test_create_story_tags_and_depends_on_both_shapes(tmp_project, tags, depends_on):
    _seed_story("Dependency")
    _wire(
        "pm_create_story",
        title="Login",
        description="Desc",
        tags=tags,
        depends_on=depends_on,
    )
    meta = _story(tmp_project, "US-TST-2")
    assert list(meta.tags) == ["alpha", "beta"]
    assert list(meta.depends_on) == ["US-TST-1"]


# --- pm_create_epic.tags ---


@pytest.mark.parametrize(
    "tags", ["alpha,beta", ["alpha", "beta"]], ids=["string", "list"]
)
def test_create_epic_tags_both_shapes(tmp_project, tags):
    _wire("pm_create_epic", title="Auth", description="Desc", tags=tags)
    assert list(_epic(tmp_project, "EPIC-TST-1").tags) == ["alpha", "beta"]


# --- pm_create_task.tags / .depends_on ---


@pytest.mark.parametrize(
    "tags, depends_on",
    [
        ("backend,api", "US-TST-1-1"),
        (["backend", "api"], ["US-TST-1-1"]),
    ],
    ids=["string", "list"],
)
def test_create_task_tags_and_depends_on_both_shapes(tmp_project, tags, depends_on):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire(
        "pm_create_task",
        story_id="US-TST-1",
        title="Second",
        description="D",
        tags=tags,
        depends_on=depends_on,
    )
    meta = _task(tmp_project, "US-TST-1-2")
    assert list(meta.tags) == ["backend", "api"]
    assert list(meta.depends_on) == ["US-TST-1-1"]


# --- pm_update.tags / .depends_on / .clear ---


@pytest.mark.parametrize(
    "tags, depends_on",
    [
        ("alpha,beta", "US-TST-1-1"),
        (["alpha", "beta"], ["US-TST-1-1"]),
    ],
    ids=["string", "list"],
)
def test_update_tags_and_depends_on_both_shapes(tmp_project, tags, depends_on):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    _wire("pm_update", id="US-TST-1-2", tags=tags, depends_on=depends_on)
    meta = _task(tmp_project, "US-TST-1-2")
    assert list(meta.tags) == ["alpha", "beta"]
    assert list(meta.depends_on) == ["US-TST-1-1"]


@pytest.mark.parametrize(
    "clear", ["tags,depends_on", ["tags", "depends_on"]], ids=["string", "list"]
)
def test_update_clear_both_shapes(tmp_project, clear):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire(
        "pm_create_task",
        story_id="US-TST-1",
        title="Second",
        description="D",
        tags=["alpha"],
        depends_on=["US-TST-1-1"],
    )
    _wire("pm_update", id="US-TST-1-2", clear=clear)
    meta = _task(tmp_project, "US-TST-1-2")
    assert list(meta.tags) == []
    assert list(meta.depends_on) == []


# --- pm_update_many.ids / .tags / .depends_on / .clear ---


@pytest.mark.parametrize(
    "ids, tags",
    [
        ("US-TST-1-1,US-TST-1-2", "alpha,beta"),
        (["US-TST-1-1", "US-TST-1-2"], ["alpha", "beta"]),
    ],
    ids=["string", "list"],
)
def test_update_many_ids_and_tags_both_shapes(tmp_project, ids, tags):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    _wire("pm_update_many", ids=ids, tags=tags)
    for task_id in ("US-TST-1-1", "US-TST-1-2"):
        assert list(_task(tmp_project, task_id).tags) == ["alpha", "beta"]


@pytest.mark.parametrize(
    "depends_on", ["US-TST-1-1", ["US-TST-1-1"]], ids=["string", "list"]
)
def test_update_many_depends_on_both_shapes(tmp_project, depends_on):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    _wire("pm_update_many", ids=["US-TST-1-2"], depends_on=depends_on)
    assert list(_task(tmp_project, "US-TST-1-2").depends_on) == ["US-TST-1-1"]


@pytest.mark.parametrize("clear", ["tags", ["tags"]], ids=["string", "list"])
def test_update_many_clear_both_shapes(tmp_project, clear):
    _seed_story()
    _wire(
        "pm_create_task",
        story_id="US-TST-1",
        title="First",
        description="D",
        tags=["alpha"],
    )
    _wire("pm_update_many", ids=["US-TST-1-1"], clear=clear)
    assert list(_task(tmp_project, "US-TST-1-1").tags) == []


# --- pm_archive_many.ids ---


@pytest.mark.parametrize(
    "ids",
    ["US-TST-1-1,US-TST-1-2", ["US-TST-1-1", "US-TST-1-2"]],
    ids=["string", "list"],
)
def test_archive_many_ids_both_shapes(tmp_project, ids):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    _wire("pm_archive_many", ids=ids)
    for task_id in ("US-TST-1-1", "US-TST-1-2"):
        assert _task(tmp_project, task_id).archived is True


# --- pm_get.id and pm_batch_get.ids ---


@pytest.mark.parametrize(
    "ids",
    ["US-TST-1-1,US-TST-1-2", ["US-TST-1-1", "US-TST-1-2"]],
    ids=["string", "list"],
)
def test_get_id_both_shapes(tmp_project, ids):
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    out = _text(_wire("pm_get", id=ids))
    assert "US-TST-1-1" in out and "US-TST-1-2" in out


@pytest.mark.parametrize(
    "ids",
    ["US-TST-1-1,US-TST-1-2", ["US-TST-1-1", "US-TST-1-2"]],
    ids=["string", "list"],
)
def test_get_task_id_alias_both_shapes(tmp_project, ids):
    """The alias is widened with the canonical spelling, or half the callers break."""
    _seed_story()
    _wire("pm_create_task", story_id="US-TST-1", title="First", description="D")
    _wire("pm_create_task", story_id="US-TST-1", title="Second", description="D")
    out = _text(_wire("pm_get", task_id=ids))
    assert "US-TST-1-1" in out and "US-TST-1-2" in out


def test_get_id_and_task_id_agree_across_shapes(tmp_project):
    """A list and the equivalent string are the SAME id, not a conflict."""
    _seed_story()
    out = _text(_wire("pm_get", id="US-TST-1", task_id=["US-TST-1"]))
    assert "US-TST-1" in out
    assert not out.startswith("error:")


@pytest.mark.parametrize(
    "ids",
    ["US-TST-1,US-TST-2", ["US-TST-1", "US-TST-2"]],
    ids=["string", "list"],
)
def test_batch_get_ids_both_shapes(tmp_project, ids):
    _seed_story("One")
    _seed_story("Two")
    out = _text(_wire("pm_batch_get", ids=ids))
    assert "US-TST-1" in out and "US-TST-2" in out


# --- pm_create_sprint.planned_stories / pm_update_sprint.planned_stories ---


def _sprint(tmp_project, sprint_id):
    return _fresh(tmp_project).get_sprint(sprint_id)[0]


@pytest.mark.parametrize(
    "planned_stories",
    ["US-TST-1,US-TST-2", ["US-TST-1", "US-TST-2"]],
    ids=["string", "list"],
)
def test_create_sprint_planned_stories_both_shapes(tmp_project, planned_stories):
    _seed_story("One")
    _seed_story("Two")
    _wire("pm_create_sprint", name="Sprint 1", planned_stories=planned_stories)
    meta = _sprint(tmp_project, "SPRINT-TST-1")
    assert list(meta.planned_stories) == ["US-TST-1", "US-TST-2"]


@pytest.mark.parametrize(
    "planned_stories",
    ["US-TST-1,US-TST-2", ["US-TST-1", "US-TST-2"]],
    ids=["string", "list"],
)
def test_update_sprint_planned_stories_both_shapes(tmp_project, planned_stories):
    _seed_story("One")
    _seed_story("Two")
    _wire("pm_create_sprint", name="Sprint 1", planned_stories="US-TST-1")
    _wire(
        "pm_update_sprint",
        sprint_id="SPRINT-TST-1",
        planned_stories=planned_stories,
    )
    meta = _sprint(tmp_project, "SPRINT-TST-1")
    assert list(meta.planned_stories) == ["US-TST-1", "US-TST-2"]


@pytest.mark.parametrize("planned_stories", ["", []], ids=["string", "list"])
def test_update_sprint_planned_stories_empty_clears_in_both_shapes(
    tmp_project, planned_stories
):
    """"Supplied, but empty" still means "clear it" — the shapes agree there too."""
    _seed_story("One")
    _wire("pm_create_sprint", name="Sprint 1", planned_stories=["US-TST-1"])
    _wire(
        "pm_update_sprint",
        sprint_id="SPRINT-TST-1",
        planned_stories=planned_stories,
    )
    assert list(_sprint(tmp_project, "SPRINT-TST-1").planned_stories) == []


def test_update_sprint_omitting_planned_stories_leaves_them_alone(tmp_project):
    """``None`` is "not supplied" — the guard the empty-clears case depends on."""
    _seed_story("One")
    _wire("pm_create_sprint", name="Sprint 1", planned_stories=["US-TST-1"])
    _wire("pm_update_sprint", sprint_id="SPRINT-TST-1", goal="Ship it")
    assert list(_sprint(tmp_project, "SPRINT-TST-1").planned_stories) == ["US-TST-1"]


# ─── the two shapes are interchangeable, end to end ─────────────────────


def test_string_and_list_produce_byte_identical_stored_tags(tmp_project):
    """The whole point: neither shape is a second-class citizen."""
    _wire("pm_create_story", title="A", description="D", tags="alpha, beta")
    _wire("pm_create_story", title="B", description="D", tags=["alpha", "beta"])
    assert list(_story(tmp_project, "US-TST-1").tags) == list(
        _story(tmp_project, "US-TST-2").tags
    )


#: Every token-list parameter on the surface, per tool.  Both the schema test
#: and the documentation test below read this one map, so a param widened
#: without being documented (or vice versa) fails here.
WIDENED = {
    "pm_create_story": ("tags", "depends_on"),
    "pm_create_epic": ("tags",),
    "pm_create_task": ("tags", "depends_on"),
    "pm_update": ("tags", "depends_on", "clear"),
    "pm_update_many": ("ids", "tags", "depends_on", "clear"),
    "pm_archive_many": ("ids",),
    "pm_get": ("id", "task_id"),
    "pm_batch_get": ("ids",),
    "pm_create_sprint": ("planned_stories",),
    "pm_update_sprint": ("planned_stories",),
}


def test_schema_advertises_both_shapes_for_widened_params():
    """tools/list must show the union, or clients never learn a list is legal."""
    from projectman.server import mcp as mcp_server

    tools = {t.name: t for t in anyio.run(mcp_server.list_tools)}
    for tool_name, params in WIDENED.items():
        schema = tools[tool_name].inputSchema["properties"]
        for param in params:
            types = {
                option.get("type") for option in schema[param].get("anyOf", [])
            }
            assert {"string", "array"} <= types, (tool_name, param, schema[param])


def test_docstrings_document_both_shapes_for_widened_params():
    """A union the docstring never mentions is a union no client will use.

    The tool description is what an MCP client actually reads, so the *only*
    place "you may pass a list here" can be said is the ``Args`` entry.
    """
    import projectman.server as server

    for tool_name, params in WIDENED.items():
        doc = getattr(server, tool_name).__doc__ or ""
        entries = {
            line.strip().split(":", 1)[0]: line.strip()
            for line in doc.splitlines()
            if line.strip() and ":" in line
        }
        for param in params:
            entry = entries.get(param)
            assert entry, f"{tool_name}.{param} has no Args entry"
            # An ID alias carries one fixed sentence project-wide — see
            # tests/test_id_alias_resolver.py, which asserts that wording
            # exactly. The canonical spelling it points at documents the two
            # shapes for both, so the alias must not repeat them.
            if entry.startswith(f"{param}: Alias for "):
                continue
            assert "list" in entry, f"{tool_name}.{param} never mentions a list"
            assert "comma-separated" in entry, (
                f"{tool_name}.{param} never mentions the comma-separated string"
            )


def test_reference_docs_document_both_shapes_for_widened_params():
    """``docs/reference/mcp-tools.md`` is the human-facing half of the same promise."""
    from pathlib import Path

    doc = (
        Path(__file__).resolve().parents[1] / "docs/reference/mcp-tools.md"
    ).read_text()
    assert "## Token-list parameters" in doc
    for tool_name, params in WIDENED.items():
        for param in params:
            assert f"| `{tool_name}` |" in doc, f"{tool_name} missing from the table"
            assert param in doc, f"{param} undocumented"
