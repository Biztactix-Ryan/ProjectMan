"""`pm_update` keeps its status-write contract, exactly (US-PM-8-8).

`docs/reference/verdict-verbs-contract.md` §4 is the binding statement:

    `pm_update(id, status=...)` keeps working **exactly** as today, including
    `status="done"` with no `outcome`/`note` and therefore no run-log entry.
    It is the generic escape hatch and the compat surface (US-PM-8-8); nothing
    about it is deprecated, warned on, or made stricter, and the verdict verbs
    are purely additive.

These tests are written *before* the verdict verbs land (US-PM-8-7) on purpose:
they are the guard rail that stops the new verbs tightening the old path by
accident.  Five consumer repos in the studies plus the web UI drive status
through this surface, so "still works" here means the same call, the same
optional arguments, and — crucially — the same *absence* of a run-log entry
when the caller gave no outcome.  A future change that starts requiring a note,
or that starts logging one on the caller's behalf, must fail here first.

Web/CLI note: the web API's `PATCH /api/tasks/{id}` reaches the same
`Store.update` contract (`src/projectman/web/routes/api.py`), covered by
`tests/web/test_tasks_board_docs.py::test_task_lifecycle` and
`tests/web/test_archived_metrics.py::test_archive_route_leaves_the_task_status_alone_on_disk`.  The Click CLI has no task-status write
of its own — `src/projectman/cli.py` is init/git/changeset commands only.
"""

import inspect

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import Store

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

