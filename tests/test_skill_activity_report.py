"""US-PM-14-7 — the final report is built from the activity log, not memory.

``pm-orchestrate``'s Phase 4 step 22 used to read, in full:

    Summarize: tasks accepted (with evidence one-liners — read them back from
    ``pm_run_log(id)`` rather than from memory, since step 19 recorded them
    structurally), tasks parked and why, tasks retried, tasks untouched and
    why; points moved; stories completed.

Every list in that sentence came from the orchestrator's own recollection of a
loop that may have run for hours, and the one thing that could have supplied
them instead — the append-only activity log — was called zero times across
~14,200 tool calls in four usage studies.  US-PM-14-5 put a ``run_id`` on the
claim, release and verdict events; this task gives ``pm_activity`` a filter for
it, so *one* query returns everything a run did, and rewrites step 22 to spend
that query.

Two halves, pinned here together because neither is worth anything alone:

* **the instruction** — over the template (source of truth) and the tracked
  rendered ``SKILL.md`` alike, in the manner of
  ``tests/test_skill_claim_recovery.py``; their byte-for-byte equality is owned
  by ``tests/test_skill_verdict_verbs.py``.  Step 22 must issue a real
  ``pm_activity(run_id=...)``, page it to exhaustion, derive every section of
  the report from the entries, and say outright that the log outranks memory
  when the two disagree.  Step 23 keeps the ``git diff --stat``, which is the
  half of the report the log genuinely cannot supply.
* **the mechanism** — the filter exists, it separates two interleaved runs over
  a real ``tools/call``, and every event type step 22 names is actually emitted
  carrying the run id.  A skill telling the orchestrator to derive "stories
  closed" from a query that never returns a story closure would be a report
  rebuilt from nothing.
"""

import inspect
import re

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import Store
from tests.test_skill_guidance_tools import _step
from tests.test_skill_verdict_verbs import DOCS, _outside_fences, _text

# ─── the steps under test ────────────────────────────────────────

#: the step that rebuilds the report from the log
REPORT_STEP = "22."

#: the step that keeps the working-tree diff
DIFF_STEP = "23."

#: the step that closes the sprint out
SPRINT_STEP = "24."

#: Phase 0's run-id subsection heading (minted by US-PM-14-6)
RUN_ID_HEADING = "### Run id"

#: the heading US-PM-14-8 fills in — this task must leave it standing
RESUME_HEADING = "## Resume"

#: what the run's own slice of the log is spelled as
ACTIVITY_CALL = re.compile(r"pm_activity\(([^)]*)\)")

#: any ``pm_*(...)`` call, with its argument list captured
TOOL_CALL = re.compile(r"\b(pm_[a-z_]+)\(([^)]*)\)")

#: ``name=`` inside an argument list
KWARG = re.compile(r"\b([a-z_]+)=")

#: every section of the report step 22 must derive from the log, as the
#: phrase the step spells it with
REPORT_SECTIONS = (
    "Accepted",
    "Retried",
    "Parked",
    "accept-as-review",
    "Recovered claims",
    "Released",
    "Stories closed",
    "Points moved",
    "Untouched",
)


