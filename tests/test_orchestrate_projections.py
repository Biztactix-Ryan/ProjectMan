"""US-PM-49-1 — the projections exist on the tools *and* the skill uses them.

Story US-PM-49's acceptance criterion is a two-ended claim:

    "pm_board, pm_batch_get and pm_list_sprints accept a brief or fields
    projection and the orchestrate skill uses it in pre-flight and planning"

Either end alone is worthless.  A server that serves ``brief``/``fields`` while
the skill keeps asking for whole boards saves nothing — the 13 KB board, the
16 KB batch read and the 6.6 KB sprint list measured on the Kura runs are paid
by the *caller's* instructions, not by the tool's capability.  A skill that
names a projection the server does not serve is worse: every run breaks at
pre-flight.  So this module holds both halves and, in the plan-phase test,
joins them.

Deliberately thin where other modules are thick:

* server-side semantics — the byte-identical default, ``fields`` beating
  ``brief``, the empty-string cases, the per-key exhaustion for each type —
  are owned by ``tests/test_brief_mode.py`` and ``tests/test_field_projection.py``.
  Here there is exactly one compact test per behaviour named in the criterion,
  parametrized across the three tools, so the criterion is pinned as *one*
  statement about all three rather than re-litigated tool by tool;
* the plan-phase read's field set, its acceptance by the server, and the
  document-wide sweep for unprojected reads are owned by
  ``tests/test_skill_projection.py``; its helpers are imported, not copied, and
  the test below closes the one gap that module leaves — that the literal it
  feeds to the real ``pm_batch_get`` is the literal *Phase 2* carries, in the
  template and a live render as well as the rendered ``SKILL.md``.

The skill half runs over three documents (Jinja template, tracked rendered
``SKILL.md``, live render) and is scoped to the phase slices the criterion
names, so a projected call that migrated out of pre-flight or planning fails
here rather than passing on a document-wide grep.  Falsification guards push
pre-US-PM-49-6 phase text through the same checks and require it to fail.

Nothing here writes outside ``tmp_path``, and nothing here modifies a template.
"""

import re
from dataclasses import dataclass, field
from typing import Callable

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.cli import _render_template
from tests.test_skill_projection import (
    FIELDS_LITERAL,
    PM_BATCH_GET_CALL,
    PM_GET_CALL,
    _plan_read,
)
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
)
from tests.test_skill_verdict_verbs import ORCHESTRATE_TEMPLATE_NAME, _text

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ═══════════════════════════════════════════════════════════════════
# Server half — the three tools accept the projections
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def seeded(tmp_project):
    """A board with both a ready and an unready group, stories, and sprints.

    The acceptance criteria matter twice over: they are free text ``brief``
    must drop from the stories, and the tasks they auto-create are thin and
    unpointed, which is what puts rows in the board's ``not_ready`` group.
    """
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


def _board_rows(**kwargs) -> list[dict]:
    """Every board row, groups flattened in a stable order."""
    from projectman.server import pm_board

    board = yaml.safe_load(pm_board(**kwargs))["board"]
    return [row for group in sorted(board) for row in board[group]]


def _story_items(**kwargs) -> list[dict]:
    from projectman.server import pm_batch_get

    return yaml.safe_load(pm_batch_get(type="stories", **kwargs))


def _sprints(**kwargs) -> list[dict]:
    from projectman.server import pm_list_sprints

    return yaml.safe_load(pm_list_sprints(**kwargs))["sprints"]


@dataclass(frozen=True)
class ToolCase:
    """One tool, seen through the criterion's four claims."""

    #: call the tool with projection kwargs, return the rows it projects
    rows: Callable[..., list[dict]]
    #: the free-text keys ``brief=True`` must drop from every row
    free_text: tuple[str, ...]
    #: a ``fields=`` literal the tool serves — none of these names is ``id``
    projection: str
    #: a name the tool has never heard of
    unknown: str
    #: names the rejection message must list as valid
    valid_names: tuple[str, ...] = field(default=())


TOOLS = {
    "pm_board": ToolCase(
        rows=_board_rows,
        free_text=("story", "hints", "blockers"),
        projection="title,points",
        unknown="titel",
        valid_names=("id", "title", "points", "story", "hints", "blockers"),
    ),
    "pm_batch_get": ToolCase(
        rows=_story_items,
        free_text=("body", "acceptance_criteria"),
        projection="status,points",
        unknown="stats",
        valid_names=("status", "points", "acceptance_criteria"),
    ),
    "pm_list_sprints": ToolCase(
        rows=_sprints,
        free_text=("goal",),
        projection="status,completed_points",
        unknown="goals",
        valid_names=("goal", "status", "planned_points", "completed_points"),
    ),
}

