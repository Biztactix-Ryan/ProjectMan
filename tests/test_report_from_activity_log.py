"""US-PM-14-3 — the final report is built from the activity log, not memory.

``tests/test_skill_activity_report.py`` pins the two halves separately: that
step 22 *says* to rebuild the report from ``pm_activity(run_id=)``, and that
each event type it names is *emitted* carrying the run id.  Neither half
answers the acceptance criterion on its own, because a report is only "built
from the log" if an orchestrator holding nothing but that one filtered slice
can actually produce every section step 22 asks for.

So this module drives one realistic run over real ``tools/call``s — two
accepts (the second closing its story), a retry, a park, an accept-as-review,
a claim recovered from a dead run, a release, and the sprint close — and then
throws the run's memory away.  ``_report_from_log`` is the orchestrator
following step 22 literally: it reads the ``pm_activity(run_id=)`` slice and
nothing else except the two lookups step 22 itself names (``pm_run_log`` for
the outcome split and one projected ``pm_get`` for points).  Every section it
derives is compared against the ground truth the scenario built.

The point of the points assertion in particular: a human edits one accepted
task's estimate from 3 to 5 mid-run, untagged.  A run totalling remembered
numbers reports 9; the store says 11.
"""

import re

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import Store
from tests.test_skill_guidance_tools import _step
from tests.test_skill_verdict_verbs import DOCS, _text

# ─── the run under reconstruction ────────────────────────────────

#: the step that rebuilds the report from the log
REPORT_STEP = "22."

#: this run — the only slice the report may be built from
RUN = "orch-2026-08-22-1111"

#: the run that died holding a claim this one takes back
DEAD_RUN = "orch-2026-08-21-9c2f"

#: a third run working the same project at the same time
OTHER_RUN = "orch-2026-08-22-2222"

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: one rendered ``pm_activity`` entry, e.g.
#: ``[2026-…Z] UPDATE task US-TST-1-1 by Farhan Rich run orch-… (status: a → b)``
ENTRY = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+(?P<event>[A-Z]+)\s+(?P<kind>\w+)\s+(?P<id>[\w-]+)"
    r"\s+by\s+(?P<actor>.*?)"
    r"(?:\s+run\s+(?P<run>[\w-]+))?"
    r"(?:\s+\((?P<changes>.*)\))?$"
)

#: one ``field: before → after`` pair inside an entry's change list
CHANGE = re.compile(r"^(?P<field>[a-z_]+): (?P<before>.*?) → (?P<after>.*)$")


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


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


def _ok(name: str, **arguments) -> str:
    is_error, text = _call(name, arguments)
    assert not is_error, f"{name}({arguments}) failed: {text}"
    return text


# ═══ the run ════════════════════════════════════════════════════


class Truth:
    """What the run actually did — the answer the log has to reproduce."""

    accepted = {"US-TST-1-1", "US-TST-1-2", "US-TST-3-1"}
    retried = {"US-TST-2-1"}
    parked = {"US-TST-2-2"}
    accepted_as_review = {"US-TST-2-3"}
    recovered = {"US-TST-3-1"}
    released = {"US-TST-3-2"}
    stories_closed = {"US-TST-1"}
    #: 3 + 5 + 3 — US-TST-1-2 was re-estimated mid-run behind the run's back
    points = 11
    #: what the run *remembers* estimating, and would report from memory
    remembered_points = 9
    untouched = {"US-TST-2-4", "US-TST-3-3"}
    plan = (
        accepted | retried | parked | accepted_as_review | released | untouched
    )
    sprint = "SPRINT-TST-1"


