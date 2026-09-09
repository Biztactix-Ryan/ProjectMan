"""US-PM-26 — the session-start ``pm_context`` fetch is a pointer, not a ritual.

Acceptance criteria pinned here:

* "Interactive skill and agent templates no longer require ``pm_context`` at
  session start" — the interactive documents may *point at* the tool, but no
  sentence in them may make calling it the opening move of a session.
* "The orchestrate skill still mandates the once-per-run bounded ``pm_context``
  and refuses unestimated sprint content by directing to ``/pm-plan``" — the
  run-scoped rules that pay for themselves under an orchestrator are not
  collateral damage of the interactive relaxation.  The ``/pm-plan`` refusal is
  pinned unchanged; the fetch half was **superseded by US-PM-49-6**, which
  removed it from the orchestrator once US-PM-49-7 had removed the excerpt it
  fed, so the assertion here is inverted rather than dropped — the boundary the
  criterion drew is still pinned, it just now runs the other way.

The same boundary covers the other run-scoped block US-PM-48 added: the
**Validator Prompt Template** and its bounded JSON verdict.  Its clauses are
pinned in ``tests/test_orchestrate_validator_prompt.py`` and its size budget in
``tests/test_orchestrate_skill_size.py``; both are imported below rather than
restated, so what is asserted here is only that a relaxation sweep never
reaches them.

Why the fetch was mandatory in the first place, and why that stopped being
right.  ``pm_context`` earns its cost when one call is amortised across a whole
sprint of worker dispatches: ``/pm-orchestrate`` fetched it once, bounded, and
pasted the excerpt into every worker prompt (until US-PM-49-7 dropped the paste
and US-PM-49-6 the fetch).  Interactively there was never anything to
amortise — a session that answers "what should I work on?" pays a hub-wide
document read for an answer ``pm_board`` already holds, and ``pm_grab`` and
``pm_get`` carry the item context on their own.  The telemetry bears that out:
``pm_context`` sat at 8/1/1/0 calls across four studies, because a tool named
only as a preamble is a tool nobody reaches.

Why a regex over prose rather than a wording snapshot: the mandate was never one
sentence.  It lived as the first item of the agent's Core Workflow ("1.
**Context** — ``pm_context(project)`` to load hub + project docs + active
work"), as a standalone imperative in the context-hierarchy section ("Use
``pm_context(project)`` at the start of any work session"), and as a numbered
token-discipline rule in the reference doc.  Any of those coming back re-imposes
the round trip the story removes, so the assertion is stated against the
*shape* — a session-start obligation bound to ``pm_context`` — and every
phrasing that shipped before US-PM-26-5 is kept in
``PRE_US_PM_26_CONTEXT_MANDATES`` as a regression corpus for the regexes.

Relaxed is not deleted.  ``skill_pm`` and ``agent_pm`` must still name the tool
*with its bounds* (``max_doc_chars``/``limit``): an unbounded ``pm_context``
returned 48,588 chars in one study, so a pointer that drops the arguments points
at the expensive call, and a pointer deleted altogether just makes the guidance
unreachable again.

Both the template (source of truth) and the tracked rendered copy are checked:
the templates carry no Jinja variables, so the rendered ``SKILL.md`` is a byte
copy, and a mandate deleted from only one of the two would still ship.
"""

import re

import pytest

from tests.test_orchestrate_skill_size import MAX_CHARS, _within_limit
from tests.test_orchestrate_validator_prompt import (
    REQUIRED_KEYS as VALIDATOR_KEYS,
    _validator_fence,
)
from tests.test_skill_release_instructions import (
    REPO_ROOT,
    RENDERED_SKILLS,
    TEMPLATES,
    _skill_templates,
)
from tests.test_skill_verdict_verbs import _text

#: every document the interactive relaxation covers: template → rendered copy
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
    "pm-status": (
        TEMPLATES / "skill_pm_status.md.j2",
        RENDERED_SKILLS / "pm-status" / "SKILL.md",
    ),
    "pm-cleanup": (
        TEMPLATES / "skill_pm_cleanup.md.j2",
        RENDERED_SKILLS / "pm-cleanup" / "SKILL.md",
    ),
    "pm-next": (
        TEMPLATES / "skill_pm_next.md.j2",
        RENDERED_SKILLS / "pm-next" / "SKILL.md",
    ),
    "agent-pm": (
        TEMPLATES / "agent_pm.md.j2",
        REPO_ROOT / ".claude" / "agents" / "pm.md",
    ),
}

