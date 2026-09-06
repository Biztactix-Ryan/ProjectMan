"""Tools route by the ID's prefix or an explicit one; `project` is gone (US-PM-34).

``tests/test_server_routing.py`` pins the resolver itself.  This module pins
what the *tools* do with it, which is the pair of sibling criteria the resolver
exists to satisfy:

* **US-PM-34-2** — in a hub, ``pm_get``, ``pm_update`` and the verdict verbs
  (``pm_accept``, ``pm_retry``, ``pm_park``, ``pm_review``), plus ``pm_grab``
  and ``pm_release``, find the store named by the ID prefix with no other
  argument; ``pm_accept`` claims its next task from that same store; and an
  unknown prefix comes back as a coded ``not_found`` naming the known prefixes.
* **US-PM-34-3** — ``pm_get``, ``pm_batch_get``, ``pm_update_many`` and
  ``pm_archive_many`` accept IDs from several stores in one call, answer in
  input order with every item read from (and written to) its own store, and
  report a bad ID in the partial-failure shape each tool already documents.

* **US-PM-34-4** — the ID-less verbs take an optional ``prefix`` instead: in a
  hub an omitted prefix reads the hub's own store and *refuses* a create, a
  given prefix picks that project's store, and an unknown one fails the same
  coded way an unknown prefix inside an ID does.
* **US-PM-34-5** — in single-project mode ``prefix`` is ignored outright, so
  nothing about that install's behaviour moved.

Plus the ``tools/list`` guard US-PM-34-1 reads: **no** tool advertises a
``project`` property any more, and the tools that advertise ``prefix`` are
exactly the ID-less ones.

Everything below drives the real tools — the Python entry point for the happy
paths, and the low-level ``CallToolRequest`` handler wherever the *coded* error
on the wire is the thing being asserted.
"""

import inspect

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import Store, clear_all_caches

from conftest import make_hub_subproject

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ─── fixtures ────────────────────────────────────────────────────


def _reset_caches() -> None:
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


def _seed(prefix: str, task_count: int) -> str:
    """One ready, active story with *task_count* ready tasks in a subproject.

    Created through the tools, so the fixture itself exercises both halves of
    the change: ``pm_create_story`` is ID-less and names its store with
    ``prefix``, while ``pm_create_tasks`` routes through ``story_id``.
    """
    from projectman.server import pm_create_story, pm_create_tasks, pm_update

    pm_create_story(
        f"{prefix} story", "Story body text long enough to matter.", prefix=prefix
    )
    story_id = f"US-{prefix}-1"
    pm_update(story_id, status="active")
    pm_create_tasks(
        story_id,
        [
            {"title": f"{prefix} task {i}", "description": READY_BODY, "points": 1}
            for i in range(1, task_count + 1)
        ],
    )
    return story_id


@pytest.fixture
def hub(tmp_hub, monkeypatch):
    """A hub (prefix HUB) with two attached subprojects, API and WEB.

    API owns ``US-API-1`` with three tasks, WEB owns ``US-WEB-1`` with two, so
    every cross-store assertion has a real item on both sides of the boundary.
    """
    make_hub_subproject(tmp_hub, "api", "API")
    make_hub_subproject(tmp_hub, "web", "WEB")
    monkeypatch.chdir(tmp_hub)
    _reset_caches()
    _seed("API", 3)
    _seed("WEB", 2)
    yield tmp_hub
    _reset_caches()


def _on_disk(hub_root, name: str) -> Store:
    """A Store reading *name*'s directory straight from disk, uncached."""
    clear_all_caches()
    return Store(hub_root, project_dir=hub_root / "projects" / name / ".project")


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


# ═══ US-PM-34-2 — one ID, no second argument ════════════════════