@pytest.fixture
def orchestrated(tmp_project):
    """One run's worth of real work, interleaved with a rival run and a human."""
    store = Store(tmp_project)
    for story, tasks in ((1, 2), (2, 4), (3, 3)):
        store.create_story(f"Story {story}", "Story body text long enough to matter.")
        store.update(f"US-TST-{story}", status="active")
        for n in range(1, tasks + 1):
            store.create_task(f"US-TST-{story}", f"Task {n}", READY_BODY, points=3)
    sprint = store.create_sprint(
        "Sprint 1", planned_stories=["US-TST-1", "US-TST-2", "US-TST-3"]
    )
    assert sprint.id == Truth.sprint

    # A claim the previous run died holding, before this run starts.
    _ok("pm_grab", task_id="US-TST-3-1", run_id=DEAD_RUN)

    # ─ accept, and accept again to close the story ─
    _ok("pm_grab", task_id="US-TST-1-1", run_id=RUN)
    _ok("pm_accept", task_id="US-TST-1-1", note="all DoD met", run_id=RUN,
        next_task=False)
    _ok("pm_grab", task_id="US-TST-1-2", run_id=RUN)
    closing = _ok("pm_accept", task_id="US-TST-1-2", note="all DoD met", run_id=RUN,
                  next_task=False)
    assert "story_closed: US-TST-1" in closing, closing

    # ─ retry ─
    _ok("pm_grab", task_id="US-TST-2-1", run_id=RUN)
    _ok("pm_retry", task_id="US-TST-2-1", note="tests still red")
    # ─ park ─
    _ok("pm_grab", task_id="US-TST-2-2", run_id=RUN)
    _ok("pm_park", task_id="US-TST-2-2", note="needs the staging DB credentials")
    # ─ accept-as-review ─
    _ok("pm_grab", task_id="US-TST-2-3", run_id=RUN)
    _ok("pm_review", task_id="US-TST-2-3", note="endpoint works; error paths untested")

    # ─ recover the dead run's claim, then finish it ─
    _ok("pm_grab", task_id="US-TST-3-1", run_id=RUN)
    _ok("pm_update", id="US-TST-3-1", outcome="info",
        note=f"recovered from run {DEAD_RUN}", run_id=RUN)
    _ok("pm_accept", task_id="US-TST-3-1", note="finished after recovery",
        run_id=RUN, next_task=False)

    # ─ a pre-claimed task handed back unstarted ─
    _ok("pm_grab", task_id="US-TST-3-2", run_id=RUN)
    _ok("pm_release", task_id="US-TST-3-2", note="budget reached before it started",
        run_id=RUN)

    # ─ noise: a rival run on a task this run touched, and an untagged human edit ─
    _ok("pm_grab", task_id="US-TST-2-1", run_id=OTHER_RUN)
    _ok("pm_grab", task_id="US-TST-3-3", run_id=OTHER_RUN)
    _ok("pm_update", id="US-TST-1-2", points=5)

    # ─ step 24 ─
    _ok("pm_update_sprint", sprint_id=sprint.id, status="completed", run_id=RUN)
    return store


# ═══ the orchestrator, following step 22 with no memory ═════════


def _slice(run_id: str, limit: int = 100) -> list[dict]:
    """Step 22's query, paged on ``has_more`` exactly as the step says."""
    entries, offset = [], 0
    while True:
        page = yaml.safe_load(
            _ok("pm_activity", run_id=run_id, limit=limit, offset=offset)
        )
        entries.extend(page["entries"])
        if not page.get("has_more"):
            break
        offset += limit
    parsed = []
    for line in entries:
        match = ENTRY.match(line)
        assert match, f"unparseable activity entry: {line!r}"
        fields = match.groupdict()
        changes = {}
        for chunk in (fields["changes"] or "").split(", "):
            pair = CHANGE.match(chunk)
            if pair:
                changes[pair["field"]] = (pair["before"], pair["after"])
        fields["changes"] = changes
        parsed.append(fields)
    return parsed


def _outcome(task_id: str) -> str | None:
    """The task's newest run-log outcome — step 22's split for same-status verdicts."""
    log = yaml.safe_load(_ok("pm_run_log", id=task_id, limit=1))
    return log[0]["outcome"] if log else None


def _report_from_log(run_id: str, plan: set[str], limit: int = 100) -> dict:
    """Every section of step 22's report, derived from the log and nothing else.

    The only lookups beyond the slice are the two step 22 itself names: the
    ``pm_run_log`` outcome that separates verdicts sharing a status, and one
    projected ``pm_get`` for points.  Nothing here consults what the run did.
    """
    entries = _slice(run_id, limit=limit)
    tasks = [e for e in entries if e["kind"] == "task"]

    def moved_to(status):
        return {
            e["id"] for e in tasks if e["changes"].get("status", (None, None))[1] == status
        }

    accepted = moved_to("done")
    # Both `pm_retry` and `pm_release` write the same entry — claim cleared,
    # status back to `todo` — so the outcome is the only separator, exactly as
    # it is for park vs accept-as-review.
    back_in_pool = moved_to("todo")
    retried = {t for t in back_in_pool if _outcome(t) == "failed"}
    released = back_in_pool - retried
    # Park and accept-as-review both land on `review`.
    to_review = moved_to("review")
    parked = {t for t in to_review if _outcome(t) == "blocked"}
    accepted_as_review = {t for t in to_review if _outcome(t) == "partial"}

    recovered = {
        e["id"]
        for e in tasks
        if (claim := e["changes"].get("claimed_by_run"))
        and claim[0].startswith("orch-")
        and claim[1] == run_id
    }
    stories_closed = {
        e["id"]
        for e in entries
        if e["kind"] == "story" and e["changes"].get("status", (None, None))[1] == "done"
    }
    sprints_closed = {
        e["id"]
        for e in entries
        if e["kind"] == "sprint"
        and e["changes"].get("status", (None, None))[1] == "completed"
    }

    points = 0
    if accepted:
        projected = yaml.safe_load(
            _ok("pm_get", id=",".join(sorted(accepted)), fields="points")
        )
        points = sum(item["points"] for item in projected)

    return {
        "accepted": accepted,
        "retried": retried,
        "parked": parked,
        "accepted_as_review": accepted_as_review,
        "recovered": recovered,
        "released": released,
        "stories_closed": stories_closed,
        "sprints_closed": sprints_closed,
        "points": points,
        "untouched": plan - {e["id"] for e in tasks},
    }


