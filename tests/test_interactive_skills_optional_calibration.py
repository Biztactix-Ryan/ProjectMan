"""US-PM-26 — calibration is a mandate only under the orchestrator.

Acceptance criteria pinned here:

* "Interactive skill templates no longer require ``pm_estimate`` before writing
  points" — the interactive documents may *offer* the tool, but no sentence in
  them may sequence it in front of a ``points`` write.
* "The orchestrate skill still mandates the once-per-run bounded ``pm_context``"
  — the run-scoped rules that pay for themselves under an orchestrator are not
  collateral damage of the interactive relaxation.

Why a regex over prose rather than a wording snapshot: the mandate was never one
sentence.  It lived as a routing-bullet imperative ("Run the ``pm_estimate``
calibration step ... first"), as a numbered two-step section ("Step 1 —
Calibrate", "Step 2 — Size and write"), and as an agent-workflow clause ("this
step runs before any ``points`` value is written").  Any of the three coming
back re-imposes the round trip the story removes, so the assertion is stated
against the *shape* — an ordering word bound to ``pm_estimate`` or to a
``points`` write — and every phrasing that existed before US-PM-26-4 is kept in
``PRE_US_PM_26_MANDATES`` as a regression corpus for the regexes themselves.

Document scope.  ``skill_*.j2`` templates split three ways and every one must be
accounted for (``test_every_skill_template_is_classified``), so a new skill
cannot quietly escape the rule:

* INTERACTIVE — ``/pm``, ``/pm-plan``, ``/pm-do``, ``/pm-autoscope`` and the
  ``pm`` agent.  Mandate-free.  ``/pm-autoscope`` joined the set in US-PM-26-5:
  its calibration is genuinely worth more in bulk (one call per size band across
  dozens of proposed items, still pinned by ``test_skill_guidance_tools.py``),
  but "worth more" is an argument for offering it, not for gating every
  ``points`` write behind it — and the gate was the thing the story removes.
* ``skill_pm_orchestrate.md.j2`` — keeps its run-scoped rules; asserted, not
  exempted.

Both the template (source of truth) and the tracked rendered copy are checked:
the templates carry no Jinja variables, so the rendered ``SKILL.md`` is a byte
copy, and a mandate deleted from only one of the two would still ship.
"""

import re

import pytest

from tests.test_skill_release_instructions import (
    REPO_ROOT,
    RENDERED_SKILLS,
    TEMPLATES,
    _skill_templates,
)
from tests.test_skill_verdict_verbs import _text

#: interactive documents: template → tracked rendered copy
INTERACTIVE_DOCS = {
    "pm": (TEMPLATES / "skill_pm.md.j2", RENDERED_SKILLS / "pm" / "SKILL.md"),
    "pm-plan": (
        TEMPLATES / "skill_pm_plan.md.j2",
        RENDERED_SKILLS / "pm-plan" / "SKILL.md",
    ),
    "pm-do": (TEMPLATES / "skill_pm_do.md.j2", RENDERED_SKILLS / "pm-do" / "SKILL.md"),
    "pm-autoscope": (
        TEMPLATES / "skill_pm_autoscope.md.j2",
        RENDERED_SKILLS / "pm-autoscope" / "SKILL.md",
    ),
    "agent-pm": (
        TEMPLATES / "agent_pm.md.j2",
        REPO_ROOT / ".claude" / "agents" / "pm.md",
    ),
}

#: interactive documents that carry an estimation step at all.  ``/pm-do``
#: executes an already-sized task and names no estimation tool; asserting it
#: mentions ``pm_estimate`` would invent a requirement the story never made.
ESTIMATING_DOCS = ["pm", "pm-plan", "pm-autoscope", "agent-pm"]

