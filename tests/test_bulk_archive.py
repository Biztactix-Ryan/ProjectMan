"""`pm_archive_many` — one declared call for a multi-item archive (US-PM-12-7).

The story's measurement: `pm_archive` is single-item only, so the model fires
it in long uniform bursts — 266 of 269 calls sat inside a run of three or more,
longest run 114 — and three of those calls were *denied mid-sweep* by Claude
Code's permission classifier, because a long tail of identical destructive
single-item calls reads as runaway behaviour.  This is the one place the missing
bulk verb causes a correctness failure rather than only cost.

Shape decision, recorded here because the DoD asked for it: a **new tool**,
`pm_archive_many(ids=...)`, rather than an `ids=` form bolted onto `pm_archive`.
`pm_archive` already carries an `id`/`task_id` alias pair that `_resolve_id`
enforces as one operand; adding a third, plural spelling to the same signature
would mean three ID-ish parameters whose combinations all need defining, and it
would hide a many-item destructive write behind a tool whose name and
annotations say one item.  A separate name is also the half that matters to the
permission classifier: the declared bulk intent is visible in the tool name
itself.  It matches `pm_update_many` (US-PM-12-6), which is the surface
US-PM-12-8 builds partial-failure semantics on.

Everything below is asserted through the real tools, and the two safety rules a
bulk destructive verb lives by are asserted directly: a malformed *call* is
rejected before anything is written, while a failing *item* never stops the ones
after it and is named in the response.
"""

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