def _run_id_section(text: str) -> str:
    """Phase 0's run-id subsection: its heading up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(RUN_ID_HEADING)]
    assert starts, f"no {RUN_ID_HEADING!r} heading — the run id is never minted"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _schemas() -> dict:
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ═══ step 22 — the query ════════════════════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_step_22_queries_the_activity_log_for_this_run(path):
    """The report starts from ``pm_activity(run_id=<this run>)``, not a memory."""
    step = _step(_text(path), REPORT_STEP)
    calls = ACTIVITY_CALL.findall(step)
    assert calls, (
        "step 22 never calls pm_activity — the report is still being "
        "reconstructed from the orchestrator's memory"
    )
    assert any("run_id=" in args for args in calls), (
        f"step 22 calls pm_activity without a run_id filter: {calls!r}; "
        "an unfiltered log is every run's events, not this one's"
    )
    assert "<this run>" in step, (
        "step 22 does not spend the run id minted in Phase 0 — some other "
        "id would not be this run's slice of the log"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_22_pages_the_query_to_exhaustion(path):
    """A report built from a silently truncated first page is a wrong report."""
    step = _step(_text(path), REPORT_STEP)
    assert "has_more" in step, (
        "step 22 never mentions has_more — nothing tells the orchestrator "
        "the first page was not the whole run"
    )
    assert "offset" in step, "step 22 names no way to fetch the next page"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("section", REPORT_SECTIONS)
def test_step_22_derives_every_report_section_from_the_log(path, section):
    """Each list the report carries is named, with the entries it comes from."""
    step = _step(_text(path), REPORT_STEP)
    assert section.lower() in step.lower(), (
        f"step 22 does not derive {section!r} — that section of the report "
        "would still come from memory"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_22_splits_park_from_review_by_run_log_outcome(path):
    """Both verdicts land on ``review``; only the outcome separates them.

    The log records the status transition, not the verb, so a step that
    derived "parked" from ``→ review`` alone would silently merge the tasks
    a human must look at with the ones that merely need a second opinion.
    """
    step = _step(_text(path), REPORT_STEP)
    assert "pm_run_log(" in step, (
        "step 22 never reads the run log, so park and accept-as-review "
        "cannot be told apart"
    )
    assert "blocked" in step and "partial" in step, (
        "step 22 does not name the outcomes that separate a park (blocked) "
        "from an accept-as-review (partial)"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_22_makes_the_log_authoritative_over_memory(path):
    """Memory is the cross-check; on disagreement the log wins, out loud."""
    step = _step(_text(path), REPORT_STEP).lower()
    assert "the log wins" in step, (
        "step 22 does not say which side wins when the log and the "
        "orchestrator's notes disagree — an unresolved tie is a guess"
    )
    assert "disagree" in step, "step 22 never contemplates a disagreement"
    assert "cross-check" in step or "cross check" in step, (
        "step 22 does not demote memory to a cross-check"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_22_sums_points_from_the_store_not_from_memory(path):
    """Points moved is a projected ``pm_get`` over the accepted ids."""
    step = _step(_text(path), REPORT_STEP)
    assert "pm_get(" in step and "points" in step, (
        "step 22 gives no way to total the points it reports"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_22_names_only_real_tools_with_real_parameters(path):
    """The pin is not cosmetic: every call in step 22 must exist as written.

    A step telling the orchestrator to pass a keyword the server does not
    accept is a report that raises instead of rendering.
    """
    schemas = _schemas()
    step = _step(_text(path), REPORT_STEP)
    for name, args in TOOL_CALL.findall(step):
        assert name in schemas, f"step 22 calls {name}, which is not a registered tool"
        params = set(schemas[name].inputSchema.get("properties", {}))
        for kwarg in KWARG.findall(args):
            assert kwarg in params, (
                f"step 22 passes {name}({kwarg}=...), but {name} has no such "
                f"parameter; it takes {sorted(params)}"
            )


# ═══ step 23 — the half the log cannot supply ═══════════════════


@pytest.mark.parametrize("path", DOCS)
def test_step_23_still_shows_the_working_tree_diff(path):
    """The activity log records item moves, never file moves."""
    step = _step(_text(path), DIFF_STEP)
    assert "git diff --stat" in step, (
        "step 23 dropped the working-tree diff — the report would no longer "
        "say what code changed"
    )
    assert ".project/" in step, (
        "step 23 no longer separates code changes from .project/ status churn"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_23_says_why_the_log_does_not_replace_the_diff(path):
    """Reader must not conclude step 22 made step 23 redundant."""
    step = _step(_text(path), DIFF_STEP).lower()
    assert "log" in step, (
        "step 23 never explains its relationship to the log step before it"
    )


@pytest.mark.parametrize("path", DOCS)
def test_sprint_close_is_tagged_with_the_run(path):
    """Step 24's close must land inside this run's slice of the log."""
    step = _step(_text(path), SPRINT_STEP)
    assert "pm_update_sprint(" in step
    assert "run_id=" in step, (
        "step 24 completes the sprint without a run_id, so the sprint close "
        "is invisible to step 22's query"
    )


# ═══ the run-id section, and the anchor 14-8 fills ══════════════


@pytest.mark.parametrize("path", DOCS)
def test_run_id_section_says_the_report_is_rebuilt_from_the_log(path):
    """Phase 0 must say what the id buys at the *end* of the run, too."""
    section = _run_id_section(_text(path))
    assert "pm_activity(run_id=" in section, (
        "the run-id section never mentions the query that spends the id at "
        "the end of the run"
    )
    assert "report" in section.lower(), (
        "the run-id section does not connect the id to the final report"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_resume_anchor_is_left_standing_for_14_8(path):
    """This task must not write — or delete — US-PM-14-8's section."""
    text = _text(path)
    assert RESUME_HEADING in text, (
        f"the {RESUME_HEADING!r} anchor is gone; US-PM-14-8 has nothing to "
        "fill in"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_old_memory_first_summary_sentence_is_gone(path):
    """The instruction it replaced must not survive anywhere in the document."""
    prose = _outside_fences(_text(path))
    assert "rather than from memory, since step 19 recorded them" not in prose, (
        "the pre-14-7 step 22 sentence is still in the document"
    )


# ═══ the mechanism — pm_activity's run_id filter ════════════════

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

RUN_A = "orch-2026-08-22-aaaa"
RUN_B = "orch-2026-08-22-bbbb"


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _seed(tmp_project, tasks_per_story=2, stories=1) -> Store:
    store = Store(tmp_project)
    for s in range(1, stories + 1):
        store.create_story(f"Story {s}", "Story body text long enough to matter.")
        store.update(f"US-TST-{s}", status="active")
        for i in range(1, tasks_per_story + 1):
            store.create_task(f"US-TST-{s}", f"Task {i}", READY_BODY, points=3)
    return store


def _call(name: str, arguments: dict) -> tuple[bool, str]:
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


def _activity(**arguments) -> dict:
    arguments.setdefault("limit", 100)
    is_error, text = _call("pm_activity", arguments)
    assert not is_error, text
    return yaml.safe_load(text)


def test_pm_activity_publishes_a_run_id_filter():
    """The parameter is on the wire schema, not merely in the Python body."""
    schema = _schemas()["pm_activity"].inputSchema["properties"]
    assert "run_id" in schema, (
        "pm_activity has no run_id filter, so 'every event this run produced' "
        "is not one call"
    )


def test_the_run_id_filter_returns_exactly_one_runs_events(tmp_project):
    """Two runs interleaved on one project; each sees only its own."""
    _seed(tmp_project, tasks_per_story=2)
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    server.pm_grab("US-TST-1-2", run_id=RUN_B)
    server.pm_release("US-TST-1-2", note="handing it back", run_id=RUN_B)
    server.pm_retry("US-TST-1-1", note="tests failed")

    a = _activity(run_id=RUN_A)
    b = _activity(run_id=RUN_B)
    assert a["total"] == 2, a["entries"]
    assert b["total"] == 2, b["entries"]
    assert all(f"run {RUN_A}" in e for e in a["entries"]), a["entries"]
    assert all(f"run {RUN_B}" in e for e in b["entries"]), b["entries"]
    assert all("US-TST-1-1" in e for e in a["entries"]), a["entries"]
    assert all("US-TST-1-2" in e for e in b["entries"]), b["entries"]


def test_an_untagged_edit_belongs_to_no_run(tmp_project):
    """Pre-14-5 lines and ordinary edits must never match a run filter."""
    _seed(tmp_project, tasks_per_story=1)
    import projectman.server as server

    server.pm_update("US-TST-1-1", points=5)
    assert _activity(run_id=RUN_A)["total"] == 0
    # ...but the event is in the log, so this is a filter and not a dropped write.
    assert _activity(item_id="US-TST-1-1")["total"] >= 1


def test_has_more_reports_the_next_page(tmp_project):
    """Step 22 pages on ``has_more``; it has to mean something."""
    _seed(tmp_project, tasks_per_story=3)
    import projectman.server as server

    for n in (1, 2, 3):
        server.pm_grab(f"US-TST-1-{n}", run_id=RUN_A)

    first = _activity(run_id=RUN_A, limit=2, offset=0)
    assert first["total"] == 3
    assert first["has_more"] is True
    assert len(first["entries"]) == 2
    second = _activity(run_id=RUN_A, limit=2, offset=2)
    assert second["has_more"] is False
    assert len(second["entries"]) == 1


# ═══ every event step 22 names is emitted with the run id ═══════


def test_claim_verdict_and_story_closure_all_carry_the_run_id(tmp_project):
    """The end-to-end shape step 22 reads: grab → done_next → story_closed."""
    _seed(tmp_project, tasks_per_story=1)
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    is_error, text = _call(
        "pm_done_next",
        {"task_id": "US-TST-1-1", "note": "shipped it", "run_id": RUN_A},
    )
    assert not is_error, text
    assert "story_closed: US-TST-1" in text, text

    entries = _activity(run_id=RUN_A)["entries"]
    assert all(f"run {RUN_A}" in e for e in entries), entries

    claim = [e for e in entries if "todo → in-progress" in e]
    verdict = [e for e in entries if "in-progress → done" in e and "task" in e]
    closure = [e for e in entries if "story US-TST-1 " in e and "→ done" in e]
    assert claim, f"no claim event tagged with the run: {entries}"
    assert verdict, f"no verdict event tagged with the run: {entries}"
    assert closure, (
        f"the story closure is not in the run's slice of the log, so step 22 "
        f"cannot report 'stories closed': {entries}"
    )


@pytest.mark.parametrize(
    "verb,transition",
    [
        ("pm_retry", "in-progress → todo"),
        ("pm_park", "in-progress → review"),
        ("pm_review", "in-progress → review"),
    ],
)
def test_each_verdict_verb_tags_its_event_with_the_claiming_run(
    tmp_project, verb, transition
):
    """The verdict verbs take no ``run_id``: they inherit the claim's."""
    _seed(tmp_project, tasks_per_story=1)
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    is_error, text = _call(verb, {"task_id": "US-TST-1-1", "note": "because"})
    assert not is_error, text

    entries = _activity(run_id=RUN_A)["entries"]
    assert any(transition in e for e in entries), (
        f"{verb}'s event is missing from run {RUN_A}'s slice: {entries}"
    )


def test_pm_update_can_tag_an_edit_with_the_run(tmp_project):
    """Step 3's recovery note has to land inside the run's own slice."""
    _seed(tmp_project, tasks_per_story=1)
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_B)
    is_error, text = _call(
        "pm_update",
        {
            "id": "US-TST-1-1",
            "outcome": "info",
            "note": f"recovered from run {RUN_B}",
            "run_id": RUN_A,
        },
    )
    assert not is_error, text
    assert _activity(run_id=RUN_A)["total"] == 1