#: templates deliberately outside the interactive set, with the reason
OUT_OF_SCOPE = {
    "skill_pm_orchestrate.md.j2": "keeps its run-scoped mandates (asserted below)",
    "skill_pm_status.md.j2": "read-only reporting: writes no points",
    "skill_pm_cleanup.md.j2": "archiving: writes no points",
    "skill_pm_next.md.j2": "scratch note read/write: not a backlog item, writes no points",
}

PM_ESTIMATE_CALL = re.compile(r"\bpm_estimate\b")

#: A mandate is an ordering/obligation word bound to the calibration call or to
#: the ``points`` write it used to gate.  Each pattern is justified by a real
#: phrasing that shipped before US-PM-26-4 (see ``PRE_US_PM_26_MANDATES``).
MANDATE_PATTERNS = [
    # "this step runs before any `points` value is written"
    re.compile(r"before\s+(?:any|the|writing|a)\b[^.\n]{0,60}\bpoints\b", re.I),
    # "Run the `pm_estimate` calibration step ... first"
    re.compile(r"\b(?:run|call|use)\b[^.\n]{0,80}pm_estimate[^.\n]{0,80}\bfirst\b", re.I),
    re.compile(r"pm_estimate[^.\n]{0,80}\b(?:first|beforehand|up front)\b", re.I),
    re.compile(r"\b(?:first|before)\b[^.\n]{0,80}pm_estimate", re.I),
    # "must / has to / always call pm_estimate", "do not skip"
    re.compile(r"\b(?:must|shall|have to|has to|always|required to)\b[^.\n]{0,80}pm_estimate", re.I),
    re.compile(r"pm_estimate[^.\n]{0,80}\bis (?:required|mandatory)\b", re.I),
    re.compile(r"\bdo not skip\b[^.\n]{0,80}(?:step|calibrat)", re.I),
    # "Step 1 — Calibrate", "has two named steps in front of it"
    re.compile(r"Step\s*1\s*[—:-]\s*Calibrat", re.I),
    re.compile(r"\bsteps?\s+in front of\b", re.I),
    # "every operation that writes a `points` value ... has ... in front"
    re.compile(r"calibrate (?:each|every|before)\b", re.I),
]

#: The phrasings that shipped before US-PM-26-4.  They exist so the regexes are
#: tested against real text rather than trusted: if a pattern stops matching the
#: mandate it was written for, the pattern is broken, not the templates.
PRE_US_PM_26_MANDATES = [
    "writing `points=`? Run the `pm_estimate` calibration step (**Estimation**, below) first",
    "### Estimation — calibrate before writing points",
    "- **Step 1 — Calibrate: `pm_estimate(<id>)`.** Call it on the item being sized.",
    "Do not skip step 1 and invent a number.",
    "6. **Estimate** — `pm_estimate(id)` for point calibration; this step runs "
    "before any `points` value is written (create, update, or after auto-scope)",
    "propose task breakdown, calibrate each estimate with `pm_estimate(<id>)`",
    "Every operation that writes a `points` value ... has two named steps in front of it:",
    # /pm-autoscope's two workflow gates, removed by US-PM-26-5
    "10. **Calibrate: `pm_estimate(<id>)`** — see *Estimation in bulk* below — "
    "before any `points` value is written",
    "   d. **Calibrate: `pm_estimate(<id>)`** — see *Estimation in bulk* below — "
    "before any `points` value is written",
    "With many items, call `pm_estimate` on the representative (first) story of "
    "each size band you are proposing rather than on every item",
]

#: the orchestrator's once-per-run bounded context rule, verbatim
ORCHESTRATE_BOUNDED_CONTEXT = (
    "`pm_context(max_doc_chars=2000, limit=5)` **once per run**"
)

ORCHESTRATE_DOCS = [
    pytest.param(TEMPLATES / "skill_pm_orchestrate.md.j2", id="orchestrate-template"),
    pytest.param(RENDERED_SKILLS / "pm-orchestrate" / "SKILL.md", id="orchestrate-rendered"),
]


