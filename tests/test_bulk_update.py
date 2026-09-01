"""`pm_update_many` — one call for multi-item work (US-PM-12-6).

The story's measurement: `pm_update` is single-item only, so the model fires it
in long uniform bursts (longest observed run: 109 consecutive calls, 406 of 559
consecutive pairs targeting *different* IDs — genuine multi-item work, not retry
churn).  Four patterns recur, and each one is asserted here as a single call:
mark-done with run log, dependency wiring, estimation, bare status flip.

The shape follows `pm_create_tasks`, per the story: a batch argument beside the
single-item verb, not a new dialect.  Both halves are covered — a uniform patch
over a CSV ID list, and a list of per-item patches — plus the rule that makes a
bulk verb safe to hand a model: a malformed *call* is rejected before anything
is written, while a failing *item* never stops the ones after it and is named in
the response (the reportable per-item results US-PM-12-8 builds on).
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


def _status(tmp_project, item_id: str) -> str:
    meta, _ = _fresh_store(tmp_project).get(item_id)
    return meta.status.value


def _meta(tmp_project, item_id: str):
    meta, _ = _fresh_store(tmp_project).get(item_id)
    return meta


def _run_log(tmp_project, item_id: str) -> list:
    return _fresh_store(tmp_project).get_run_log(item_id)


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


def _tool_schemas() -> dict:
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ─── the two shapes ──────────────────────────────────────────────


class TestUniformPatch:
    """AC 1, first half: one patch, a CSV ID list."""

    def test_one_call_flips_every_listed_id(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(ids=",".join(tasks), status="review"))

        assert data["count"] == 4
        assert [e["id"] for e in data["updated"]] == tasks
        assert all(e["status"] == "review" for e in data["updated"])
        for task_id in tasks:
            assert _status(tmp_project, task_id) == "review"

    def test_whitespace_and_empties_in_the_id_list_are_tolerated(
        self, tmp_project, tasks
    ):
        """Same parsing as every other CSV argument on the surface."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(ids=f" {tasks[0]} , ,{tasks[1]}, ", status="blocked")
        )

        assert data["count"] == 2
        assert _status(tmp_project, tasks[0]) == "blocked"
        assert _status(tmp_project, tasks[1]) == "blocked"

    def test_epics_stories_and_tasks_can_be_mixed_in_one_list(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(ids=f"US-TST-1,{tasks[0]}", tags="sweep"))

        assert data["count"] == 2
        assert _meta(tmp_project, "US-TST-1").tags == ["sweep"]
        assert _meta(tmp_project, tasks[0]).tags == ["sweep"]


class TestPerItemPatches:
    """AC 1, second half: heterogeneous work in one call."""

    def test_each_entry_gets_its_own_patch(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": tasks[0], "points": 3},
                    {"id": tasks[1], "points": 5, "status": "blocked"},
                ]
            )
        )

        assert data["count"] == 2
        assert _meta(tmp_project, tasks[0]).points == 3
        assert _meta(tmp_project, tasks[1]).points == 5
        assert _status(tmp_project, tasks[1]) == "blocked"
        # The untouched one stays untouched.
        assert _meta(tmp_project, tasks[0]).status.value == "todo"

    def test_task_id_is_accepted_as_the_entry_id_spelling(self, tmp_project, tasks):
        """The same alias `pm_update` takes, per US-PM-3."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(updates=[{"task_id": tasks[0], "points": 8}]))

        assert data["updated"][0]["id"] == tasks[0]
        assert _meta(tmp_project, tasks[0]).points == 8

    def test_top_level_fields_are_defaults_each_entry_may_override(
        self, tmp_project, tasks
    ):
        """One status flip, per-item notes — the combined shape."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": tasks[0], "note": "first one landed"},
                    {"id": tasks[1], "note": "second one landed"},
                    {"id": tasks[2], "status": "blocked", "note": "this one did not"},
                ],
                status="done",
                outcome="success",
            )
        )

        assert data["count"] == 3
        assert _status(tmp_project, tasks[0]) == "done"
        assert _status(tmp_project, tasks[1]) == "done"
        # The entry's own value wins over the call-level default.
        assert _status(tmp_project, tasks[2]) == "blocked"
        assert _run_log(tmp_project, tasks[0])[-1].note == "first one landed"
        assert _run_log(tmp_project, tasks[1])[-1].note == "second one landed"

    def test_ids_and_updates_may_be_combined_in_one_call(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                ids=f"{tasks[0]},{tasks[1]}",
                updates=[{"id": tasks[2], "points": 13}],
                status="review",
            )
        )

        assert data["count"] == 3
        assert [_status(tmp_project, t) for t in tasks[:3]] == ["review"] * 3
        assert _meta(tmp_project, tasks[2]).points == 13


