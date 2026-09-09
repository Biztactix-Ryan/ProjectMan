"""US-PM-50-4 — pm-plan must run the long-task check before it activates.

Story US-PM-50 is about tasks that outlive the orchestrator's one-hour prompt
cache.  The signal is computed in ``durations.long_task_risk`` and handed to
the planner by ``pm_get_sprint`` as ``long_task_risk``; a signal nobody reads
changes nothing, so the acceptance criterion pinned here is —

    "The pm-plan skill runs the long-task check before activating a sprint and
    offers to re-scope flagged tasks"

— and US-PM-50-11 made the change, as Phase 4's "Long-task check" step, sitting
between ``pm_create_sprint`` and the ``pm_update_sprint(status="active")`` that
starts the sprint.  This module holds the criterion, clause by clause, on that
Phase 4 section.

The clauses are scoped to the *section*, not to the check step alone, because
the load-bearing half of the criterion is an ordering: the check is worth
nothing if it sits after activation, when re-scoping is already too late.  That
ordering is pinned by character position in the section text rather than by
step numbers, so inserting a step anywhere in Phase 4 cannot silently satisfy
it.

Three documents are checked: the Jinja template (source of truth), the tracked
rendered ``.claude/skills/pm-plan/SKILL.md`` (what a planning agent actually
loads) and a live render of the template, so a template edit that never
survives the renderer is caught too.

Two tests look past the clause table, into real code: every store tool the
check names must be a registered MCP tool, the entry fields it promises must be
the fields ``durations.long_task_risk`` actually emits, and the ceiling in its
worked example must be this project's default ``max_task_minutes``.  A step
that lists ``p99`` or a ceiling of 90 would read fine and be wrong.

The last tests are falsification guards — the pre-US-PM-50-11 Phase 4, which
activated with no check at all; a vague "watch out for slow tasks" note; and a
near-miss that runs the whole check *after* activation — are pushed through the
same clause table.  A checklist that never fires is not evidence.

Nothing here writes: the criterion is a property of templates this task must
not modify.
"""

import inspect
import re

import anyio
import pytest

from projectman.cli import _render_template
from projectman.config import max_task_minutes
from projectman.durations import long_task_risk
from tests.test_skill_release_instructions import RENDERED_SKILLS, TEMPLATES
from tests.test_skill_verdict_verbs import _text

PLAN_TEMPLATE_NAME = "skill_pm_plan.md.j2"
PLAN_TEMPLATE = TEMPLATES / PLAN_TEMPLATE_NAME
PLAN_SKILL = RENDERED_SKILLS / "pm-plan" / "SKILL.md"

# ─── the vocabulary of the criterion ─────────────────────────────

#: the key the check reads, and the tool that returns it
LONG_TASK_RISK = re.compile(r"`?long_task_risk`?")
PM_GET_SPRINT = re.compile(r"\bpm_get_sprint\s*\(")

#: the call that starts the sprint — what the check must precede
ACTIVATE = re.compile(
    r"pm_update_sprint\([^)]*status\s*=\s*[\"']active[\"']", re.IGNORECASE
)

#: the numbers a flagged entry is reported with
P90 = re.compile(r"`?p90`?", re.IGNORECASE)
CEILING = re.compile(r"\bceiling\b|`?max_task_minutes`?|\bthreshold\b", re.IGNORECASE)
LISTS = re.compile(r"\blist(?:s|ed|ing)?\b|\bshow(?:s|n)?\b|\breport(?:s|ed)?\b", re.I)

#: the offer the criterion demands
OFFERS = re.compile(r"\boffer(?:s|ed|ing)?\b|\bask(?:s|ed)?\b|\bpropose(?:s|d)?\b", re.I)
RESCOPE = re.compile(r"\bre-?scope(?:s|d|ing)?\b|\bsplit(?:s|ting)?\b|\bbreak\b", re.I)
SMALLER = re.compile(r"\bsmaller\b|\bfiner\b|\bsub-?tasks?\b", re.IGNORECASE)
PM_SCOPE = re.compile(r"\bpm_scope\s*\(")
BEFORE_ACTIVATING = re.compile(
    r"\bbefore\s+(?:activat\w+|starting|it goes active|the sprint (?:goes|is) active)\b",
    re.IGNORECASE,
)