TOOL_IDS = list(TOOLS)


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_each_tool_accepts_brief_and_fields(seeded, tool):
    """The criterion's verb, taken literally: both parameters are accepted.

    Not a formality — until US-PM-49-5 ``pm_board`` had neither, and a caller
    passing them got a TypeError rather than a smaller board.
    """
    case = TOOLS[tool]
    assert case.rows(), f"{tool} returned no rows to project — fixture is vacuous"
    assert case.rows(brief=True), f"{tool}(brief=True) returned nothing"
    assert case.rows(fields=case.projection), (
        f"{tool}(fields={case.projection!r}) returned nothing"
    )


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_brief_drops_the_free_text_from_every_row(seeded, tool):
    """``brief=True`` removes the bodies, goals, criteria and labels.

    Guarded against vacuity in both directions: the default must *carry* the
    free text (otherwise the saving came from a quietly slimmed default, not
    from the projection), and the brief rows must still be there.
    """
    case = TOOLS[tool]
    full = case.rows()
    assert any(key in row for row in full for key in case.free_text), (
        f"no {tool} row carries any of {case.free_text} even without brief — "
        "the fixture cannot show that brief drops anything"
    )

    brief = case.rows(brief=True)
    assert len(brief) == len(full), f"{tool}(brief=True) changed the listing itself"
    for row in brief:
        assert "id" in row
        for key in case.free_text:
            assert key not in row, f"{tool}(brief=True) still carries {key!r}: {row}"


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_fields_projects_to_the_named_keys_and_keeps_id(seeded, tool):
    """``fields`` returns the named keys and ``id``, and nothing else.

    Compared row-by-row against the unprojected call, so the assertion is
    exact where a row has every named key and still correct where a row does
    not have one (an unpointed board row has no ``points``): a key a row never
    had cannot appear, and a value must not change on the way through.
    """
    case = TOOLS[tool]
    names = {n.strip() for n in case.projection.split(",") if n.strip()}
    assert "id" not in names, "the literal must not name id — id survives unnamed"

    full = case.rows()
    projected = case.rows(fields=case.projection)
    assert len(projected) == len(full)
    assert any(names <= set(row) for row in full), (
        f"no {tool} row has all of {sorted(names)} — the projection would be "
        "trivially satisfied"
    )
    for row, full_row in zip(projected, full):
        assert set(row) == {"id"} | (names & set(full_row)), (
            f"{tool}(fields={case.projection!r}) returned {sorted(row)}"
        )
        for key, value in row.items():
            assert value == full_row[key], (tool, key)


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_an_unknown_field_name_is_an_error_listing_the_valid_names(seeded, tool):
    """A typo fails loudly and says what would have worked.

    The dangerous alternative is a silent empty projection: the orchestrator
    would read a board of bare ids, see no error, and plan on nothing.
    """
    case = TOOLS[tool]
    with pytest.raises(ToolError) as excinfo:
        case.rows(fields=case.unknown)
    message = str(excinfo.value)
    assert case.unknown in message, message
    missing = [name for name in case.valid_names if name not in message]
    assert not missing, (
        f"{tool} rejected {case.unknown!r} without listing {missing}: {message}"
    )


# ═══════════════════════════════════════════════════════════════════
# Skill half — pre-flight and planning use them
# ═══════════════════════════════════════════════════════════════════

#: the three documents that must agree: source of truth, the file an
#: orchestrating agent actually loads, and what the renderer produces today
SOURCES = {
    "template": lambda: _text(ORCHESTRATE_TEMPLATE),
    "rendered": lambda: _text(ORCHESTRATE_SKILL),
    "live-render": lambda: _render_template(ORCHESTRATE_TEMPLATE_NAME),
}

PRE_FLIGHT = "Phase 1"
PLAN = "Phase 2"

#: ``pm_list_sprints(status="active", brief=True)`` — quoting and spacing free
LIST_SPRINTS_PROJECTED = re.compile(
    r'pm_list_sprints\(\s*status\s*=\s*["\']active["\']\s*,\s*brief\s*=\s*[Tt]rue\s*\)'
)