# ═══ (a) every section is derivable from the slice alone ════════


@pytest.mark.parametrize(
    "section",
    [
        "accepted",
        "retried",
        "parked",
        "accepted_as_review",
        "recovered",
        "released",
        "stories_closed",
        "untouched",
    ],
)
def test_every_report_section_comes_out_of_the_log(orchestrated, section):
    """One filtered query reproduces each list the run would have remembered."""
    report = _report_from_log(RUN, Truth.plan)
    assert report[section] == getattr(Truth, section), (
        f"{section} derived from the log is {sorted(report[section])}, but the "
        f"run actually did {sorted(getattr(Truth, section))}"
    )


def test_the_sprint_close_is_in_the_runs_own_slice(orchestrated):
    """Step 24 tags the close so step 22's report can name it."""
    assert _report_from_log(RUN, Truth.plan)["sprints_closed"] == {Truth.sprint}


def test_points_come_from_the_store_and_not_from_the_remembered_estimates(
    orchestrated,
):
    """A task re-estimated behind the run's back is why memory cannot be trusted."""
    report = _report_from_log(RUN, Truth.plan)
    assert report["points"] == Truth.points
    assert report["points"] != Truth.remembered_points, (
        "the scenario no longer distinguishes the store's total from the "
        "orchestrator's remembered one, so this proves nothing"
    )


def test_no_section_is_empty_so_the_scenario_actually_exercises_them(orchestrated):
    """Guard against a report of nine empty lists passing every assertion."""
    report = _report_from_log(RUN, Truth.plan)
    empty = [k for k, v in report.items() if isinstance(v, set) and not v]
    assert not empty, f"these sections were never exercised: {empty}"


# ═══ (b) paging ═════════════════════════════════════════════════


def test_a_page_smaller_than_the_run_still_yields_the_whole_report(orchestrated):
    """`has_more` paging is not optional: page 1 alone is a wrong report."""
    first = yaml.safe_load(_ok("pm_activity", run_id=RUN, limit=3, offset=0))
    assert first["has_more"] is True
    assert first["total"] > 3
    assert len(first["entries"]) == 3

    assert _report_from_log(RUN, Truth.plan, limit=3) == _report_from_log(
        RUN, Truth.plan, limit=100
    )


def test_the_unpaged_first_page_would_have_been_wrong(orchestrated):
    """The failure paging prevents, spelled out."""
    complete = _report_from_log(RUN, Truth.plan, limit=1000)
    entries = _slice(RUN)
    assert len(entries) > 3, entries
    # A run that stopped at the first page holds only the newest events, so the
    # first accept of the run is simply not in it.
    page = yaml.safe_load(_ok("pm_activity", run_id=RUN, limit=3))["entries"]
    assert not any("US-TST-1-1" in line for line in page), page
    assert "US-TST-1-1" in complete["accepted"]


# ═══ (c) other runs and untagged edits stay out ═════════════════


def test_a_rival_runs_work_on_the_same_task_never_enters_the_report(orchestrated):
    """OTHER_RUN grabbed US-TST-2-1 after this run retried it."""
    mine = _slice(RUN)
    assert all(e["run"] == RUN for e in mine), mine
    theirs = _slice(OTHER_RUN)
    assert {e["id"] for e in theirs} == {"US-TST-2-1", "US-TST-3-3"}
    # This run's slice holds its own retry of 2-1 and nothing of the rival's claim.
    ours_on_2_1 = [e for e in mine if e["id"] == "US-TST-2-1"]
    assert len(ours_on_2_1) == 2, ours_on_2_1  # the grab and the retry
    assert _report_from_log(RUN, Truth.plan)["retried"] == {"US-TST-2-1"}
    # US-TST-3-3 was worked, but not by this run, so it stays untouched.
    assert "US-TST-3-3" in _report_from_log(RUN, Truth.plan)["untouched"]