#: the one-line rationale — why an hour is the line that matters
HOUR = re.compile(r"\bhour\b|\b60\s*(?:min\b|minutes\b)", re.IGNORECASE)
CACHE = re.compile(r"\bcach\w+\b", re.IGNORECASE)
PREFIX_REWRITE = re.compile(
    r"\bprefix\b[^.\n]{0,30}\bre-?writ\w+|\bre-?writ\w+[^.\n]{0,30}\bprefix\b",
    re.IGNORECASE,
)

#: the empty case, and what to do with it
EMPTY = re.compile(
    r"\bempty\s+list\b|\bnothing\s+(?:is\s+)?flagged\b|\bno\s+flagged\b"
    r"|\bno\s+entries\b|\bempty\b",
    re.IGNORECASE,
)
MOVE_ON = re.compile(
    r"\bmove on\b|\bsay so\b|\bcarry on\b|\bproceed\b|\bcontinue\b|\bnothing to do\b",
    re.IGNORECASE,
)

#: the entry fields the step promises a caller will find
FIELD = re.compile(r"`([a-z_][a-z0-9_]*)`")

#: the tools the check step is allowed to name
NAMED_TOOL = re.compile(r"\b(pm_[a-z_]+)\s*\(")


# ─── the slices ──────────────────────────────────────────────────