#: ``pm_board(brief=True)``
BOARD_PROJECTED = re.compile(r"pm_board\(\s*brief\s*=\s*[Tt]rue\s*\)")

#: any call to the two pre-flight list tools, argument list captured
PRE_FLIGHT_CALLS = re.compile(r"\b(pm_board|pm_list_sprints)\(([^)]*)\)")

#: ``brief=True`` or a ``fields=`` literal — either satisfies the criterion
PROJECTED_ARGS = re.compile(r"brief\s*=\s*[Tt]rue|fields\s*=")


def _phase(text: str, heading: str) -> str:
    """The block under ``## <heading>``, up to the next ``##`` heading."""
    lines = text.splitlines()
    starts = [
        n
        for n, line in enumerate(lines)
        if line.startswith("## ") and heading in line
    ]
    assert starts, f"no '## {heading}' heading — the phase vanished"
    assert len(starts) == 1, f"'{heading}' heads {len(starts)} sections"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


# ─── clause table ────────────────────────────────────────────────
#
# Iterated by the tests *and* by the falsification guards, so a clause cannot
# be checked in one place and quietly dropped from the other.

PRE_FLIGHT_CLAUSES = {
    'the sprint lookup is pm_list_sprints(status="active", brief=True)': (
        lambda phase: bool(LIST_SPRINTS_PROJECTED.search(phase))
    ),
    "the claim scan is pm_board(brief=True)": (
        lambda phase: bool(BOARD_PROJECTED.search(phase))
    ),
    "no pre-flight board or sprint read is unprojected": (
        lambda phase: all(
            PROJECTED_ARGS.search(args)
            for _, args in PRE_FLIGHT_CALLS.findall(phase)
        )
    ),
}


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
@pytest.mark.parametrize("phase", [PRE_FLIGHT, PLAN])
def test_the_phase_slices_are_extractable(source, phase):
    """Guard the slices: every assertion below is scoped to one of them."""
    text = SOURCES[source]()
    assert "template not found" not in text, "the template failed to render"
    block = _phase(text, phase)
    assert len(block.splitlines()) >= 2, f"{phase} lost its steps"
    assert "pm_" in block, f"{phase} makes no store call at all"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
@pytest.mark.parametrize(
    "clause", list(PRE_FLIGHT_CLAUSES), ids=list(PRE_FLIGHT_CLAUSES)
)
def test_pre_flight_uses_the_projections(source, clause):
    """"...and the orchestrate skill uses it in pre-flight", clause by clause.

    Scoped to Phase 1 on purpose: step 11 in Phase 3 calls a bare ``pm_board``
    to pick the next task and that is a different, deliberate call — a
    document-wide rule would either fail on it or have to carve it out.
    """
    phase = _phase(SOURCES[source](), PRE_FLIGHT)
    assert PRE_FLIGHT_CLAUSES[clause](phase), (
        f"pre-flight fails: {clause}\n\n{phase}"
    )


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_plan_phase_reads_the_stories_in_one_projected_batch_call(source):
    """"...and in planning": one ``pm_batch_get(ids=..., fields="...")``.

    ``_plan_read`` is imported from ``tests/test_skill_projection.py`` rather
    than restated — that module owns the field set the plan needs and the
    document-wide uniqueness of the call.  What is added here is the *phase*:
    the one batched read has to live in Phase 2, where the plan is built.
    """
    plan = _phase(SOURCES[source](), PLAN)
    calls = [args for args in PM_BATCH_GET_CALL.findall(plan) if "ids=" in args]
    assert len(calls) == 1, (
        f"expected exactly one pm_batch_get(ids=...) in {PLAN}, found {calls}"
    )
    assert FIELDS_LITERAL.search(calls[0]), (
        f"the plan-phase story read is unprojected: pm_batch_get({calls[0]})"
    )


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_plan_phase_projection_is_the_literal_the_server_accepts(source):
    """Join the halves: Phase 2's literal is the one fed to ``pm_batch_get``.

    That the literal is a projection the server serves for a *story* is
    asserted against the real tool by ``tests/test_skill_projection.py::
    test_the_plan_reads_projection_is_one_the_server_accepts``, which reads it
    out of the rendered ``SKILL.md``.  This test carries that result to the
    other two documents: if the template's literal ever diverges from the
    rendered one, the server-acceptance proof stops covering the source of
    truth, and the next render breaks the plan phase.
    """
    served = FIELDS_LITERAL.search(_plan_read(_text(ORCHESTRATE_SKILL))).group(1)
    here = FIELDS_LITERAL.search(_plan_read(SOURCES[source]())).group(1)
    assert here == served, (
        f"{source} projects fields={here!r} but the literal proven acceptable "
        f"to pm_batch_get is {served!r}"
    )
    assert FIELDS_LITERAL.search(
        [a for a in PM_BATCH_GET_CALL.findall(_phase(SOURCES[source](), PLAN))
         if "ids=" in a][0]
    ).group(1) == served, "the phase-2 call is not the one that was proven"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_no_unprojected_per_story_read_survives_in_the_plan_phase(source):
    """The per-story ``pm_get`` the batch call replaced may not creep back.

    ``tests/test_skill_projection.py`` sweeps the whole document for
    ``pm_get(story_id``; this is the narrower, stronger rule for the phase that
    once made that call — in Phase 2 *no* unprojected ``pm_get`` belongs at
    all, whatever it names.
    """
    plan = _phase(SOURCES[source](), PLAN)
    offenders = [
        args for args in PM_GET_CALL.findall(plan) if not FIELDS_LITERAL.search(args)
    ]
    assert not offenders, (
        f"unprojected read(s) pm_get({offenders}) in {PLAN} — the sprint's "
        "stories are read once, projected, not one whole item per story"
    )
    assert not [a for a in PM_GET_CALL.findall(plan) if "story_id" in a], (
        "a per-story pm_get is back in the plan phase"
    )