class TestThePrefixNamesTheStore:
    """AC (US-PM-34-2): the ID is the whole address."""

    def test_pm_get_reads_each_store_by_prefix(self, hub):
        from projectman.server import pm_get

        assert yaml.safe_load(pm_get("US-API-1"))["title"] == "API story"
        assert yaml.safe_load(pm_get("US-WEB-1"))["title"] == "WEB story"
        assert yaml.safe_load(pm_get("US-API-1-2"))["title"] == "API task 2"

    def test_pm_update_writes_only_into_the_store_the_prefix_names(self, hub):
        from projectman.server import pm_update

        pm_update("US-API-1", title="Renamed by prefix alone")

        assert _on_disk(hub, "api").get("US-API-1")[0].title == (
            "Renamed by prefix alone"
        )
        # The sibling store is untouched — routing chose, it did not broadcast.
        assert _on_disk(hub, "web").get("US-WEB-1")[0].title == "WEB story"

    def test_grab_and_release_route_by_prefix(self, hub):
        from projectman.server import pm_grab, pm_release

        grabbed = yaml.safe_load(pm_grab("US-WEB-1-1", assignee="worker"))
        assert grabbed["grabbed"]["task"]["id"] == "US-WEB-1-1"
        assert _on_disk(hub, "web").get("US-WEB-1-1")[0].assignee == "worker"

        released = yaml.safe_load(pm_release("US-WEB-1-1", note="handing back"))
        assert released["released"]["from_assignee"] == "worker"
        assert _on_disk(hub, "web").get("US-WEB-1-1")[0].assignee is None

    @pytest.mark.parametrize(
        "verb,task_id,key,status",
        [
            ("pm_retry", "US-API-1-1", "retried", "todo"),
            ("pm_park", "US-API-1-2", "parked", "review"),
            ("pm_review", "US-API-1-3", "reviewed", "review"),
        ],
    )
    def test_each_verdict_verb_routes_by_prefix(self, hub, verb, task_id, key, status):
        import projectman.server as server

        result = yaml.safe_load(getattr(server, verb)(task_id, note="a verdict"))

        assert result[key]["task"]["id"] == task_id
        assert _on_disk(hub, "api").get(task_id)[0].status.value == status

    def test_pm_accept_claims_the_next_task_from_the_same_store(self, hub):
        """The claim after the verdict must not wander into another project.

        ``same_story_only=False`` deliberately opens the search to every story
        the store can see; WEB has two ready tasks and must still never be the
        answer, because the accepted task's store is the only one consulted.
        """
        from projectman.server import pm_accept

        result = yaml.safe_load(
            pm_accept("US-API-1-1", note="done", same_story_only=False)
        )

        assert result["completed"]["id"] == "US-API-1-1"
        assert result["next"]["task"]["id"] == "US-API-1-2"
        assert _on_disk(hub, "web").get("US-WEB-1-1")[0].assignee is None

    def test_when_the_store_runs_out_the_answer_is_none_not_a_sibling_project(
        self, hub
    ):
        from projectman.server import pm_accept

        for task_id in ("US-API-1-1", "US-API-1-2"):
            pm_accept(task_id, note="done", same_story_only=False)
        last = yaml.safe_load(
            pm_accept("US-API-1-3", note="done", same_story_only=False)
        )

        assert last["status"] == "no_next_task"
        assert last["next"] is None
        # WEB's ready tasks were never candidates.
        assert _on_disk(hub, "web").get("US-WEB-1-1")[0].status.value == "todo"


class TestAnUnknownPrefixIsACodedNotFound:
    """AC (US-PM-34-2), second half: the error names the prefixes that exist."""

    CALLS = {
        "pm_get": {"id": "US-NOPE-1"},
        "pm_update": {"id": "US-NOPE-1", "status": "done"},
        "pm_grab": {"task_id": "US-NOPE-1-1"},
        "pm_release": {"task_id": "US-NOPE-1-1"},
        "pm_accept": {"task_id": "US-NOPE-1-1", "note": "n"},
        "pm_retry": {"task_id": "US-NOPE-1-1", "note": "n"},
        "pm_park": {"task_id": "US-NOPE-1-1", "note": "n"},
        "pm_review": {"task_id": "US-NOPE-1-1", "note": "n"},
    }

    @pytest.mark.parametrize("tool", sorted(CALLS))
    def test_the_wire_error_is_coded_and_lists_the_known_prefixes(self, hub, tool):
        is_error, text = _call_over_the_wire(tool, self.CALLS[tool])

        assert is_error is True, text
        assert "[code: not_found]" in text
        assert "NOPE" in text
        assert "API, HUB, WEB" in text

    @pytest.mark.parametrize("tool", sorted(CALLS))
    def test_a_malformed_id_is_coded_invalid(self, hub, tool):
        arguments = {
            key: ("nonsense" if key in ("id", "task_id") else value)
            for key, value in self.CALLS[tool].items()
        }

        is_error, text = _call_over_the_wire(tool, arguments)

        assert is_error is True, text
        assert "[code: invalid]" in text

    def test_nothing_was_written_anywhere(self, hub):
        """A routing failure is a refusal, not a half-applied write."""
        _call_over_the_wire("pm_update", {"id": "US-NOPE-1", "status": "done"})

        assert _on_disk(hub, "api").get("US-API-1")[0].status.value == "active"
        assert _on_disk(hub, "web").get("US-WEB-1")[0].status.value == "active"