def _phase_4(text: str) -> str:
    """The ``## Phase 4`` section, up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("## Phase 4")]
    assert starts, "no '## Phase 4' section — the persist-and-activate phase vanished"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _numbered_steps(section: str) -> list[str]:
    """Every numbered step of a section, sub-bullets and wrapped prose kept."""
    lines = section.splitlines()
    starts = [n for n, line in enumerate(lines) if re.match(r"^\d+(?:-\d+)?\.\s", line)]
    steps = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        steps.append("\n".join(lines[start:end]).strip())
    return steps


def _check_step(section: str) -> str:
    """Phase 4's long-task check — the step that reads ``long_task_risk``.

    Located by what it does, never by its number: US-PM-50-11 inserted it as
    step 9 and a later step could shift it without weakening the criterion.
    Returns ``""`` when no step reads the key, so every clause below fails on
    a Phase 4 that never runs the check.
    """
    hits = [step for step in _numbered_steps(section) if LONG_TASK_RISK.search(step)]
    return hits[0] if hits else ""


# ─── clause table ────────────────────────────────────────────────
#
# Every clause takes the whole Phase 4 section: the ordering clause needs the
# activation call, which lives in a different step.  Iterated by the tests
# *and* by the falsification guards, so a clause cannot be checked in one place
# and quietly dropped from the other.


def _reads_long_task_risk_from_the_sprint(section: str) -> bool:
    step = _check_step(section)
    return bool(step and PM_GET_SPRINT.search(step) and LONG_TASK_RISK.search(step))


def _runs_before_activation(section: str) -> bool:
    """Pinned by position in the text, not by step numbers."""
    step = _check_step(section)
    if not step:
        return False
    activation = ACTIVATE.search(section)
    if not activation:
        return False
    return section.index(step) < activation.start()


def _lists_flagged_tasks_with_p90_and_ceiling(section: str) -> bool:
    step = _check_step(section)
    return bool(step and LISTS.search(step) and P90.search(step) and CEILING.search(step))


def _offers_to_rescope_before_activating(section: str) -> bool:
    step = _check_step(section)
    return bool(
        step
        and OFFERS.search(step)
        and RESCOPE.search(step)
        and SMALLER.search(step)
        and PM_SCOPE.search(step)
        and BEFORE_ACTIVATING.search(step)
    )


def _gives_the_one_line_rationale(section: str) -> bool:
    step = _check_step(section)
    return bool(
        step and HOUR.search(step) and CACHE.search(step) and PREFIX_REWRITE.search(step)
    )


def _handles_the_empty_list(section: str) -> bool:
    step = _check_step(section)
    return bool(step and EMPTY.search(step) and MOVE_ON.search(step))


CLAUSES = {
    "reads long_task_risk off pm_get_sprint": _reads_long_task_risk_from_the_sprint,
    "runs before the activation call": _runs_before_activation,
    "lists flagged tasks with band p90 and the ceiling": (
        _lists_flagged_tasks_with_p90_and_ceiling
    ),
    "offers to re-scope via pm_scope before activating": (
        _offers_to_rescope_before_activating
    ),
    "gives the hour / prompt-cache / prefix-rewrite rationale": (
        _gives_the_one_line_rationale
    ),
    "handles the empty list": _handles_the_empty_list,
}


# ─── the documents ───────────────────────────────────────────────

SOURCES = {
    "template": lambda: _text(PLAN_TEMPLATE),
    "rendered": lambda: _text(PLAN_SKILL),
    "live-render": lambda: _render_template(PLAN_TEMPLATE_NAME),
}


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_check_step_is_extractable(source):
    """Guard the slice: every clause below is scoped to this text."""
    text = SOURCES[source]()
    assert "template not found" not in text, "the template failed to render"
    section = _phase_4(text)
    step = _check_step(section)
    assert step, f"no Phase 4 step reads `long_task_risk`:\n\n{section}"
    assert re.match(r"^\d+(?:-\d+)?\.\s", step), "the slice is not a numbered step"
    assert len(step) > 120, "the check lost its body — a bare call carries no offer"
    assert ACTIVATE.search(section), (
        f"Phase 4 no longer activates the sprint — ordering is unpinnable:\n\n{section}"
    )


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_pm_plan_checks_for_long_tasks_before_activating(source, clause):
    """The acceptance criterion, one clause per case, on all three documents."""
    section = _phase_4(SOURCES[source]())
    assert CLAUSES[clause](section), (
        f"pm-plan Phase 4 fails: {clause}\n\n{section}"
    )


# ─── past the clause table: the check must match the code ────────


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_every_tool_the_check_names_is_a_registered_tool(source):
    """A step that calls a tool nobody serves is an instruction to fail."""
    from projectman.server import mcp as mcp_server

    registered = {tool.name for tool in anyio.run(mcp_server.list_tools)}
    step = _check_step(_phase_4(SOURCES[source]()))
    named = set(NAMED_TOOL.findall(step))
    assert named, f"the check names no store tool at all:\n\n{step}"
    assert {"pm_get_sprint", "pm_scope"} <= named, (
        f"the check must name both pm_get_sprint and pm_scope, named {sorted(named)}"
    )
    unknown = sorted(name for name in named if name not in registered)
    assert not unknown, f"the check names unregistered tools: {unknown}"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_entry_fields_the_check_promises_are_the_fields_emitted(source):
    """``id``, ``points``, ``p50``, ``p90``, ``max_task_minutes`` — really.

    The step tells the planner what every entry carries; if ``long_task_risk``
    stopped emitting one of them the planner would report a blank.
    """
    step = _check_step(_phase_4(SOURCES[source]()))
    carries = re.search(r"carries([^.]*)\.", step)
    assert carries, f"the check no longer says what an entry carries:\n\n{step}"
    promised = set(FIELD.findall(carries.group(1)))
    assert promised, f"no entry fields named:\n\n{carries.group(0)}"
    emitted = set(re.findall(r"\"([a-z_][a-z0-9_]*)\"\s*:", inspect.getsource(long_task_risk)))
    missing = sorted(field for field in promised if field not in emitted)
    assert not missing, (
        f"the check promises fields long_task_risk never emits: {missing} "
        f"(emitted: {sorted(emitted)})"
    )


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_worked_example_uses_this_projects_ceiling(source):
    """The "ceiling 60 min" in the example is the real default, not a guess."""
    step = _check_step(_phase_4(SOURCES[source]()))
    default = max_task_minutes(None)
    example = re.search(r"ceiling\s+(\d+(?:\.\d+)?)\s*min", step, re.IGNORECASE)
    assert example, f"the check shows no worked ceiling:\n\n{step}"
    assert float(example.group(1)) == default, (
        f"the example ceiling {example.group(1)} is not the default {default:g}"
    )


# ─── falsification guards ────────────────────────────────────────

#: Phase 4 exactly as it stood before US-PM-50-11 — activation, no check.
BEFORE = """## Phase 4 — Persist and activate