#: the documents that must keep a bounded pointer at the tool.  ``/pm`` routes
#: the ``context`` command and the agent describes the hub→project hierarchy;
#: the other interactive documents never named the tool as a step, so demanding
#: one from them would invent a requirement the story never made.
POINTING_DOCS = ["pm", "agent-pm"]

#: templates deliberately outside the interactive set, with the reason
OUT_OF_SCOPE = {
    "skill_pm_orchestrate.md.j2": (
        "run-scoped, not interactive; its once-per-run fetch was dropped "
        "outright by US-PM-49-6 (asserted below)"
    ),
}

#: ``pm_context(...)``, with its argument list captured
PM_CONTEXT_CALL = re.compile(r"\bpm_context\(([^)]*)\)")

#: a numbered first step: "1. ", "1) "
FIRST_STEP = re.compile(r"^\s*1[.)]\s")

#: A session-start mandate is an opening-move or obligation phrase bound to the
#: context fetch.  Each pattern is justified by a phrasing that really shipped
#: (see ``PRE_US_PM_26_CONTEXT_MANDATES``).
MANDATE_PATTERNS = [
    # "Use `pm_context(project)` at the start of any work session"
    re.compile(r"pm_context[^.\n]{0,80}\bat the (?:very )?start of\b", re.I),
    re.compile(r"\bat the (?:very )?start of\b[^.\n]{0,80}pm_context", re.I),
    # the phrase itself, wherever it sits
    re.compile(r"\bstart of (?:any|every|each|the) (?:work )?session\b", re.I),
    re.compile(r"\b(?:begin|start) (?:any|every|each) session\b", re.I),
    # "Step 1 — Context: `pm_context(project)`"
    re.compile(r"\bstep\s*1\b[^.\n]{0,80}pm_context", re.I),
    # "always / must / required to call pm_context"
    re.compile(
        r"\b(?:must|shall|always|have to|has to|required to)\b[^.\n]{0,80}pm_context",
        re.I,
    ),
    re.compile(r"pm_context[^.\n]{0,80}\bis (?:required|mandatory)\b", re.I),
    # "call `pm_context` before starting work"
    re.compile(
        r"pm_context[^.\n]{0,80}\bbefore (?:starting|beginning|you start|any work)\b",
        re.I,
    ),
    re.compile(
        r"\bbefore (?:starting|beginning|you start|any work)\b[^.\n]{0,80}pm_context",
        re.I,
    ),
]

#: The phrasings that shipped before US-PM-26-5.  They exist so the regexes are
#: tested against real text rather than trusted: if a pattern stops matching the
#: mandate it was written for, the pattern is broken, not the templates.
PRE_US_PM_26_CONTEXT_MANDATES = [
    "1. **Context** — `pm_context(project)` to load hub + project docs + active work",
    "Use `pm_context(project)` at the start of any work session to get the full picture.",
    "1. **Fetch context** via `pm_context` — get combined hub + project context",
    "Always call `pm_context` before starting work.",
    "**Step 1 — Context: `pm_context(project)`.**",
    "You must call `pm_context(project)` at the beginning of the session.",
]

#: the orchestrator's run-scoped rules, verbatim as they read today
ORCHESTRATE_PLAN_REFUSAL = "**No scoping or planning** (→ `/pm-plan`)"