# ═══ US-PM-34-3 — several stores in one call ════════════════════


MIXED = ["US-WEB-1-1", "US-API-1-2", "US-WEB-1-2", "US-API-1-1"]


class TestMultiIdToolsSpanStores:
    """AC (US-PM-34-3): input order out, each item from its own store."""

    def test_pm_get_answers_in_input_order_across_stores(self, hub):
        from projectman.server import pm_get

        items = yaml.safe_load(pm_get(",".join(MIXED)))

        assert [item["id"] for item in items] == MIXED
        assert [item["title"] for item in items] == [
            "WEB task 1",
            "API task 2",
            "WEB task 2",
            "API task 1",
        ]

    def test_pm_batch_get_answers_in_input_order_across_stores(self, hub):
        from projectman.server import pm_batch_get

        items = yaml.safe_load(pm_batch_get(ids=MIXED))

        assert [item["id"] for item in items] == MIXED
        assert [item["story_id"] for item in items] == [
            "US-WEB-1",
            "US-API-1",
            "US-WEB-1",
            "US-API-1",
        ]

    def test_pm_update_many_writes_into_every_store_in_input_order(self, hub):
        from projectman.server import pm_update_many

        result = yaml.safe_load(pm_update_many(ids=MIXED, points=5))

        assert result["count"] == 4
        assert [entry["id"] for entry in result["updated"]] == MIXED
        assert "partial" not in result
        for name, prefix in (("api", "API"), ("web", "WEB")):
            store = _on_disk(hub, name)
            for n in (1, 2):
                assert store.get(f"US-{prefix}-1-{n}")[0].points == 5

    def test_pm_archive_many_archives_across_stores_in_input_order(self, hub):
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids=MIXED))

        assert result["count"] == 4
        assert [entry["id"] for entry in result["archived"]] == MIXED
        assert "partial" not in result
        assert _on_disk(hub, "api").get("US-API-1-1")[0].archived is True
        assert _on_disk(hub, "web").get("US-WEB-1-2")[0].archived is True
        # The third API task was not in the list and is untouched.
        assert _on_disk(hub, "api").get("US-API-1-3")[0].archived is False


class TestABadIdKeepsEachToolsPartialFailureShape:
    """A prefix nobody owns is one item's problem, not the call's.

    ``_stores_for_ids`` is deliberately all-or-nothing, so each of these four
    tools resolves per ID instead: their published contract already says a bad
    ID is reported *per item* while the rest of the sweep lands, and an unknown
    prefix is just another way for one ID to be bad.
    """

    def test_pm_get_reports_it_in_the_items_own_error_key(self, hub):
        from projectman.server import pm_get

        items = yaml.safe_load(pm_get("US-API-1-1,US-NOPE-9,US-WEB-1-1"))

        assert [item["id"] for item in items] == [
            "US-API-1-1",
            "US-NOPE-9",
            "US-WEB-1-1",
        ]
        assert "NOPE" in items[1]["error"]
        assert "error" not in items[0] and "error" not in items[2]

    def test_pm_batch_get_reports_it_in_the_items_own_error_key(self, hub):
        from projectman.server import pm_batch_get

        items = yaml.safe_load(
            pm_batch_get(ids=["US-API-1-1", "US-NOPE-9", "US-WEB-1-1"])
        )

        assert [item["id"] for item in items] == [
            "US-API-1-1",
            "US-NOPE-9",
            "US-WEB-1-1",
        ]
        assert "NOPE" in items[1]["error"]

    def test_pm_update_many_reports_it_as_a_partial_failure(self, hub):
        from projectman.server import pm_update_many

        result = yaml.safe_load(
            pm_update_many(ids=["US-API-1-1", "US-NOPE-9", "US-WEB-1-1"], points=3)
        )

        assert result["partial"] is True
        assert result["count"] == 2
        assert result["succeeded"] == ["US-API-1-1", "US-WEB-1-1"]
        assert [f["id"] for f in result["failed"]] == ["US-NOPE-9"]
        assert result["failed_count"] == 1
        # The two good items landed in their own stores.
        assert _on_disk(hub, "api").get("US-API-1-1")[0].points == 3
        assert _on_disk(hub, "web").get("US-WEB-1-1")[0].points == 3

    def test_pm_archive_many_reports_it_as_a_partial_failure(self, hub):
        from projectman.server import pm_archive_many

        result = yaml.safe_load(
            pm_archive_many(ids=["US-API-1-1", "US-NOPE-9", "US-WEB-1-1"])
        )

        assert result["partial"] is True
        assert result["count"] == 2
        assert result["succeeded"] == ["US-API-1-1", "US-WEB-1-1"]
        assert [f["id"] for f in result["failed"]] == ["US-NOPE-9"]

    def test_a_partial_failure_is_not_a_failed_call(self, hub):
        is_error, text = _call_over_the_wire(
            "pm_update_many",
            {"ids": ["US-API-1-1", "US-NOPE-9"], "points": 3},
        )

        assert is_error is False, text
        assert not text.lstrip().startswith("error:")