# ─── falsification guards ────────────────────────────────────────
#
# A checklist that never fires is not evidence.


def test_the_pre_flight_clauses_reject_the_unprojected_phase_1():
    """The pre-US-PM-49-6 pre-flight must fail every clause."""
    before = (
        "## Phase 1 — Pre-flight\n"
        "1. Sprint: `--sprint <id>` → `pm_get_sprint(id)`, else "
        '`pm_list_sprints(status="active")`. None → stop.\n'
        "3. Classify every in-progress claim from the data: `pm_board()` and "
        "`pm_active` give `claimed_by_run`, `claim_age`, `stale: true`.\n"
    )
    passed = [name for name, check in PRE_FLIGHT_CLAUSES.items() if check(before)]
    assert not passed, f"the unprojected pre-flight passed these clauses: {passed}"


def test_the_pre_flight_clauses_reject_a_half_projected_phase_1():
    """One projected call is not two — a mixed phase must still fail.

    Without this the "no unprojected read" clause could carry the other two:
    a phase that briefs the board and dumps the whole sprint list would look
    compliant to any check that only asks whether a projection appears.
    """
    half = (
        "## Phase 1 — Pre-flight\n"
        '1. `pm_list_sprints(status="active")` — the active sprint.\n'
        "3. `pm_board(brief=True)` and `pm_active` classify the claims.\n"
    )
    failed = [name for name, check in PRE_FLIGHT_CLAUSES.items() if not check(half)]
    assert sorted(failed) == sorted(
        [
            'the sprint lookup is pm_list_sprints(status="active", brief=True)',
            "no pre-flight board or sprint read is unprojected",
        ]
    ), f"a half-projected pre-flight failed the wrong clauses: {failed}"


def test_the_plan_sweep_catches_a_planted_per_story_read():
    """The Phase 2 sweep must fire on the read it is looking for."""
    planted = (
        "## Phase 2 — Plan\n"
        "5. For each sprint story: `pm_get(story_id)` — the plan needs whole "
        "items.\n"
    )
    offenders = [
        args
        for args in PM_GET_CALL.findall(planted)
        if not FIELDS_LITERAL.search(args)
    ]
    assert offenders, "the plan-phase sweep missed a planted unprojected pm_get"


def test_the_plan_sweep_catches_an_unprojected_batch_call():
    """...and an unprojected batch read, which is cheaper but still whole."""
    planted = "5. `pm_batch_get(ids=<sprint story ids>)` — the sprint's stories.\n"
    calls = [args for args in PM_BATCH_GET_CALL.findall(planted) if "ids=" in args]
    assert calls and not FIELDS_LITERAL.search(calls[0]), (
        "the batch-read check would pass an unprojected pm_batch_get"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