def test_pm_update_many_tags_every_event_it_writes(tmp_project):
    """``run_id`` is a property of the call, like ``project``."""
    _seed(tmp_project, tasks_per_story=2)
    is_error, text = _call(
        "pm_update_many",
        {"ids": "US-TST-1-1,US-TST-1-2", "points": 5, "run_id": RUN_A},
    )
    assert not is_error, text
    assert _activity(run_id=RUN_A)["total"] == 2


def test_pm_update_sprint_tags_the_sprint_close(tmp_project):
    """Step 24's close-out is part of the run, so the report can name it."""
    store = _seed(tmp_project, tasks_per_story=1)
    sprint = store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
    is_error, text = _call(
        "pm_update_sprint",
        {"sprint_id": sprint.id, "status": "completed", "run_id": RUN_A},
    )
    assert not is_error, text
    entries = _activity(run_id=RUN_A)["entries"]
    assert any(sprint.id in e for e in entries), entries


def test_run_id_is_never_written_to_frontmatter(tmp_project):
    """It tags the event, never the item — the same rule as ``Store.update``."""
    store = _seed(tmp_project, tasks_per_story=1)
    sprint = store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
    store.update_sprint(sprint.id, status="completed", run_id=RUN_A)
    text = (tmp_project / ".project" / "sprints" / f"{sprint.id}.md").read_text()
    assert "run_id" not in text, text
    store.update("US-TST-1-1", points=5, run_id=RUN_A)
    assert "run_id" not in (tmp_project / ".project" / "tasks" / "US-TST-1-1.md").read_text()


def test_the_report_query_is_documented_on_the_tool():
    """The docstring the model reads must name the filter's purpose."""
    from projectman.server import pm_activity

    doc = inspect.getdoc(pm_activity) or ""
    assert "run_id:" in doc, "pm_activity's run_id parameter is undocumented"
    assert "has_more" in doc, "pm_activity never tells the caller to paginate"