@pytest.fixture
def tasks(tmp_project) -> list[str]:
    """A story with four tasks, created through the tools."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": f"Task {i}", "description": READY_BODY, "points": 1}
            for i in range(1, 5)
        ],
    )
    return [f"US-TST-1-{i}" for i in range(1, 5)]


def _fresh_store(tmp_project) -> Store:
    """A Store reading straight from disk, so nothing is answered from cache."""
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _meta(tmp_project, item_id: str):
    meta, _ = _fresh_store(tmp_project).get(item_id)
    return meta


def _is_archived(tmp_project, item_id: str) -> bool:
    meta = _meta(tmp_project, item_id)
    return bool(getattr(meta, "archived", False)) or meta.status.value == "archived"


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


def _item_files(tmp_project) -> dict:
    """Every epic/story/task file on disk, by name, as raw text.

    Item files only: the index and the activity log are rewritten by design,
    so comparing them would say nothing about what was *archived*.
    """
    project_dir = tmp_project / ".project"
    return {
        path.name: path.read_text()
        for sub in ("epics", "stories", "tasks")
        for path in sorted((project_dir / sub).glob("*.md"))
    }


def _tool_schemas() -> dict:
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ─── the explicit ID list ────────────────────────────────────────


class TestExplicitIdList:
    def test_one_call_archives_every_id_in_the_list(self, tmp_project, tasks):
        """AC 2: bulk archive accepts an explicit ID list."""
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids=",".join(tasks)))

        assert result["count"] == 4
        for task_id in tasks:
            assert _is_archived(tmp_project, task_id), task_id

    def test_the_list_tolerates_whitespace_and_a_trailing_comma(
        self, tmp_project, tasks
    ):
        """The spelling a model actually produces is still one call."""
        from projectman.server import pm_archive_many

        result = yaml.safe_load(
            pm_archive_many(ids=f" {tasks[0]} , {tasks[1]} , ")
        )

        assert result["count"] == 2
        assert _is_archived(tmp_project, tasks[0])
        assert _is_archived(tmp_project, tasks[1])
        # ...and nothing outside the list was touched.
        assert not _is_archived(tmp_project, tasks[2])

    def test_a_single_id_is_a_valid_list(self, tmp_project, tasks):
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids=tasks[0]))

        assert result["count"] == 1
        assert _is_archived(tmp_project, tasks[0])

    def test_epics_stories_and_tasks_may_be_mixed_in_one_list(self, tmp_project, tasks):
        """The ID list is not typed — the sweep a real cleanup performs."""
        from projectman.server import pm_archive_many, pm_create_epic

        pm_create_epic("Epic", "Epic body text long enough to matter.")

        result = yaml.safe_load(
            pm_archive_many(ids=f"EPIC-TST-1,US-TST-1,{tasks[0]}")
        )

        assert result["count"] == 3
        assert _meta(tmp_project, "EPIC-TST-1").status.value == "archived"
        assert _meta(tmp_project, "US-TST-1").status.value == "archived"
        assert _meta(tmp_project, tasks[0]).archived is True

    def test_only_the_listed_ids_are_archived_whatever_their_status_or_tags(
        self, tmp_project, tasks
    ):
        """The safety property: the list is a *selector*, not a starting point.

        AC 2 is only worth having if the explicit list is also exhaustive —
        an ID list must never widen into a sweep over neighbours that happen
        to share a status or a tag.  So the project is stocked with items in
        assorted statuses and tags, two IDs are named, and every other item
        file on disk is required to come back byte-identical.
        """
        from projectman.server import pm_archive_many, pm_create_epic, pm_update

        pm_create_epic("Epic", "Epic body text long enough to matter.")
        pm_update(tasks[0], status="done", tags="cleanup")
        pm_update(tasks[1], status="blocked", tags="cleanup")
        pm_update(tasks[2], tags="keep")
        pm_update(tasks[3], status="in-progress", tags="cleanup")

        listed = [tasks[0], tasks[2]]
        before = _item_files(tmp_project)
        assert len(before) >= 6, sorted(before)

        result = yaml.safe_load(pm_archive_many(ids=",".join(listed)))

        assert result["count"] == 2
        assert sorted(item["id"] for item in result["archived"]) == sorted(listed)
        # The two named items are archived...
        for item_id in listed:
            assert _is_archived(tmp_project, item_id), item_id
        # ...and every other item — including the tasks sharing the "cleanup"
        # tag and the done/blocked statuses a sweep would have caught — is
        # untouched, not merely un-archived.
        after = _item_files(tmp_project)
        assert set(after) == set(before)
        for name, text in before.items():
            if name in {f"{item_id}.md" for item_id in listed}:
                assert after[name] != text, name
            else:
                assert after[name] == text, f"{name} was rewritten"
        for untouched in (tasks[1], tasks[3], "US-TST-1", "EPIC-TST-1"):
            assert not _is_archived(tmp_project, untouched), untouched



# ─── per-item results ────────────────────────────────────────────


class TestPerItemResultsAreReportable:
    def test_every_archived_item_gets_its_own_entry(self, tmp_project, tasks):
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids=",".join(tasks[:3])))

        assert [entry["id"] for entry in result["archived"]] == tasks[:3]
        for entry in result["archived"]:
            assert entry["archived"] is True
            assert "status" in entry

    def test_a_task_entry_reports_the_status_the_work_really_reached(
        self, tmp_project, tasks
    ):
        """Archiving a task sets a flag; it does not rewrite history as `done`.

        The per-item entry has to say what actually happened, or the bulk verb
        becomes a way to silently mark abandoned work complete.
        """
        from projectman.server import pm_archive_many, pm_update

        pm_update(tasks[0], status="blocked")

        result = yaml.safe_load(pm_archive_many(ids=tasks[0]))

        assert result["archived"][0]["status"] == "blocked"
        assert result["archived"][0]["archived"] is True
        assert _meta(tmp_project, tasks[0]).status.value == "blocked"

    def test_a_story_entry_reports_the_archived_status(self, tmp_project, tasks):
        """Stories do have a real archived status — and the entry says so."""
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids="US-TST-1"))

        assert result["archived"][0]["status"] == "archived"

    def test_a_clean_sweep_carries_no_partial_failure_fields(self, tmp_project, tasks):
        """Absence is the signal: no `failed` key means nothing failed."""
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids=",".join(tasks[:2])))

        assert "failed" not in result
        assert "failed_count" not in result
        assert "partial" not in result


# ─── partial failure ─────────────────────────────────────────────


class TestPartialFailureIsReportable:
    def test_a_bad_id_does_not_stop_the_items_after_it(self, tmp_project, tasks):
        """AC 3, on the archive half: which IDs succeeded and which did not."""
        from projectman.server import pm_archive_many

        result = yaml.safe_load(
            pm_archive_many(ids=f"{tasks[0]},US-TST-1-99,{tasks[1]}")
        )

        assert result["partial"] is True
        assert result["count"] == 2
        assert result["succeeded"] == [tasks[0], tasks[1]]
        assert result["failed_count"] == 1
        assert result["failed"][0]["id"] == "US-TST-1-99"
        assert result["failed"][0]["error"]
        # The item after the failure really was written.
        assert _is_archived(tmp_project, tasks[1])

    def test_succeeded_and_failed_together_account_for_the_whole_list(
        self, tmp_project, tasks
    ):
        """Nothing may go missing: the caller can reconcile the list it sent."""
        from projectman.server import pm_archive_many

        sent = [tasks[0], "US-TST-1-98", tasks[1], "US-TST-1-99"]
        result = yaml.safe_load(pm_archive_many(ids=",".join(sent)))

        reported = result["succeeded"] + [f["id"] for f in result["failed"]]
        assert sorted(reported) == sorted(sent)

    def test_an_all_failed_sweep_still_reports_per_item(self, tmp_project, tasks):
        from projectman.server import pm_archive_many

        result = yaml.safe_load(pm_archive_many(ids="US-TST-1-98,US-TST-1-99"))

        assert result["count"] == 0
        assert result["archived"] == []
        assert result["succeeded"] == []
        assert result["failed_count"] == 2
        assert result["partial"] is True

    def test_the_shape_matches_pm_update_many(self, tmp_project, tasks):
        """US-PM-12-8 builds on one surface, so both verbs report the same keys."""
        from projectman.server import pm_archive_many, pm_update_many

        updated = yaml.safe_load(
            pm_update_many(ids=f"{tasks[0]},US-TST-1-99", status="review")
        )
        archived = yaml.safe_load(
            pm_archive_many(ids=f"{tasks[1]},US-TST-1-99")
        )

        shared = {"count", "failed", "failed_count", "succeeded", "partial"}
        assert shared <= set(updated)
        assert shared <= set(archived)
        assert set(updated["failed"][0]) == set(archived["failed"][0]) == {"id", "error"}


# ─── malformed calls ─────────────────────────────────────────────


class TestMalformedCallsAreRejectedBeforeAnyWrite:
    def test_no_ids_at_all_is_an_error_not_a_silent_no_op(self, tmp_project):
        """A destructive verb never guesses. No list means no call, not 'all'."""
        from projectman.server import pm_archive_many

        with pytest.raises(ToolError) as excinfo:
            pm_archive_many()

        assert "ids" in str(excinfo.value)

    @pytest.mark.parametrize("blank", ["", "   ", ",", " , , "])
    def test_a_blank_or_empty_list_is_an_error(self, tmp_project, blank):
        from projectman.server import pm_archive_many

        with pytest.raises(ToolError):
            pm_archive_many(ids=blank)

    def test_nothing_is_written_when_the_call_is_rejected(self, tmp_project, tasks):
        """The rule that makes a bulk destructive verb safe to hand a model.

        A duplicate ID is a whole-call mistake — the caller's list is not the
        list it thinks it is — so it is caught before the first write, and the
        valid IDs alongside it are left alone.
        """
        from projectman.server import pm_archive_many

        with pytest.raises(ToolError) as excinfo:
            pm_archive_many(ids=f"{tasks[0]},{tasks[1]},{tasks[0]}")

        assert "duplicate" in str(excinfo.value)
        assert tasks[0] in str(excinfo.value)
        assert not _is_archived(tmp_project, tasks[0])
        assert not _is_archived(tmp_project, tasks[1])

    def test_a_list_over_the_limit_is_rejected_whole(self, tmp_project, tasks):
        from projectman.server import BULK_ARCHIVE_LIMIT, pm_archive_many

        oversized = ",".join(f"US-TST-1-{i}" for i in range(1, BULK_ARCHIVE_LIMIT + 2))

        with pytest.raises(ToolError) as excinfo:
            pm_archive_many(ids=oversized)

        assert str(BULK_ARCHIVE_LIMIT) in str(excinfo.value)
        assert not _is_archived(tmp_project, tasks[0])

    def test_the_limit_is_above_the_longest_measured_run(self):
        """114 consecutive pm_archive calls were observed; one call must hold them."""
        from projectman.server import BULK_ARCHIVE_LIMIT

        assert BULK_ARCHIVE_LIMIT >= 114


# ─── parity with pm_archive ──────────────────────────────────────


class TestParityWithPmArchive:
    def test_a_one_item_bulk_archive_leaves_the_same_state_as_pm_archive(
        self, tmp_project, tasks
    ):
        """The bulk verb is the same write, not a second implementation."""
        from projectman.server import pm_archive, pm_archive_many

        pm_archive(tasks[0])
        pm_archive_many(ids=tasks[1])

        one = _meta(tmp_project, tasks[0])
        many = _meta(tmp_project, tasks[1])
        assert one.archived == many.archived is True
        assert one.status.value == many.status.value

    def test_pm_archive_still_returns_its_original_body(self, tmp_project, tasks):
        """The single-item verb's contract is untouched by the extraction."""
        from projectman.server import pm_archive

        assert pm_archive(tasks[0]) == f"archived: {tasks[0]}"

    def test_the_index_is_written_once_for_the_whole_sweep(self, tmp_project, tasks):
        """Per-sweep, not per-item — and the index really does reflect the writes."""
        import projectman.server as server

        calls = []
        original = server.write_index

        def counting(store, *args, **kwargs):
            calls.append(store)
            return original(store, *args, **kwargs)

        server.write_index = counting
        try:
            server.pm_archive_many(ids=",".join(tasks[:3]))
        finally:
            server.write_index = original

        assert len(calls) == 1

    def test_an_all_failed_sweep_writes_no_index(self, tmp_project, tasks):
        import projectman.server as server

        calls = []
        original = server.write_index

        def counting(store, *args, **kwargs):
            calls.append(store)
            return original(store, *args, **kwargs)

        server.write_index = counting
        try:
            server.pm_archive_many(ids="US-TST-1-98,US-TST-1-99")
        finally:
            server.write_index = original

        assert calls == []