# ═══ The tools/list guard (US-PM-34-1's half of the surface) ════


#: Every tool that resolves its store from an ID it was given.  None of them
#: may carry `project` — the ID already said which store, and saying it twice
#: is the thing US-PM-34 removes.
ROUTED_BY_ID = {
    "pm_get",
    "pm_batch_get",
    "pm_epic",
    "pm_create_task",
    "pm_create_tasks",
    "pm_update",
    "pm_update_many",
    "pm_archive",
    "pm_archive_many",
    "pm_grab",
    "pm_release",
    "pm_accept",
    "pm_retry",
    "pm_park",
    "pm_review",
    "pm_done_next",
    "pm_estimate",
    "pm_scope",
    "pm_get_sprint",
    "pm_update_sprint",
    "pm_run_log",
}

#: Every verb with **no ID to route by**.  Each takes an optional `prefix`
#: instead — the same vocabulary as an ID's own prefix, so a hub is addressed
#: one way everywhere.  None of them takes `project`.
#:
#: Two of them read as ID-taking and are not.  ``pm_activity``'s ``item_id``
#: is a free-text *filter* matched against whatever string the log recorded,
#: not an operand — routing it would turn a legitimate filter into an
#: `invalid` error.  ``pm_fix_malformed``'s ``id`` is the id being *written
#: into* a quarantined file; the file, not the id, says which store is being
#: repaired, and the break-glass CLI addresses it with ``--project``.
#:
#: ``pm_create_epic`` is ID-less too, and takes **no** prefix: epics are
#: hub-level (US-PM-36), so there is no store to choose — in a hub they are
#: written to the hub's own store and carry its prefix.  Its own criteria live
#: in ``tests/test_hub_epics.py``.
ID_LESS = {
    "pm_activity",
    "pm_active",
    "pm_audit",
    "pm_auto_scope",
    "pm_board",
    "pm_burndown",
    "pm_commit",
    "pm_context",
    "pm_create_sprint",
    "pm_create_story",
    "pm_docs",
    "pm_fix_malformed",
    "pm_git_status",
    "pm_list_sprints",
    "pm_malformed",
    "pm_next",
    "pm_push",
    "pm_reindex",
    "pm_restore",
    "pm_search",
    "pm_status",
    "pm_update_doc",
}

#: The ID-less verbs that make new items *in a project*.  A hub has no default
#: project to create in, so these refuse an omitted prefix instead of silently
#: filing the work under the hub, where nobody would look for it.
#: ``pm_create_epic`` is not among them — a hub epic belongs to the hub, so it
#: has nothing to refuse.
CREATE_VERBS = {
    "pm_create_story",
    "pm_create_sprint",
    "pm_auto_scope",
}