# The task statuses pm_update's own docstring advertises.
TASK_STATUSES = ["todo", "in-progress", "review", "done", "blocked"]
# Story/epic lifecycle statuses.  `archived` is deliberately absent: archiving
# is its own operation (pm_archive) with its own tests, not a compat surface.
STORY_STATUSES = ["backlog", "ready", "active", "done"]
EPIC_STATUSES = ["draft", "active", "done"]


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def task(tmp_project) -> str:
    """A story with one task, created through the store, ready to update."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    store.create_task("US-TST-1", "Task 1", READY_BODY, points=1)
    return "US-TST-1-1"


def _fresh_store(tmp_project) -> Store:
    """A Store reading straight from disk, so nothing is answered from cache."""
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


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


# ─── §4 — status="done" with no outcome and no note ──────────────


class TestBareDoneWrite:
    """The exact call §4 names: done, nothing else, no run-log entry."""

    def test_done_with_no_outcome_or_note_succeeds(self, tmp_project, task):
        from projectman.server import pm_update

        data = yaml.safe_load(pm_update(task, status="done"))

        assert data["updated"]["id"] == task
        assert data["updated"]["status"] == "done"
        meta, _ = _fresh_store(tmp_project).get_task(task)
        assert meta.status.value == "done"

    def test_done_with_no_outcome_writes_no_run_log_entry(self, tmp_project, task):
        """The 13% hole the story measures stays *reachable* — by design.

        §4 keeps this behaviour: the verdict verbs move traffic off pm_update,
        they do not make pm_update log on the caller's behalf.
        """
        from projectman.server import pm_update

        pm_update(task, status="done")

        assert _run_log(tmp_project, task) == []

    def test_bare_done_response_carries_no_run_log_key(self, tmp_project, task):
        """`run_log:` in the response means an entry was appended.  None was."""
        from projectman.server import pm_update

        data = yaml.safe_load(pm_update(task, status="done"))

        assert "run_log" not in data["updated"]

    def test_bare_done_over_the_wire(self, tmp_project, task):
        """Not just the Python function — the real tools/call path too."""
        is_error, text = _call_over_the_wire(
            "pm_update", {"id": task, "status": "done"}
        )

        assert not is_error, text
        assert yaml.safe_load(text)["updated"]["status"] == "done"
        assert _run_log(tmp_project, task) == []


# ─── every advertised status, on every item type ─────────────────


class TestStatusWritesStillWork:
    @pytest.mark.parametrize("status", TASK_STATUSES)
    def test_task_status_write(self, tmp_project, task, status):
        from projectman.server import pm_update

        data = yaml.safe_load(pm_update(task, status=status))

        assert data["updated"]["status"] == status
        meta, _ = _fresh_store(tmp_project).get_task(task)
        assert meta.status.value == status

    @pytest.mark.parametrize("status", TASK_STATUSES)
    def test_task_status_write_alone_never_logs(self, tmp_project, task, status):
        from projectman.server import pm_update

        pm_update(task, status=status)

        assert _run_log(tmp_project, task) == []

    @pytest.mark.parametrize("status", STORY_STATUSES)
    def test_story_status_write(self, tmp_project, task, status):
        from projectman.server import pm_update

        data = yaml.safe_load(pm_update("US-TST-1", status=status))

        assert data["updated"]["status"] == status
        meta, _ = _fresh_store(tmp_project).get_story("US-TST-1")
        assert meta.status.value == status

    @pytest.mark.parametrize("status", EPIC_STATUSES)
    def test_epic_status_write(self, tmp_project, status):
        from projectman.server import pm_create_epic, pm_update

        epic_id = yaml.safe_load(pm_create_epic("Epic", "Epic body"))["created"]["id"]

        data = yaml.safe_load(pm_update(epic_id, status=status))

        assert data["updated"]["status"] == status
        meta, _ = _fresh_store(tmp_project).get_epic(epic_id)
        assert meta.status.value == status


# ─── outcome + note: still exactly one entry ─────────────────────


class TestOutcomeAndNoteStillLog:
    def test_outcome_and_note_appends_exactly_one_entry(self, tmp_project, task):
        from projectman.server import pm_update

        data = yaml.safe_load(
            pm_update(task, status="done", outcome="success", note="All green")
        )

        assert data["updated"]["run_log"] == "success"
        entries = _run_log(tmp_project, task)
        assert len(entries) == 1
        assert entries[0].outcome.value == "success"
        assert entries[0].note == "All green"
        assert entries[0].status == "done"

    def test_each_outcome_value_still_accepted(self, tmp_project, task):
        """All five outcomes, not just the two the studies see in the wild."""
        from projectman.server import pm_update

        for outcome in ("success", "partial", "blocked", "failed", "info"):
            pm_update(task, outcome=outcome, note=f"note for {outcome}")

        entries = _run_log(tmp_project, task)
        assert [e.outcome.value for e in entries] == [
            "info",
            "failed",
            "blocked",
            "partial",
            "success",
        ]

    def test_repeated_status_writes_do_not_accumulate_entries(self, tmp_project, task):
        from projectman.server import pm_update

        pm_update(task, status="in-progress")
        pm_update(task, status="review", outcome="partial", note="halfway")
        pm_update(task, status="done")

        assert len(_run_log(tmp_project, task)) == 1


# ─── the assignee="" unassign path ───────────────────────────────


class TestLegacyUnassignSentinel:
    def test_empty_assignee_still_unassigns(self, tmp_project, task):
        """The undocumented legacy sentinel keeps working (US-PM-7 kept it)."""
        from projectman.server import pm_update

        pm_update(task, assignee="claude", status="in-progress")

        data = yaml.safe_load(pm_update(task, assignee=""))

        assert data["updated"]["assignee"] is None
        meta, _ = _fresh_store(tmp_project).get_task(task)
        # Never a literal '' on disk: readiness.py tests `assignee is not None`.
        assert meta.assignee is None

    def test_empty_assignee_changes_nothing_else(self, tmp_project, task):
        from projectman.server import pm_update

        pm_update(task, assignee="claude", status="in-progress")
        pm_update(task, assignee="")

        meta, _ = _fresh_store(tmp_project).get_task(task)
        assert meta.status.value == "in-progress"
        assert _run_log(tmp_project, task) == []

    def test_empty_assignee_over_the_wire(self, tmp_project, task):
        from projectman.server import pm_update

        pm_update(task, assignee="claude", status="in-progress")

        is_error, text = _call_over_the_wire("pm_update", {"id": task, "assignee": ""})

        assert not is_error, text
        meta, _ = _fresh_store(tmp_project).get_task(task)
        assert meta.assignee is None


# ─── nothing about pm_update is deprecated or made stricter ──────


class TestNothingDeprecated:
    @pytest.mark.parametrize("param", ["status", "outcome", "note", "assignee"])
    def test_parameters_stay_optional(self, param):
        """`status` alone must remain a legal call: everything else defaults."""
        from projectman.server import pm_update

        assert inspect.signature(pm_update).parameters[param].default is None

    def test_status_stays_in_the_tool_schema(self):
        schema = _tool_schemas()["pm_update"].inputSchema
        assert "status" in schema["properties"]
        assert schema.get("required", []) == ["id"] or "status" not in schema.get(
            "required", []
        )

    @pytest.mark.parametrize("word", ["deprecat", "obsolete", "no longer"])
    def test_docstring_carries_no_deprecation_notice(self, word):
        """§4: nothing about pm_update is deprecated or warned on."""
        from projectman.server import pm_update

        assert word not in (inspect.getdoc(pm_update) or "").lower()


# ─── §4 — still true now the verdict verbs exist alongside ───────


class TestCompatAfterVerbs:
    """US-PM-8-4: the guard rails above, re-asserted against the *shipped*
    verbs rather than their absence.

    The tests earlier in this file were written before US-PM-8-7 landed, so
    they pinned pm_update in a server module where no verb was registered.
    These three close the remaining half of §4's "purely additive": the verbs
    are present, and pm_update is still the unchanged generic escape hatch —
    it still logs nothing on the caller's behalf, it can still move a task a
    verb moved, and when it *is* given an outcome and a note it writes the
    byte-identical run-log entry a verb writes.
    """

    VERBS = ["pm_accept", "pm_park", "pm_retry", "pm_review"]

    def _verb(self, name):
        import projectman.server as server

        return getattr(server, name)

    def test_bare_done_still_logs_nothing_with_the_verbs_registered(
        self, tmp_project, task
    ):
        """§4: the verbs are additive — their arrival did not make pm_update
        stricter, and the no-run-log hole stays deliberately reachable."""
        from projectman.server import pm_update

        registered = _tool_schemas()
        assert [v for v in self.VERBS if v in registered] == self.VERBS

        pm_update(task, status="done")

        assert _run_log(tmp_project, task) == []

    def test_pm_update_can_move_a_task_a_verb_moved(self, tmp_project, task):
        """A plain status write still owns any task, whatever put it there.

        pm_park sends the task to `review` with the assignee cleared; a bare
        pm_update must be able to send it straight back to `todo` without an
        outcome, a note, or an extra run-log entry.
        """
        from projectman.server import pm_update

        pm_update(task, assignee="claude", status="in-progress")
        self._verb("pm_park")(task, note="waiting on a human")
        assert _fresh_store(tmp_project).get_task(task)[0].status.value == "review"

        data = yaml.safe_load(pm_update(task, status="todo"))

        assert data["updated"]["status"] == "todo"
        meta, _ = _fresh_store(tmp_project).get_task(task)
        assert meta.status.value == "todo"
        # Only the park's own entry: the move back added nothing.
        assert len(_run_log(tmp_project, task)) == 1

    def test_pm_update_writes_the_same_entry_a_verb_writes(self, tmp_project, task):
        """Given the same triple, both paths agree on the disk format.

        pm_park is `status=review, outcome=blocked` said structurally; the
        same values passed to pm_update must land as the same entry, so the
        run log stays one homogeneous stream across both spellings.
        """
        from projectman.server import pm_update

        store = Store(tmp_project)
        store.create_task("US-TST-1", "Task 2", READY_BODY, points=1)

        pm_update(
            "US-TST-1-1", status="review", outcome="blocked", note="same note"
        )
        self._verb("pm_park")("US-TST-1-2", note="same note")

        by_update = _run_log(tmp_project, "US-TST-1-1")
        by_verb = _run_log(tmp_project, "US-TST-1-2")
        assert len(by_update) == len(by_verb) == 1

        def shape(entry):
            return entry.model_dump(exclude={"timestamp"})

        assert shape(by_update[0]) == shape(by_verb[0])
        assert by_update[0].status == "review"
        assert by_update[0].outcome.value == "blocked"