def _docs(names) -> list:
    """Template + rendered copy of each named interactive document."""
    params = []
    for name in names:
        template, rendered = INTERACTIVE_DOCS[name]
        params.append(pytest.param(template, id=f"{name}-template"))
        params.append(pytest.param(rendered, id=f"{name}-rendered"))
    return params


ALL_INTERACTIVE = _docs(INTERACTIVE_DOCS)
ALL_ESTIMATING = _docs(ESTIMATING_DOCS)


def _mandates(text: str) -> list[str]:
    """Every line of ``text`` that reads as a calibrate-before-points mandate."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for pattern in MANDATE_PATTERNS:
            if pattern.search(line):
                hits.append(f"{n}: {line.strip()}  [matched {pattern.pattern!r}]")
                break
    return hits


@pytest.mark.parametrize("mandate", PRE_US_PM_26_MANDATES)
def test_the_mandate_regexes_match_the_wording_they_replaced(mandate):
    """Guard the guard: each pre-US-PM-26 phrasing must trip a pattern."""
    assert _mandates(mandate), (
        f"no MANDATE_PATTERNS entry matches a phrasing that really shipped: {mandate!r} — "
        "the regexes have drifted and would pass a restored mandate"
    )


@pytest.mark.parametrize("path", ALL_INTERACTIVE)
def test_interactive_docs_do_not_require_calibration_before_points(path):
    """AC: interactive templates no longer require pm_estimate before points."""
    hits = _mandates(_text(path))
    assert not hits, (
        f"{path.name}: sequences calibration in front of a points write — "
        "interactive estimation is set-directly, calibration optional:\n  "
        + "\n  ".join(hits)
    )


@pytest.mark.parametrize("path", ALL_ESTIMATING)
def test_interactive_estimation_docs_still_offer_pm_estimate(path):
    """Optional is not deleted: the tool stays discoverable where sizing happens."""
    assert PM_ESTIMATE_CALL.search(_text(path)), (
        f"{path.name}: no longer mentions pm_estimate — the calibration became "
        "unreachable instead of optional"
    )


@pytest.mark.parametrize("name", ESTIMATING_DOCS)
def test_interactive_template_and_rendered_copy_stay_identical(name):
    """The templates hold no Jinja variables; a one-sided edit would still ship."""
    template, rendered = INTERACTIVE_DOCS[name]
    assert _text(template) == _text(rendered), (
        f"{template.name} and {rendered} have diverged — update both"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_keeps_its_once_per_run_bounded_context(path):
    """AC: the orchestrate skill still mandates the bounded, once-per-run context."""
    text = _text(path)
    assert ORCHESTRATE_BOUNDED_CONTEXT in text, (
        f"{path.name}: lost the once-per-run bounded pm_context rule "
        f"({ORCHESTRATE_BOUNDED_CONTEXT!r})"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_is_not_swept_up_by_the_interactive_relaxation(path):
    """The orchestrate document is out of the interactive set, on purpose.

    US-PM-26 relaxes the interactive documents only.  This pins the boundary:
    the orchestrate skill is never a member of ``INTERACTIVE_DOCS``, so no
    future edit can silently move it there and delete its run-scoped rules by
    parametrization.
    """
    members = {p for pair in INTERACTIVE_DOCS.values() for p in pair}
    assert path not in members, f"{path.name} is being checked as an interactive doc"


def test_every_skill_template_is_classified():
    """No skill/agent template may sit outside both buckets unnoticed."""
    interactive = {t.name for t, _ in INTERACTIVE_DOCS.values()}
    unclassified = [
        p.name
        for p in _skill_templates()
        if p.name not in interactive and p.name not in OUT_OF_SCOPE
    ]
    assert not unclassified, (
        "skill templates classified neither interactive nor out-of-scope: "
        f"{unclassified} — add each to INTERACTIVE_DOCS (and it must then be "
        "mandate-free) or to OUT_OF_SCOPE with the reason"
    )