@pytest.fixture
def every_tool_schema():
    """``tools/list`` with every gated family on, so nothing hides."""
    from projectman.server import apply_tool_gating, gated_tool_state
    from projectman.server import mcp as mcp_server

    before = gated_tool_state()
    apply_tool_gating({family: True for family in before})
    try:
        yield {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
    finally:
        apply_tool_gating(before)


def test_no_tool_at_all_advertises_a_project_property(every_tool_schema):
    """US-PM-34-1's headline, on the live schema: `project` is gone."""
    offenders = sorted(
        name
        for name, tool in every_tool_schema.items()
        if "project" in tool.inputSchema.get("properties", {})
    )

    assert offenders == []


def test_the_tools_that_take_a_prefix_are_exactly_the_id_less_ones(
    every_tool_schema,
):
    """The one list a reader has to trust, checked against the live schema."""
    with_prefix = {
        name
        for name, tool in every_tool_schema.items()
        if "prefix" in tool.inputSchema.get("properties", {})
    }

    assert with_prefix == ID_LESS


def test_every_routed_tool_actually_calls_the_resolver():
    """The absence of `project` would also be satisfied by ignoring the store.

    Reading the source is crude, but it is the only check that distinguishes
    "routes by ID" from "silently uses whatever store it is standing in".
    """
    import projectman.server as server

    not_routing = sorted(
        name
        for name in ROUTED_BY_ID
        if "_store_for_id" not in inspect.getsource(getattr(server, name))
    )

    assert not_routing == []


def _tools_with_parameter(name: str) -> set:
    import projectman.server as server

    return {
        tool
        for tool in dir(server)
        if tool.startswith("pm_")
        and callable(getattr(server, tool))
        and name in inspect.signature(getattr(server, tool)).parameters
    }


def test_the_two_sets_do_not_overlap_and_cover_the_prefix_surface():
    assert ROUTED_BY_ID & ID_LESS == set()
    assert CREATE_VERBS <= ID_LESS
    assert _tools_with_parameter("prefix") == ID_LESS


def test_not_one_tool_function_still_takes_a_project_argument():
    """Belt and braces: the Python signatures, not just the wire schema.

    A tool hidden behind gating would be absent from ``tools/list`` and so
    invisible to the schema guard above; ``dir(server)`` sees it regardless.
    """
    assert _tools_with_parameter("project") == set()


# ═══ US-PM-34-4 — the ID-less verbs take an optional prefix ═════


#: One minimal, valid call per create verb, with the prefix left out.  These
#: are the calls that must be *refused* in a hub rather than defaulted.
CREATE_CALLS = {
    "pm_create_story": {
        "title": "A story",
        "description": "Story body text long enough to matter.",
    },
    "pm_create_sprint": {"name": "Sprint 1", "goal": "Ship it"},
    "pm_auto_scope": {},
}


class TestIdLessVerbsTakeAPrefix:
    """AC (US-PM-34-4): no ID to route by, so the prefix says which store."""

    def test_pm_status_with_no_prefix_reports_the_hub_store(self, hub):
        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())

        assert result["project"] == "test-hub"
        # The hub's own store is empty — the two seeded stories are elsewhere.
        assert result["stories"] == 0
        # And it still names its subprojects, which is the hub view US-PM-31-9
        # added and this change must not lose.
        assert sorted(row["name"] for row in result["subprojects"]) == ["api", "web"]

    @pytest.mark.parametrize("prefix,name", [("API", "api"), ("WEB", "web")])
    def test_pm_status_with_a_prefix_reports_that_subproject(self, hub, prefix, name):
        from projectman.server import pm_status

        result = yaml.safe_load(pm_status(prefix=prefix))

        assert result["project"] == name
        assert result["stories"] == 1
        # Naming a store is not the hub view, so the extra key stays off.
        assert "subprojects" not in result

    def test_the_prefix_is_case_insensitive(self, hub):
        from projectman.server import pm_status

        assert yaml.safe_load(pm_status(prefix="api"))["project"] == "api"

    def test_reads_route_to_the_named_store(self, hub):
        from projectman.server import pm_board, pm_active, pm_search

        board = yaml.safe_load(pm_board(prefix="WEB"))["board"]
        assert {t["id"] for t in board["available"]} == {"US-WEB-1-1", "US-WEB-1-2"}

        active = yaml.safe_load(pm_active(prefix="API"))
        assert [s["id"] for s in active["active_stories"]] == ["US-API-1"]

        found = yaml.safe_load(pm_search("story", prefix="WEB"))
        assert any(hit["id"] == "US-WEB-1" for hit in found)

    def test_reads_with_no_prefix_answer_from_the_hub_rather_than_erroring(self, hub):
        """An omitted prefix is a *default* for reads, never a refusal."""
        from projectman.server import (
            pm_active,
            pm_board,
            pm_context,
            pm_docs,
            pm_list_sprints,
            pm_next,
            pm_reindex,
        )

        assert yaml.safe_load(pm_board())["board"]["available"] == []
        assert yaml.safe_load(pm_active())["active_stories"] == []
        assert yaml.safe_load(pm_list_sprints())["count"] == 0
        assert yaml.safe_load(pm_next())["note"] is None
        assert "project_docs" in yaml.safe_load(pm_context())
        assert yaml.safe_load(pm_docs()) is not None
        assert "reindexed" in pm_reindex()

    @pytest.mark.parametrize("verb", sorted(CREATE_CALLS))
    def test_a_create_without_a_prefix_is_a_coded_invalid_error(self, hub, verb):
        is_error, text = _call_over_the_wire(verb, CREATE_CALLS[verb])

        assert is_error is True, text
        assert "[code: invalid]" in text
        assert "prefix" in text
        # The error is useful: it says which prefixes it would have accepted.
        assert "API" in text and "WEB" in text

    def test_a_refused_create_wrote_nothing_anywhere(self, hub):
        _call_over_the_wire("pm_create_story", CREATE_CALLS["pm_create_story"])

        for name, prefix in (("api", "API"), ("web", "WEB")):
            ids = {s.id for s in _on_disk(hub, name).list_stories()}
            assert ids == {f"US-{prefix}-1"}

    def test_a_create_with_a_prefix_lands_in_that_store(self, hub):
        from projectman.server import pm_create_story

        created = yaml.safe_load(
            pm_create_story(
                "Second WEB story",
                "Story body text long enough to matter.",
                prefix="WEB",
            )
        )["created"]

        assert created["id"] == "US-WEB-2"
        assert _on_disk(hub, "web").get("US-WEB-2")[0].title == "Second WEB story"
        assert {s.id for s in _on_disk(hub, "api").list_stories()} == {"US-API-1"}

    @pytest.mark.parametrize(
        "tool,arguments",
        [
            ("pm_status", {"prefix": "NOPE"}),
            ("pm_board", {"prefix": "NOPE"}),
            ("pm_create_story", dict(CREATE_CALLS["pm_create_story"], prefix="NOPE")),
        ],
    )
    def test_an_unknown_prefix_is_the_same_coded_not_found_as_in_an_id(
        self, hub, tool, arguments
    ):
        is_error, text = _call_over_the_wire(tool, arguments)

        assert is_error is True, text
        assert "[code: not_found]" in text
        assert "NOPE" in text
        assert "API, HUB, WEB" in text

    def test_an_unattached_prefix_is_a_not_found_carrying_the_attach_hint(
        self, tmp_hub, monkeypatch
    ):
        make_hub_subproject(tmp_hub, "cold", "COLD", attached=False)
        monkeypatch.chdir(tmp_hub)
        _reset_caches()
        try:
            is_error, text = _call_over_the_wire("pm_status", {"prefix": "COLD"})
        finally:
            _reset_caches()

        assert is_error is True, text
        assert "[code: not_found]" in text
        assert "COLD" in text and "cold" in text