ORCHESTRATE_DOCS = [
    pytest.param(TEMPLATES / "skill_pm_orchestrate.md.j2", id="orchestrate-template"),
    pytest.param(
        RENDERED_SKILLS / "pm-orchestrate" / "SKILL.md", id="orchestrate-rendered"
    ),
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
ALL_POINTING = _docs(POINTING_DOCS)


def _mandates(text: str) -> list[str]:
    """Every line of ``text`` that reads as a session-start context mandate."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if FIRST_STEP.match(line) and "pm_context" in line:
            hits.append(f"{n}: {line.strip()}  [matched: numbered first step]")
            continue
        for pattern in MANDATE_PATTERNS:
            if pattern.search(line):
                hits.append(f"{n}: {line.strip()}  [matched {pattern.pattern!r}]")
                break
    return hits


@pytest.mark.parametrize("mandate", PRE_US_PM_26_CONTEXT_MANDATES)
def test_the_mandate_regexes_match_the_wording_they_replaced(mandate):
    """Guard the guard: each pre-US-PM-26 phrasing must trip a pattern."""
    assert _mandates(mandate), (
        f"no MANDATE_PATTERNS entry matches a phrasing that really shipped: {mandate!r} — "
        "the regexes have drifted and would pass a restored mandate"
    )


@pytest.mark.parametrize("path", ALL_INTERACTIVE)
def test_interactive_docs_do_not_require_context_at_session_start(path):
    """AC: interactive templates no longer require pm_context at session start."""
    hits = _mandates(_text(path))
    assert not hits, (
        f"{path.name}: makes pm_context the opening move of a session — "
        "interactively the fetch is a pointer, not a preamble:\n  "
        + "\n  ".join(hits)
    )


@pytest.mark.parametrize("path", ALL_POINTING)
def test_pointing_docs_still_name_pm_context_with_its_bounds(path):
    """Optional is not deleted, and a pointer without bounds points at 48k chars."""
    calls = PM_CONTEXT_CALL.findall(_text(path))
    assert calls, (
        f"{path.name}: no longer calls pm_context() — the brief became "
        "unreachable instead of optional"
    )
    bounded = [
        args
        for args in calls
        if "max_doc_chars=" in args.replace(" ", "") and "limit=" in args.replace(" ", "")
    ]
    assert bounded, (
        f"{path.name}: every pm_context() call is unbounded {calls} — the pointer "
        "must name max_doc_chars= and limit=, as /pm-orchestrate's does"
    )


@pytest.mark.parametrize("name", INTERACTIVE_DOCS)
def test_interactive_template_and_rendered_copy_stay_identical(name):
    """The templates hold no Jinja variables; a one-sided edit would still ship."""
    template, rendered = INTERACTIVE_DOCS[name]
    assert _text(template) == _text(rendered), (
        f"{template.name} and {rendered} have diverged — update both"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_no_longer_fetches_a_per_run_context_at_all(path):
    """US-PM-49-6 supersedes US-PM-26's once-per-run pin for the orchestrator.

    US-PM-26 kept the fetch because one bounded read was amortised across every
    worker prompt of the run.  US-PM-49-7 removed the excerpt from those
    prompts, which removed the amortisation and left a read nothing downstream
    consumed — so the fetch itself went with US-PM-49-6.  The relaxation this
    module is about is unaffected: the tool is still reachable, and the
    documents that point at it must still bound the call
    (``test_pointing_docs_still_name_pm_context_with_its_bounds``).
    """
    calls = PM_CONTEXT_CALL.findall(_text(path))
    assert not calls, (
        f"{path.name}: still calls pm_context{calls} — the per-run brief was "
        "dropped by US-PM-49-6 once no worker prompt carried its excerpt"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_still_refuses_unscoped_work_by_directing_to_pm_plan(path):
    """AC: sprint content that still needs scoping or estimating goes to /pm-plan.

    The orchestrator runs a sprint; it does not size one.  Without this refusal
    the relaxation above reads as licence to estimate mid-run, which is the one
    place the calibrated number actually matters.
    """
    assert ORCHESTRATE_PLAN_REFUSAL in _text(path), (
        f"{path.name}: lost the refusal that sends unscoped/unestimated content "
        f"to /pm-plan ({ORCHESTRATE_PLAN_REFUSAL!r})"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_keeps_the_validator_prompt_and_its_json_verdict(path):
    """The validator block survives, in both the template and the rendered copy.

    US-PM-48 moved the status/diff/DoD checks into a validator subagent, and
    the whole saving depends on the *answer* being a bounded JSON object.  The
    helper and the key list come from
    ``tests/test_orchestrate_validator_prompt.py``, which owns the clause-level
    checks; the point here is that a document-wide edit cannot delete the block
    from one of the two documents and still pass.
    """
    fence = _validator_fence(_text(path))
    missing = [key for key in VALIDATOR_KEYS if f'"{key}"' not in fence]
    assert not missing, (
        f"{path.name}: the validator prompt's JSON verdict no longer names "
        f"{missing} — the orchestrator has nothing to map onto a verb"
    )


@pytest.mark.parametrize("path", ORCHESTRATE_DOCS)
def test_orchestrate_documents_stay_within_the_size_budget(path):
    """Both documents, not just the render, stay under the character budget.

    ``tests/test_orchestrate_skill_size.py`` pins the *rendered* text; the
    validator block was added with single-digit headroom, so the template file
    is pinned here too — an edit that lands only in the template is caught
    before it is ever rendered.
    """
    text = _text(path)
    assert _within_limit(text), (
        f"{path.name} is {len(text)} characters, {len(text) - MAX_CHARS} over "
        f"the {MAX_CHARS}-character budget"
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
        "free of a session-start context mandate) or to OUT_OF_SCOPE with the reason"
    )