# ─── registration ────────────────────────────────────────────────


class TestRegistration:
    def test_the_tool_is_registered_with_an_ids_parameter(self):
        tools = _tool_schemas()

        assert "pm_archive_many" in tools
        schema = tools["pm_archive_many"].inputSchema
        assert "ids" in schema.get("properties", {})
        # The list is validated in the body so the error can say what to do,
        # rather than being a bare schema rejection.
        assert schema.get("required", []) == []

    def test_ids_is_the_only_selector_the_schema_offers(self):
        """A reviewer reading the schema must see one way to choose items.

        `project` scopes *which store* is written in hub mode; it selects no
        items.  Anything else in `properties` would be a second way to decide
        what gets archived — a criteria/status/tag/all form arriving by the
        back door — which is exactly what the docstring promises does not
        exist, so the promise is pinned against the schema itself.
        """
        properties = _tool_schemas()["pm_archive_many"].inputSchema.get(
            "properties", {}
        )

        assert set(properties) == {"ids", "project"}
        assert properties["ids"]["title"] == "Ids"

    def test_it_is_annotated_as_destructive(self):
        """The classifier reads annotations; a bulk archive is still destructive."""
        tools = _tool_schemas()
        annotations = tools["pm_archive_many"].annotations

        assert annotations.destructiveHint is True
        assert annotations.readOnlyHint is False

    def test_the_docstring_points_at_the_single_item_verb_and_the_sibling(self):
        from projectman.server import pm_archive, pm_archive_many

        doc = pm_archive_many.__doc__
        assert "pm_archive" in doc
        assert "pm_update_many" in doc
        # ...and the single-item verb points back, so the model reading it
        # while starting a sweep is told there is a one-call form.
        assert "pm_archive_many" in pm_archive.__doc__

    def test_the_explicit_list_is_documented_as_the_only_input(self):
        """It must not be mistakable for a criteria sweep."""
        doc = _tool_schemas()["pm_archive_many"].description or ""

        assert "explicit ID list" in doc
        assert "no criteria or sweep form" in doc

    def test_a_real_tools_call_performs_the_sweep(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_archive_many", {"ids": ",".join(tasks[:2])}
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 2
        assert _is_archived(tmp_project, tasks[0])
        assert _is_archived(tmp_project, tasks[1])

    def test_a_malformed_call_sets_is_error_rather_than_returning_an_error_body(
        self, tmp_project
    ):
        """US-PM-2's convention: failures raise, they never become `error:` text."""
        is_error, body = _call_over_the_wire("pm_archive_many", {})

        assert is_error is True
        assert not body.lstrip().startswith("error:")

    def test_a_partial_failure_is_not_a_failed_call(self, tmp_project, tasks):
        """Some items landed; the call did what it could and says so."""
        is_error, body = _call_over_the_wire(
            "pm_archive_many", {"ids": f"{tasks[0]},US-TST-1-99"}
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["partial"] is True
        assert data["succeeded"] == [tasks[0]]
        assert data["failed"][0]["id"] == "US-TST-1-99"