# ═══ US-PM-34-5 — single-project mode never sees any of this ════


@pytest.fixture
def single(tmp_project, monkeypatch):
    """An ordinary, non-hub project (prefix TST) as the working directory."""
    monkeypatch.chdir(tmp_project)
    _reset_caches()
    yield tmp_project
    _reset_caches()


class TestSingleProjectModeIgnoresThePrefix:
    """AC (US-PM-34-5): outside a hub the parameter does nothing at all.

    The rest of the suite is the real pin — it drives these tools with no
    prefix and asserts the responses it always did.  What is left to state
    explicitly is the *new* argument's non-effect: a prefix passed here, right
    or wrong, must not change the answer and must never raise.
    """

    @pytest.mark.parametrize("prefix", [None, "TST", "NOPE", "api"])
    def test_pm_status_answers_identically_whatever_the_prefix(self, single, prefix):
        from projectman.server import pm_status

        assert pm_status(prefix=prefix) == pm_status()
        # And no hub view leaks into a single-project response.
        assert "subprojects" not in yaml.safe_load(pm_status(prefix=prefix))

    @pytest.mark.parametrize("prefix", [None, "TST", "NOPE"])
    def test_pm_board_answers_identically_whatever_the_prefix(self, single, prefix):
        from projectman.server import pm_board

        assert pm_board(prefix=prefix) == pm_board()

    def test_pm_create_story_needs_no_prefix_and_ignores_a_wrong_one(self, single):
        """The create refusal is a hub rule; here there is nothing to refuse."""
        from projectman.server import pm_create_story

        first = yaml.safe_load(
            pm_create_story("No prefix", "Story body text long enough to matter.")
        )["created"]
        second = yaml.safe_load(
            pm_create_story(
                "Wrong prefix",
                "Story body text long enough to matter.",
                prefix="NOPE",
            )
        )["created"]

        # Both landed in the one store, numbered in sequence under its prefix.
        assert [first["id"], second["id"]] == ["US-TST-1", "US-TST-2"]
        store = Store(single)
        assert {s.id for s in store.list_stories()} == {"US-TST-1", "US-TST-2"}