def test_an_untagged_human_edit_belongs_to_no_run(orchestrated):
    """The re-estimate of US-TST-1-2 is in the log, but in nobody's slice."""
    unfiltered = yaml.safe_load(_ok("pm_activity", item_id="US-TST-1-2", limit=100))
    assert any("points: 3 → 5" in line for line in unfiltered["entries"]), unfiltered
    assert not any(
        "points" in (e["changes"] or {}) for e in _slice(RUN)
    ), "an edit this run never made is inside its slice"
    assert not any("points" in (e["changes"] or {}) for e in _slice(OTHER_RUN))


def test_the_dead_runs_own_events_are_not_this_runs(orchestrated):
    """The recovered claim is reported by this run; the dead run keeps its own."""
    dead = _slice(DEAD_RUN)
    assert {e["id"] for e in dead} == {"US-TST-3-1"}
    assert _report_from_log(DEAD_RUN, Truth.plan)["recovered"] == set(), (
        "the dead run's own claim looks like a recovery to itself"
    )


# ═══ (d) the skill names these categories and these literals ════


#: what step 22 must key on, and the source that has to contain it
LITERALS = [
    "→ done",
    "→ todo",
    "→ review",
    "claimed_by_run",
    "blocked",
    "partial",
]


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("literal", LITERALS)
def test_step_22_names_the_literal_the_report_keys_on(path, literal):
    """Pinned in test_skill_activity_report.py by section; here by literal."""
    step = _step(_text(path), REPORT_STEP)
    assert literal in step, f"step 22 never names {literal!r}"


def test_the_status_arrows_step_22_names_are_the_ones_the_events_carry(orchestrated):
    """The cross-check: skill vocabulary against real rendered entries."""
    rendered = "\n".join(
        yaml.safe_load(_ok("pm_activity", run_id=RUN, limit=100))["entries"]
    )
    for arrow in ("status: in-progress → done", "status: in-progress → todo",
                  "status: in-progress → review", "status: todo → in-progress"):
        assert arrow in rendered, f"no event renders {arrow!r}: {rendered}"
    assert f"claimed_by_run: {DEAD_RUN} → {RUN}" in rendered, rendered
    assert re.search(r"UPDATE story US-TST-1 .*status: active → done", rendered), rendered


def test_the_outcome_words_step_22_splits_on_are_the_ones_the_verbs_write(
    orchestrated,
):
    """`blocked`/`partial`/`failed` are what pm_park/pm_review/pm_retry record."""
    assert _outcome("US-TST-2-2") == "blocked"
    assert _outcome("US-TST-2-3") == "partial"
    assert _outcome("US-TST-2-1") == "failed"
    assert _outcome("US-TST-3-2") == "info"


def test_story_closed_is_the_word_pm_accept_returns(orchestrated):
    """Step 20 tells the orchestrator to watch for `story_closed`; it is real."""
    for path in (DOCS[0].values[0], DOCS[1].values[0]):
        assert "story_closed" in _text(path)


@pytest.mark.parametrize("path", DOCS)
def test_step_22_splits_retried_from_released_by_outcome(path):
    """Both land on `todo` with the claim cleared; only the run log separates them.

    Without this the report double-counts: every released task also matches
    "entries ending ``status: ... → todo``", which is step 22's rule for a
    retry.  Discovered by the end-to-end scenario above, whose ``retried`` set
    came back as ``{US-TST-2-1, US-TST-3-2}`` under the earlier wording.
    """
    step = _step(_text(path), REPORT_STEP)
    assert "failed" in step, (
        "step 22 does not name the outcome (failed) that marks a retry, so a "
        "release back to todo is indistinguishable from one"
    )
    retried = next(line for line in step.splitlines() if "**Retried**" in line)
    released = next(line for line in step.splitlines() if "**Released**" in line)
    assert "pm_run_log(" in retried or "pm_run_log(" in released, (
        "neither the Retried nor the Released bullet reads the run log, so "
        "the two cannot be told apart from the log alone"
    )


# ═══ (e) the log outranks memory ════════════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_memory_is_only_the_cross_check(path):
    """Pinned alongside test_skill_activity_report's version, from the run's side."""
    step = _step(_text(path), REPORT_STEP).lower()
    assert "the log wins" in step
    assert "cross-check" in step
    assert "disagree" in step


def test_a_write_that_never_landed_is_visible_as_a_disagreement(orchestrated):
    """What "the log wins" buys: a remembered verdict the store never took."""
    remembered_accepted = Truth.accepted | {"US-TST-2-4"}
    from_log = _report_from_log(RUN, Truth.plan)["accepted"]
    assert remembered_accepted - from_log == {"US-TST-2-4"}, (
        "the log agrees with a verdict that was never written, so a lost "
        "write would be reported as a success"
    )