# ─── AC 4 — the four measured bulk patterns, one call each ───────


class TestTheFourMeasuredPatterns:
    """Each of the four patterns the telemetry found, as a single call."""

    def test_mark_done_with_run_log(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                ids=",".join(tasks),
                status="done",
                outcome="success",
                note="swept in one call",
            )
        )

        assert data["count"] == 4
        for task_id in tasks:
            assert _status(tmp_project, task_id) == "done"
            entry = _run_log(tmp_project, task_id)[-1]
            assert entry.outcome == "success"
            assert entry.note == "swept in one call"
        assert all(e["run_log"] == "success" for e in data["updated"])

    def test_dependency_wiring(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": tasks[1], "depends_on": tasks[0]},
                    {"id": tasks[2], "depends_on": f"{tasks[0]},{tasks[1]}"},
                    {"id": tasks[3], "depends_on": tasks[2]},
                ]
            )
        )

        assert data["count"] == 3
        assert _meta(tmp_project, tasks[1]).depends_on == [tasks[0]]
        assert _meta(tmp_project, tasks[2]).depends_on == [tasks[0], tasks[1]]
        assert _meta(tmp_project, tasks[3]).depends_on == [tasks[2]]
        # The parse is echoed back, so the caller sees how it was read.
        assert data["updated"][1]["depends_on"] == [tasks[0], tasks[1]]

    def test_estimation(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": tasks[0], "points": 1},
                    {"id": tasks[1], "points": 2},
                    {"id": tasks[2], "points": 3},
                    {"id": tasks[3], "points": 5},
                ]
            )
        )

        assert data["count"] == 4
        assert [_meta(tmp_project, t).points for t in tasks] == [1, 2, 3, 5]

    def test_bare_status_flip(self, tmp_project, tasks):
        """No outcome, no note — and therefore no run-log entry, as on pm_update."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(ids=",".join(tasks), status="done"))

        assert data["count"] == 4
        assert all(_status(tmp_project, t) == "done" for t in tasks)
        assert all("run_log" not in e for e in data["updated"])
        assert all(_run_log(tmp_project, t) == [] for t in tasks)

    # The same four patterns over a real ``tools/call``, so the shapes are known
    # to survive JSON transport and not only the in-process Python signature.
    # The heterogeneous two matter most: `updates` is a list of objects, which
    # is the part a transport can mangle.

    def test_dependency_wiring_over_the_wire(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_update_many",
            {
                "updates": [
                    {"id": tasks[1], "depends_on": tasks[0]},
                    {"id": tasks[2], "depends_on": f"{tasks[0]},{tasks[1]}"},
                    {"id": tasks[3], "depends_on": tasks[2]},
                ]
            },
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 3
        # A different dependency set per task — no uniform patch expresses this.
        assert _meta(tmp_project, tasks[1]).depends_on == [tasks[0]]
        assert _meta(tmp_project, tasks[2]).depends_on == [tasks[0], tasks[1]]
        assert _meta(tmp_project, tasks[3]).depends_on == [tasks[2]]

    def test_estimation_over_the_wire(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_update_many",
            {
                "updates": [
                    {"id": tasks[0], "points": 1},
                    {"id": tasks[1], "points": 2},
                    {"id": tasks[2], "points": 3},
                    {"id": tasks[3], "points": 5},
                ]
            },
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 4
        assert [_meta(tmp_project, t).points for t in tasks] == [1, 2, 3, 5]

    def test_mark_done_with_run_log_over_the_wire(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_update_many",
            {
                "ids": ",".join(tasks),
                "status": "done",
                "outcome": "success",
                "note": "swept over the wire",
            },
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 4
        # Every item ends done *and* carries the run-log entry.
        for task_id in tasks:
            assert _status(tmp_project, task_id) == "done"
            entry = _run_log(tmp_project, task_id)[-1]
            assert entry.outcome == "success"
            assert entry.note == "swept over the wire"

    def test_bare_status_flip_over_the_wire(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_update_many", {"ids": ",".join(tasks), "status": "done"}
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 4
        assert all(_status(tmp_project, t) == "done" for t in tasks)
        # No outcome, no note, therefore no run-log entry anywhere.
        assert all(_run_log(tmp_project, t) == [] for t in tasks)


# ─── per-item results, and the failures that stop the call ───────


class TestPartialFailureIsReportable:
    """AC 3's foundation: which IDs landed, which did not, in the response."""

    def test_a_missing_id_does_not_stop_the_rest(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                ids=f"{tasks[0]},US-TST-1-99,{tasks[1]}", status="review"
            )
        )

        assert data["count"] == 2
        assert data["succeeded"] == [tasks[0], tasks[1]]
        assert data["failed_count"] == 1
        assert data["failed"][0]["id"] == "US-TST-1-99"
        assert data["failed"][0]["error"]
        assert data["partial"] is True
        assert _status(tmp_project, tasks[0]) == "review"
        assert _status(tmp_project, tasks[1]) == "review"

    def test_an_all_success_call_carries_no_failure_keys(self, tmp_project, tasks):
        """Absence means "nothing failed" — the caller branches on presence."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(ids=tasks[0], status="review"))

        for key in ("failed", "failed_count", "succeeded", "partial"):
            assert key not in data, key

    def test_every_item_can_fail_without_the_call_failing(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        data = yaml.safe_load(pm_update_many(ids="US-TST-9-9,US-TST-9-8", status="done"))

        assert data["count"] == 0
        assert data["updated"] == []
        assert [f["id"] for f in data["failed"]] == ["US-TST-9-9", "US-TST-9-8"]

    def test_per_item_extras_ride_with_their_item(self, tmp_project, tasks):
        """A truncated note is reported against the item it belongs to."""
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": tasks[0], "note": "short one", "outcome": "info"},
                    {"id": tasks[1], "note": "x" * 5000, "outcome": "info"},
                ]
            )
        )

        first, second = data["updated"]
        assert "note_truncated" not in first
        assert second["note_truncated"] is True
        assert second["note_dropped_chars"] > 0


class TestMalformedCallsAreRejectedBeforeAnyWrite:
    """A half-applied sweep is worse than none: the caller cannot tell what landed."""

    def test_an_unknown_field_in_an_entry_is_a_whole_call_error(
        self, tmp_project, tasks
    ):
        from projectman.server import pm_update_many

        with pytest.raises(ToolError) as excinfo:
            pm_update_many(
                updates=[
                    {"id": tasks[0], "status": "done"},
                    {"id": tasks[1], "stauts": "done"},
                ]
            )

        assert "stauts" in str(excinfo.value)
        # ...and the valid names are named, so the caller can fix it.
        assert "status" in str(excinfo.value)
        # Nothing was written — not even the well-formed first entry.
        assert _status(tmp_project, tasks[0]) == "todo"

    def test_an_entry_without_an_id_is_a_whole_call_error(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        with pytest.raises(ToolError) as excinfo:
            pm_update_many(updates=[{"id": tasks[0], "status": "done"}, {"points": 3}])

        assert "id" in str(excinfo.value)
        assert _status(tmp_project, tasks[0]) == "todo"

    def test_an_entry_with_nothing_to_change_is_an_error(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        with pytest.raises(ToolError):
            pm_update_many(updates=[{"id": tasks[0]}])

    def test_ids_with_no_patch_field_is_an_error(self, tmp_project, tasks):
        """Otherwise it is a silent no-op sweep over real items."""
        from projectman.server import pm_update_many

        with pytest.raises(ToolError) as excinfo:
            pm_update_many(ids=",".join(tasks))

        assert "nothing to change" in str(excinfo.value)

    def test_no_items_at_all_is_an_error(self, tmp_project):
        from projectman.server import pm_update_many

        with pytest.raises(ToolError):
            pm_update_many(status="done")

    def test_updates_must_be_a_list_of_objects(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        with pytest.raises(ToolError):
            pm_update_many(updates=[tasks[0], tasks[1]])

    def test_a_sweep_beyond_the_limit_is_refused(self, tmp_project, tasks):
        from projectman.server import BULK_UPDATE_LIMIT, pm_update_many

        oversized = ",".join(f"US-TST-1-{i}" for i in range(BULK_UPDATE_LIMIT + 1))

        with pytest.raises(ToolError) as excinfo:
            pm_update_many(ids=oversized, status="done")

        assert str(BULK_UPDATE_LIMIT) in str(excinfo.value)


# ─── parity with the single-item verb ────────────────────────────


class TestParityWithPmUpdate:
    """Same code path, so the bulk verb cannot drift from the single one."""

    def test_the_conflicting_unassign_rule_still_holds_per_item(
        self, tmp_project, tasks
    ):
        from projectman.server import pm_update_many

        data = yaml.safe_load(
            pm_update_many(updates=[{"id": tasks[0], "unassign": True, "assignee": "sam"}])
        )

        assert data["count"] == 0
        assert "conflicting instruction" in data["failed"][0]["error"]

    def test_clear_works_through_the_bulk_verb(self, tmp_project, tasks):
        from projectman.server import pm_update, pm_update_many

        pm_update(tasks[0], tags="a,b")
        pm_update(tasks[1], tags="a,b")

        yaml.safe_load(pm_update_many(ids=f"{tasks[0]},{tasks[1]}", clear="tags"))

        assert _meta(tmp_project, tasks[0]).tags == []
        assert _meta(tmp_project, tasks[1]).tags == []

    def test_assignment_and_unassignment_sweep(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        pm_update_many(ids=",".join(tasks), assignee="claude")
        assert all(_meta(tmp_project, t).assignee == "claude" for t in tasks)

        pm_update_many(ids=",".join(tasks), unassign=True)
        assert all(_meta(tmp_project, t).assignee is None for t in tasks)

    def test_the_index_is_written_for_the_whole_sweep(self, tmp_project, tasks):
        """One index write at the end, but the index must still be current."""
        from projectman.server import pm_update_many

        pm_update_many(ids=",".join(tasks), status="done")

        index = yaml.safe_load((tmp_project / ".project" / "index.yaml").read_text())
        indexed = {e["id"]: e["status"] for e in index["entries"]}
        assert [indexed[t] for t in tasks] == ["done"] * 4

    def test_a_status_change_still_emits_its_activity_entry(self, tmp_project, tasks):
        from projectman.server import pm_update_many

        pm_update_many(ids=f"{tasks[0]},{tasks[1]}", status="done")

        log = (tmp_project / ".project" / "activity.jsonl")
        assert log.exists()
        text = log.read_text()
        assert tasks[0] in text and tasks[1] in text


# ─── the surface the model reads ─────────────────────────────────


class TestRegistration:
    def test_the_tool_is_registered_with_both_shapes_in_its_schema(self):
        tools = _tool_schemas()

        assert "pm_update_many" in tools
        schema = tools["pm_update_many"].inputSchema
        properties = schema.get("properties", {})
        assert "ids" in properties
        assert "updates" in properties
        # Neither shape is mandatory — the tool takes one or the other.
        assert schema.get("required", []) == []

    def test_the_docstring_points_at_the_single_item_verb_and_the_batch_shape(self):
        from projectman.server import pm_update_many

        doc = pm_update_many.__doc__
        assert "pm_update" in doc
        assert "pm_create_tasks" in doc

    def test_a_real_tools_call_performs_the_sweep(self, tmp_project, tasks):
        is_error, body = _call_over_the_wire(
            "pm_update_many",
            {"ids": ",".join(tasks[:2]), "status": "done", "outcome": "success", "note": "wire"},
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 2
        assert _status(tmp_project, tasks[0]) == "done"

    def test_a_real_tools_call_carries_per_item_patches(self, tmp_project, tasks):
        """AC 1's other half over the wire: `updates` survives JSON transport."""
        is_error, body = _call_over_the_wire(
            "pm_update_many",
            {
                "ids": tasks[0],
                "updates": [
                    {"id": tasks[1], "points": 3},
                    {"id": tasks[2], "points": 5, "status": "blocked"},
                ],
                "status": "review",
            },
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["count"] == 3
        # The uniform half of the same call.
        assert _status(tmp_project, tasks[0]) == "review"
        # Per-item values no uniform patch could express.
        assert _meta(tmp_project, tasks[1]).points == 3
        assert _status(tmp_project, tasks[1]) == "review"
        assert _meta(tmp_project, tasks[2]).points == 5
        # The entry's own status wins over the call-level default.
        assert _status(tmp_project, tasks[2]) == "blocked"

    def test_a_malformed_call_sets_is_error_rather_than_returning_an_error_body(
        self, tmp_project
    ):
        """US-PM-2's convention: failures raise, they never become `error:` text."""
        is_error, body = _call_over_the_wire("pm_update_many", {})

        assert is_error is True
        assert not body.lstrip().startswith("error:")

    def test_a_partial_failure_is_not_a_failed_call(self, tmp_project, tasks):
        """Some items landed; the call did what it could and says so."""
        is_error, body = _call_over_the_wire(
            "pm_update_many", {"ids": f"{tasks[0]},US-TST-1-99", "status": "review"}
        )

        assert is_error is False, body
        data = yaml.safe_load(body)
        assert data["partial"] is True
        assert data["succeeded"] == [tasks[0]]