8. `pm_create_sprint` with name, goal, start/end dates, and the planned story IDs.
9. Set it active (`pm_update_sprint(id, status="active")`) unless the user wants to start later.
10. Summarize: sprint ID, goal, stories with points vs. velocity, dependency order, and flagged risks (cross-sprint dependencies, unestimated leftovers).
11. Suggest the natural next step: "Run it with `/pm-orchestrate`" or "grab the first task with `/pm-do <id>`".
"""

#: prose that sounds careful and pins nothing
VAGUE = """## Phase 4 — Persist and activate

8. `pm_create_sprint` with name, goal, start/end dates, and the planned story IDs.
9. Watch out for tasks that look slow — a long sprint task can hurt the run, so
   consider splitting anything that seems large before you go.
10. Set it active (`pm_update_sprint(id, status="active")`) unless the user wants to start later.
"""

#: the whole check, word for word — but after the sprint is already running
TOO_LATE = """## Phase 4 — Persist and activate

8. `pm_create_sprint` with name, goal, start/end dates, and the planned story IDs.
9. Set it active (`pm_update_sprint(id, status="active")`) unless the user wants to start later.
10. Long-task check — `pm_get_sprint(id)` and read `long_task_risk` before activating. A task that runs past the hour outlives the orchestrator's prompt cache (one-hour TTL), so the next dispatch pays a full prefix rewrite.
   - Every entry carries `id`, `points`, `p50`, `p90` and `max_task_minutes`. List them: "US-PRJ-12-3 (3 pts) — band p90 88 min, ceiling 60 min".
   - Offer to re-scope each flagged task into smaller tasks with `pm_scope(story_id)` before activating; the user can also accept the risk and go as planned.
   - An empty list means nothing is flagged (or the history is too thin to judge) — say so and move on.
"""


def test_the_clause_checks_reject_the_phase_before_the_check():
    """Falsification guard: the pre-US-PM-50-11 Phase 4 must fail every clause."""
    failed = [name for name, check in CLAUSES.items() if not check(BEFORE)]
    assert failed == list(CLAUSES), (
        "the un-checked Phase 4 passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


def test_the_clause_checks_reject_a_vague_slow_task_note():
    """Falsification guard: no key, no numbers, no offer — nothing to act on."""
    failed = [name for name, check in CLAUSES.items() if not check(VAGUE)]
    assert failed == list(CLAUSES), (
        "a vague slow-task note passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


def test_the_ordering_clause_rejects_a_check_placed_after_activation():
    """Falsification guard, and the discrimination proof for the ordering clause.

    Every other clause passes on this text — the words are the shipped step's
    own — so a failure here can only be the position of the check relative to
    the activation call, which is exactly the half of the criterion that makes
    it worth anything.
    """
    assert not _runs_before_activation(TOO_LATE), (
        "a check placed after `pm_update_sprint(status=\"active\")` was accepted "
        "as running before activation"
    )
    others = {
        name: check(TOO_LATE)
        for name, check in CLAUSES.items()
        if check is not _runs_before_activation
    }
    assert all(others.values()), (
        "the guard is not isolating the ordering clause; also failed: "
        f"{[name for name, ok in others.items() if not ok]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
