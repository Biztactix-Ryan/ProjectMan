"""US-PM-13 — the guidance tools must be named at the step that calls them.

Story US-PM-13's diagnosis: ``pm_context`` and ``pm_estimate`` are guidance
tools with near-zero usage (8/1/1/0 and 1/2/0/0 calls across four telemetry
studies) — not because the guidance is unwanted, but because a guidance tool
only gets called when it maps to a step someone explicitly takes.  ``pm_scope``
gets 28–40 calls for the same shape of guidance, because decomposition is a
named discrete activity.  So the fix lives in the skill files, and — as with
``test_skill_verdict_verbs.py``, ``test_skill_evidence.py`` and
``test_skill_release_instructions.py`` — a prose fix does not stay fixed on its
own.  This module pins the instruction sites.

The module is organised by acceptance criterion so the sibling tasks can add
their sections here without re-deriving helpers:

* ``pm_context (US-PM-13-1, narrowed by US-PM-49-7, dropped from the
  orchestrator by US-PM-49-6)`` — the worker prompt no longer carries an inline
  excerpt of the project brief and the orchestrator no longer fetches one per
  run; the worker's route to the docs is pinned on ``/pm-do`` instead, and the
  bound the tool must be called with is pinned on the docs that still point
  at it;
* ``pm_estimate (US-PM-13-2)`` — the scoping and estimation workflows consult it
  *before* writing points;
* ``every guidance tool has a named step (US-PM-13-3)`` — the criterion stated
  generically, over the derived guidance set and every skill/agent document, so
  it keeps holding as the wording pinned above is rewritten.  Two rules make
  that generic statement match what the criterion actually asks for: only the
  *call form* ``pm_<tool>(`` counts as mentioning a tool, and a *routing
  bullet* counts as a named step.  Both are argued at the section itself.

Helpers come from ``test_skill_verdict_verbs`` rather than being copied, so the
document set, the fence stripping and the registered-tool lookup stay defined in
exactly one place.  Both the template (source of truth) and the tracked rendered
``SKILL.md`` are checked — via the shared ``DOCS`` parametrization for the
orchestrator (whose byte-for-byte equality is already owned by
``test_skill_verdict_verbs.py``) and via ``ESTIMATION_DOCS`` for the four
estimation workflows, whose equality was unpinned until US-PM-13-2 and so is
asserted here.

Beyond the text, one test actually *runs* ``pm_context`` against oversized docs,
because a skill that advertises a bounded excerpt while the tool returns 48k
chars would satisfy every string assertion and still be a lie.
"""

import inspect
import re

import pytest
import yaml

from projectman.cli import _render_template
from tests.test_skill_release_instructions import (
    REPO_ROOT,
    RENDERED_SKILLS,
    TEMPLATES,
    _rendered_skills,
    _skill_templates,
)
from tests.test_skill_verdict_verbs import (
    DOCS,
    _fences,
    _schemas,
    _text,
)

# ─── shared helpers (used by every section below) ────────────────

#: a numbered step or a markdown heading — the boundary of a step block
STEP_OR_HEADING = re.compile(r"^(?:#{1,6} |\d+[a-z]?\. )")


def _step(text: str, prefix: str) -> str:
    """The block of the step whose line starts with ``prefix`` (e.g. ``"4b."``).

    Runs to the next numbered step or markdown heading, so a step keeps its
    continuation lines but never absorbs its successor.
    """
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(prefix)]
    assert starts, f"no line starting with {prefix!r} — that step vanished"
    start = starts[0]
    end = next(
        (
            n
            for n in range(start + 1, len(lines))
            if STEP_OR_HEADING.match(lines[n])
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _worker_fence(text: str) -> str:
    """The Worker Prompt Template's fenced block — the text a worker receives."""
    blocks = [f for f in _fences(text) if "You are executing a single ProjectMan task" in f]
    assert len(blocks) == 1, (
        f"expected exactly one worker prompt fence, found {len(blocks)}"
    )
    return blocks[0]


# ═══ pm_context (US-PM-13-1) ════════════════════════════════════
#
# AC: "The worker prompt template includes project architecture context."
# Delivered by US-PM-13-5: pre-flight step 4b fetches a bounded pm_context once
# per run, and the worker prompt fence carried the excerpt in a "Project
# context" section plus a rule letting the worker fetch more itself.
#
# US-PM-49-7 narrowed it: the paste into every worker prompt went — measured
# across the Kura runs the excerpt was most of a 6.2 KB prompt, re-sent per
# dispatch, while pm_grab already returns the task and story context the worker
# acts on.  So the assertions below are inverted for the fence and re-aimed at
# /pm-do, which is where a worker that does need the docs is told to get them.
#
# US-PM-49-6 finished the narrowing and SUPERSEDES US-PM-26's once-per-run pin:
# with no excerpt to amortise across dispatches, the per-run fetch was a read
# the orchestrator paid for and then used for nothing, so pre-flight step 4b is
# gone from the run entirely.  The bound the story argued for is not abandoned,
# it moved: it is asserted below on the documents that still point at the tool
# (`/pm` and the pm agent), and the payload honesty test still runs the very
# call they instruct.

#: ``pm_context(...)`` with its argument list captured
PM_CONTEXT_CALL = re.compile(r"\bpm_context\(([^)]*)\)")

#: ``max_doc_chars=<int>`` as written in the skill
MAX_DOC_CHARS_ARG = re.compile(r"\bmax_doc_chars\s*=\s*(\d+)")

#: the server default for ``max_doc_chars`` — a doc must ask for *less*
SERVER_DEFAULT_MAX_DOC_CHARS = 4000

#: kwargs the skills name on their pm_context calls; each must be a real parameter
NAMED_KWARGS = ["max_doc_chars", "limit"]

#: the skill a dispatched worker is told to run, template and rendered copy —
#: since US-PM-49-7 this, not the prompt, is where the worker's route to the
#: project docs lives
PM_DO_DOCS = [
    TEMPLATES / "skill_pm_do.md.j2",
    RENDERED_SKILLS / "pm-do" / "SKILL.md",
]

#: the documents that still point at the tool, template and rendered copy —
#: since US-PM-49-6 the orchestrator is not one of them
POINTER_DOCS = [
    TEMPLATES / "skill_pm.md.j2",
    RENDERED_SKILLS / "pm" / "SKILL.md",
    TEMPLATES / "agent_pm.md.j2",
    REPO_ROOT / ".claude" / "agents" / "pm.md",
]


@pytest.mark.parametrize("path", DOCS)
def test_the_orchestrator_run_no_longer_fetches_a_per_run_pm_context(path):
    """US-PM-49-6's AC: the fetch is gone from the orchestrator's flow and prompt.

    Inverted from US-PM-13-5 and US-PM-26 on purpose, and this is the whole
    change: once US-PM-49-7 stopped pasting the excerpt into worker prompts,
    nothing downstream read what step 4b fetched, so a bounded ~10k-char read
    per run bought the orchestrator nothing.  The route to the docs for anyone
    who *does* need them is asserted on ``/pm-do`` and ``POINTER_DOCS`` below,
    so this is a removal from one document, not a deletion of the guidance.
    """
    text = _text(path)
    calls = PM_CONTEXT_CALL.findall(text)
    assert not calls, (
        f"{path.name}: the orchestrator still calls pm_context{calls} — the "
        "per-run brief was dropped by US-PM-49-6; nothing in the run reads it"
    )
    assert not any(line.startswith("4b.") for line in text.splitlines()), (
        f"{path.name}: pre-flight step 4b is back — it owned the dropped fetch"
    )


@pytest.mark.parametrize("path", POINTER_DOCS)
def test_the_docs_that_still_point_at_pm_context_bound_it(path):
    """``max_doc_chars=`` is present and asks for less than the server default.

    The bound is what makes the pointer safe to follow: an unbounded
    ``pm_context`` returned 48,588 chars in one study.  It was pinned on the
    orchestrator's step 4b until US-PM-49-6 dropped that step; the rule itself
    is unchanged and is pinned here, where the calls now live.
    """
    calls = PM_CONTEXT_CALL.findall(_text(path))
    assert calls, f"{path.name}: no pm_context() call to bound"
    bounds = [MAX_DOC_CHARS_ARG.search(args) for args in calls]
    assert all(bounds), (
        f"{path.name}: calls pm_context without max_doc_chars=: {calls}"
    )
    for match in bounds:
        value = int(match.group(1))
        assert 0 < value <= SERVER_DEFAULT_MAX_DOC_CHARS, (
            f"{path.name}: max_doc_chars={value} is not a bound below the "
            f"server default of {SERVER_DEFAULT_MAX_DOC_CHARS}"
        )


@pytest.mark.parametrize("path", DOCS)
def test_worker_prompt_fence_carries_no_project_context_excerpt(path):
    """US-PM-49's AC: the prompt is ids, criteria, DoD and the rules — nothing else.

    Inverted from US-PM-13-5's assertion on purpose: the excerpt was a per-run
    read charged per dispatch, and ``pm_grab`` already returns the task and
    story context a worker acts on.
    """
    fence = _worker_fence(_text(path))
    assert "Project context" not in fence, (
        f"{path.name}: the worker prompt still pastes a 'Project context' section"
    )
    assert not PM_CONTEXT_CALL.search(fence), (
        f"{path.name}: the worker prompt still names pm_context() — the excerpt "
        "and the call that widens it both belong outside the fence now"
    )


@pytest.mark.parametrize("path", PM_DO_DOCS)
def test_the_worker_still_has_a_named_step_for_project_docs(path):
    """Dropping the excerpt may not leave the worker with no route to the docs.

    The prompt tells the worker to run ``/pm-do``; that skill is where the
    guidance-tool call has to be named, or US-PM-13's diagnosis (a guidance tool
    with no step that calls it goes uncalled) comes straight back.
    """
    text = path.read_text(encoding="utf-8")
    assert re.search(r"pm_docs\(|pm_context\(", text), (
        f"{path.name}: no step names pm_docs() or pm_context(), so a worker that "
        "needs the project docs has nowhere to be told to read them"
    )


def test_pm_context_is_a_registered_tool():
    """The skill can never instruct a tool the server does not serve."""
    assert "pm_context" in _schemas()


@pytest.mark.parametrize("kwarg", NAMED_KWARGS)
def test_kwargs_named_in_the_skill_are_real_pm_context_parameters(kwarg):
    """A skill that names a parameter the signature lacks would fail at call time."""
    from projectman.server import pm_context

    assert kwarg in inspect.signature(pm_context).parameters


def test_bounded_pm_context_payload_is_actually_small(tmp_project, monkeypatch):
    """The honesty check: run the call the skills instruct, on oversized docs.

    Every assertion above is about text.  This one runs
    ``pm_context(max_doc_chars=2000, limit=5)`` — the call ``POINTER_DOCS``
    name — against 20,000-char project docs and shows the return really is a
    bounded excerpt, not a pointer at tens of thousands of chars.
    """
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache, pm_context
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    oversized = 20_000
    docs = tmp_project / ".project"
    for filename in ("PROJECT.md", "INFRASTRUCTURE.md", "SECURITY.md"):
        (docs / filename).write_text(f"# {filename}\n\n" + "architecture. " * 5000)
        assert len((docs / filename).read_text()) > oversized

    payload = pm_context(max_doc_chars=2000, limit=5)

    assert len(payload) < 12_000, (
        f"pm_context(max_doc_chars=2000, limit=5) returned {len(payload)} chars — "
        "the bounded-excerpt claim the pointing docs make does not hold"
    )

    embedded = yaml.safe_load(payload)["project_docs"]
    assert set(embedded) == {"project", "infrastructure", "security"}
    for key, text in embedded.items():
        body = text.split("\n…[truncated")[0]
        assert len(body) <= 2000, f"{key} embedded at {len(body)} chars, over max_doc_chars"
        assert "truncated" in text, f"{key} was not truncated despite being oversized"


@pytest.mark.parametrize("path", DOCS)
def test_removing_step_4b_did_not_renumber_the_verdict_steps(path):
    """US-PM-13-5 inserted ``4b`` rather than renumbering; US-PM-49-6 removed it.

    ``test_skill_verdict_verbs._step_19`` and everything built on it slice the
    verdict step by the literal line prefixes ``19.`` and ``20.``.  Pin that
    assumption here so a future insertion that *does* renumber fails loudly at
    the cause rather than vacuously downstream.
    """
    lines = _text(path).splitlines()
    for prefix in ("19.", "20."):
        matches = [line for line in lines if line.startswith(prefix)]
        assert len(matches) == 1, (
            f"{path.name}: expected exactly one line starting {prefix!r}, "
            f"found {len(matches)}"
        )


# ═══ pm_estimate (US-PM-13-2) ═══════════════════════════════════
#
# AC: "The scoping and estimation workflows consult pm_estimate before writing
# points."  Delivered by US-PM-13-6, which added a named calibration step to
# `/pm` and `/pm-autoscope` (both at 0 mentions of ``pm_estimate`` before) and
# left the already-present steps in `/pm-plan` and the ``pm`` agent standing.
#
# The criterion is ORDER, not presence: a skill that names ``pm_estimate``
# somewhere *after* the create/update call that writes ``points`` would satisfy
# a naive substring check while the estimate stayed invented.  So every
# assertion below is about the calibration step preceding the write step, and
# every one runs against both the template (source of truth) and the tracked
# rendered copy.
#
# US-PM-26 narrowed that criterion.  The ordering mandate was adopted for the
# orchestrator's benefit (workers that size against real bands) and then applied
# everywhere; interactively it costs a round trip on a one-line update.  So for
# every interactive document — `/pm`, `/pm-plan`, `/pm-autoscope` and the ``pm``
# agent — what is pinned here is now REACHABILITY: the tool is named where
# sizing happens, as an option.  ``/pm-autoscope`` lost its ordering assertions
# in US-PM-26-5: a bulk run is where a calibration pays off best, which is an
# argument for offering it at the sizing step, not for gating the create step
# behind it.  What remains pinned for it is the offer's *placement* (on the step
# that sizes, immediately before the one that creates) and the per-size-band
# bound that keeps a large run affordable.  The absence of a mandate in the
# interactive documents is asserted in
# ``tests/test_interactive_skills_optional_calibration.py``; keep the two in
# step — an ordering *mandate* restored here would contradict that module.

#: workflow → (template filename, tracked rendered copy)
#: ``agent_pm`` renders outside ``.claude/skills/``, hence the explicit paths.
ESTIMATION_DOCS = {
    "pm": ("skill_pm.md.j2", RENDERED_SKILLS / "pm" / "SKILL.md"),
    "pm-autoscope": (
        "skill_pm_autoscope.md.j2",
        RENDERED_SKILLS / "pm-autoscope" / "SKILL.md",
    ),
    "pm-plan": ("skill_pm_plan.md.j2", RENDERED_SKILLS / "pm-plan" / "SKILL.md"),
    "agent-pm": ("agent_pm.md.j2", REPO_ROOT / ".claude" / "agents" / "pm.md"),
}

#: ``pm_estimate(`` as the skills spell the call
PM_ESTIMATE_CALL = re.compile(r"\bpm_estimate\(")


def _both(name: str) -> list:
    """The template and the rendered copy of one workflow, as pytest params."""
    template, rendered = ESTIMATION_DOCS[name]
    return [
        pytest.param(TEMPLATES / template, id=f"{name}-template"),
        pytest.param(rendered, id=f"{name}-rendered"),
    ]


#: every document the acceptance criterion covers
ALL_ESTIMATION_DOCS = [p for name in ESTIMATION_DOCS for p in _both(name)]

#: (template, rendered) pairs for the render-identity check
RENDER_PAIRS = [
    pytest.param(template, rendered, id=name)
    for name, (template, rendered) in ESTIMATION_DOCS.items()
]


def _line_index(text: str, needle: str, path=None) -> int:
    """Index of the first line containing ``needle`` — the ordering primitive."""
    for n, line in enumerate(text.splitlines()):
        if needle in line:
            return n
    raise AssertionError(f"{getattr(path, 'name', path)}: no line contains {needle!r}")


@pytest.mark.parametrize("path", ALL_ESTIMATION_DOCS)
def test_every_estimation_workflow_names_pm_estimate(path):
    """The floor: `/pm` and `/pm-autoscope` were both at zero before US-PM-13-6."""
    assert PM_ESTIMATE_CALL.search(_text(path)), (
        f"{path.name}: never names pm_estimate() — the workflow sizes blind"
    )


@pytest.mark.parametrize("path", _both("pm"))
def test_pm_skill_estimation_section_offers_the_calibration_it_no_longer_gates(path):
    """`/pm`'s Estimation section: the call and what it returns, as an option.

    US-PM-26 replaced the two-step gate with guidance, so the assertion moved
    from ordering to content: the section must still name ``pm_estimate()``, say
    what it hands back (``estimation_guidance`` is the field the tool returns —
    naming it is what makes the offer actionable), and keep the fibonacci scale
    the points are written on.  Without that the section degrades into a bare
    tool name and the guidance the tool exists to deliver stops being reachable.
    """
    text = _text(path)
    start = _line_index(text, "### Estimation", path)
    body = "\n".join(text.splitlines()[start:]).split("\n### ", 2)[0]
    assert PM_ESTIMATE_CALL.search(body), (
        f"{path.name}: the Estimation section no longer calls pm_estimate():\n{body}"
    )
    assert "estimation_guidance" in body, (
        f"{path.name}: the section never says pm_estimate returns "
        f"estimation_guidance:\n{body}"
    )
    assert re.search(r"fibonacci", body, re.IGNORECASE), (
        f"{path.name}: the section dropped the fibonacci scale:\n{body}"
    )
    assert "1/2/3/5/8/13" in body, (
        f"{path.name}: the section dropped the calibration bands:\n{body}"
    )


@pytest.mark.parametrize("path", _both("pm"))
@pytest.mark.parametrize("bullet", ["`update <id>", "`scope <story-id>`"])
def test_pm_skill_points_write_paths_point_back_at_the_calibration_step(path, bullet):
    """Every routing bullet that writes points must reference the Estimation step.

    Without the back-reference the section is unreachable from the place the
    model actually reads — the command routing table.
    """
    lines = [line for line in _text(path).splitlines() if bullet in line]
    assert lines, f"{path.name}: no routing bullet containing {bullet!r}"
    for line in lines:
        assert re.search(r"estimation|calibrat", line, re.IGNORECASE), (
            f"{path.name}: a points-writing bullet never points at calibration: {line!r}"
        )


@pytest.mark.parametrize("path", _both("pm-autoscope"))
@pytest.mark.parametrize(
    "sizing_step,create_step",
    [("10. **Size the tasks**", "11. Create approved tasks"), ("d. **Size the tasks**", "e. Create approved tasks")],
    ids=["full-scan", "incremental"],
)
def test_autoscope_offers_calibration_on_the_step_that_sizes_tasks(path, sizing_step, create_step):
    """Both autoscope workflows offer the calibration where the points are chosen.

    US-PM-26-5 turned the gate into an offer, so what is asserted is placement,
    not obligation: the sizing step names ``pm_estimate()``, and the step that
    writes those points via ``pm_create_task`` is the next one — a pointer
    parked in another section is not reachable from the step that sizes.
    """
    text = _text(path)
    sizing = _line_index(text, sizing_step, path)
    create = _line_index(text, create_step, path)
    assert PM_ESTIMATE_CALL.search(text.splitlines()[sizing]), (
        f"{path.name}: {sizing_step!r} names no pm_estimate() — the calibration "
        "is no longer reachable from the step that chooses points"
    )
    assert "pm_create_task" in text.splitlines()[create], (
        f"{path.name}: {create_step!r} no longer creates tasks — the placement "
        "assertion has gone vacuous"
    )
    assert create == sizing + 1, (
        f"{path.name}: {create_step!r} (line {create}) no longer directly follows "
        f"{sizing_step!r} (line {sizing}) — the offer drifted away from the write"
    )


@pytest.mark.parametrize("path", _both("pm-autoscope"))
def test_autoscope_bounds_bulk_estimation_to_one_call_per_size_band(path):
    """A per-item call across dozens of items would price the step out of use.

    The skill's answer is one call per size band; pin it, because dropping the
    bound is exactly the edit that would make the step get skipped instead.
    """
    text = _text(path)
    assert "Estimation in bulk" in text, f"{path.name}: the bulk-estimation section is gone"
    section = text.split("## Estimation in bulk", 1)[1].split("\n## ", 1)[0]
    assert PM_ESTIMATE_CALL.search(section), f"{path.name}: the bulk section drops pm_estimate()"
    assert "band" in section.lower(), (
        f"{path.name}: the bulk section never says to estimate per size band:\n{section}"
    )
    assert re.search(r"rather than", section), (
        f"{path.name}: the bulk section never contrasts per-band with per-item:\n{section}"
    )


@pytest.mark.parametrize("path", _both("pm-plan"))
def test_plan_scoping_gate_offers_estimation_where_it_creates(path):
    """`/pm-plan`'s Phase 3 gate names pm_estimate on the line that creates tasks.

    US-PM-26 turned "``pm_estimate(id)`` per task" into an offer, so the
    ordering assertion this test used to make is gone (it would now pass or fail
    on where in one sentence the offer sits).  What still matters is that the
    offer lives on the gate line itself: the scoping gate is where points get
    proposed, and a pointer parked in another phase is not reachable from it.
    """
    lines = [line for line in _text(path).splitlines() if PM_ESTIMATE_CALL.search(line)]
    assert lines, f"{path.name}: the scoping gate never calls pm_estimate()"
    gate = [line for line in lines if "create on approval" in line]
    assert gate, (
        f"{path.name}: no scoping-gate line pairs pm_estimate() with creation: {lines}"
    )
    for line in gate:
        assert re.search(r"\bpoints\b|\bestimat", line, re.IGNORECASE), (
            f"{path.name}: the gate line names pm_estimate but never ties it to "
            f"sizing the tasks it creates: {line!r}"
        )


@pytest.mark.parametrize("path", _both("agent-pm"))
def test_agent_estimate_step_offers_calibration_for_the_points_it_writes(path):
    """The agent keeps a named Estimate step; US-PM-26 made it an offer.

    The step used to declare that it "runs before any ``points`` value is
    written".  What survives that relaxation is the pairing: the workflow step
    that mentions points is the one that names ``pm_estimate()``, so the tool
    stays attached to the activity that would use it rather than floating in a
    tool list.
    """
    lines = [line for line in _text(path).splitlines() if "**Estimate**" in line]
    assert lines, f"{path.name}: the agent lost its Estimate step"
    for line in lines:
        assert PM_ESTIMATE_CALL.search(line), f"{path.name}: {line!r} names no pm_estimate()"
        assert re.search(r"\bpoints\b", line), (
            f"{path.name}: the Estimate step no longer connects the tool to the "
            f"points it sizes: {line!r}"
        )


def test_pm_estimate_is_a_registered_tool_accepting_id():
    """The skills instruct ``pm_estimate(<id>)`` — the server must serve that.

    ``id`` is deliberately *optional* on the wire (the tool also accepts
    ``task_id``), so this asserts it is an accepted parameter of string type
    rather than a required one — the skills only ever pass it by that name.
    """
    from projectman.server import pm_estimate

    tool = _schemas().get("pm_estimate")
    assert tool is not None, "pm_estimate is not a registered MCP tool"
    schema = tool.inputSchema["properties"].get("id")
    assert schema is not None, tool.inputSchema
    types = {t.get("type") for t in schema.get("anyOf", [schema])}
    assert "string" in types, schema
    assert "id" in inspect.signature(pm_estimate).parameters


@pytest.mark.parametrize("template,rendered", RENDER_PAIRS)
def test_rendered_estimation_docs_are_byte_identical_to_their_templates(template, rendered):
    """Only ``pm-orchestrate`` was pinned before; these four carry the AC now.

    ``setup-claude`` renders each template with no kwargs, so a hand-edit to the
    tracked copy — or a template edit that was never re-rendered — means the
    assertions above are checking two different documents.
    """
    assert _text(rendered) == _render_template(template)


# ═══ every guidance tool has a named step (US-PM-13-3) ══════════
#
# AC: "Skill files name the step at which each guidance tool is called."
#
# The two sections above pin the *specific wording* US-PM-13-5 and US-PM-13-6
# added.  That wording will be rewritten one day; the criterion behind it must
# not be.  So this section states the rule generically: for every guidance
# tool, every skill/agent document that mentions it must mention it at a named
# step — a numbered/lettered step, a bold step label, a phase, or a routing
# bullet — and not merely in a flat tool inventory, a table row or a prose
# aside.
#
# Two rules make that generic statement mean what the criterion means.
#
# RULE 1 — only the CALL FORM counts as mentioning the tool.  A mention is
# ``pm_<tool>(``, backticked or not.  ``skill_pm_do.md.j2`` says "Dependency
# status is shown in `pm_grab` and `pm_context` responses" — that is a
# description of a response payload, not an instruction to call anything, so
# there is no step for it to be named at and demanding one would be demanding a
# step for a sentence that never asks the reader to take one.  Bare names in
# tables and tool inventories fall out for the same reason; they are the
# inventory the criterion is aimed *against*, and they are now excluded at the
# mention stage rather than at the step stage.
#
# RULE 2 — a ROUTING BULLET is a named step.  In a router skill (`/pm`) the
# document has no numbered flow at all: it is a table of contents from command
# words to tool calls, and ``- `context [project]` → `pm_context(project)` `` is
# precisely "the step someone takes" that the story's diagnosis says a guidance
# tool needs in order to get called.  Dropping the arrow — ``| pm_context |
# guidance |`` in a table, or ``Tools: pm_context, pm_estimate`` in an
# inventory — drops the step with it, and those stay negative.
#
# Membership in the guidance set is *derived*, not asserted by taste: a
# guidance tool is a registered MCP tool that is (a) annotated
# ``readOnlyHint=True`` — it advises, it never writes — and (b) whose docstring
# summary line says it returns guidance / calibration / context.  Of the 24
# read-only tools the server registers, exactly three match:
#
#   * ``pm_context``  — "Get combined hub + project *context* for an agent
#     starting work."
#   * ``pm_estimate`` — "returns content + *calibration* guidelines."
#   * ``pm_scope``    — "returns story + existing tasks + decomposition
#     *guidance*."
#
# Deliberately excluded, and why: ``pm_docs`` is read-only but its summary is
# "Read project documentation files" — a retrieval primitive that
# ``pm_context`` itself points at for full text, not advice about how to work.
# ``pm_auto_scope`` returns "codebase signals", i.e. an inventory of what needs
# scoping, and ``pm_audit`` returns findings; neither advises how to do a step.
# ``test_the_guidance_set_is_exactly_the_servers_read_only_advisory_tools``
# keeps that derivation honest — a fourth advisory tool added to the server
# fails there rather than silently escaping this section's coverage.

#: the guidance tools, in the order the story discusses them
GUIDANCE_TOOLS = ("pm_context", "pm_estimate", "pm_scope")


def _mention_re(tool: str) -> re.Pattern:
    """RULE 1: a document mentions a guidance tool by *calling* it.

    ``pm_context(`` is an instruction; a bare ``pm_context`` inside a sentence
    about what a response contains is a noun.  Only the former can have a step.
    """
    return re.compile(rf"\b{re.escape(tool)}\(")


#: what makes a read-only tool *advisory* rather than merely retrieving
GUIDANCE_SUMMARY = re.compile(r"\b(guidance|calibration|context)\b", re.IGNORECASE)

#: a markdown heading (ATX), at any level
_HEADING = re.compile(r"^ {0,3}(#{1,6}) ")

#: a heading that names a phase — "## Phase 3 — Select and scope to capacity"
_PHASE_HEADING = re.compile(r"\bPhase\s+\d")

#: a numbered list item: "1. ", "10. ", "4b. "
_NUMBERED = re.compile(r"^\s*\d+[a-z]?\.\s")

#: any list item — bullet, numbered or lettered
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s|\d+[a-z]?\.\s|[a-z]\.\s)")

#: A NAMED STEP, as the skills actually spell one.  Numbered ("4b."), lettered
#: ("a."), a bold step label ("**Step 1 —", "**Calibrate:"), a phase, or —
#: RULE 2 — a routing bullet, whose command words are the step and whose arrow
#: maps them onto the call.
#: Deliberately *not* matched: a table row ("| `pm_estimate(<id>)` | ... |"), a
#: tool inventory, a prose aside.  Those tell you the tool exists, never that
#: you are standing at the step that calls it — the entire diagnosis of
#: US-PM-13.  The arrow is what separates the two: it is the thing that says
#: "when you are doing *this*, call *that*".
STEP_MARKER = re.compile(
    r"""(?x)
      ^\s*\d+[a-z]?\.\s     # 1.   10.   4b.
    | ^\s*[a-z]\.\s         # a.   d.
    | \*\*Step\s+\d         # **Step 1 — Calibrate
    | \*\*Calibrate         # **Calibrate: `pm_estimate(<id>)`**
    | \bPhase\s+\d          # Phase 3
    | ^\s*[-*+]\s+`[^`\n]+`\s*(?:→|->)   # - `scope <id>` → `pm_scope(id)`
    """
)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _section_is_a_numbered_list(lines: list[str], heading: int) -> bool:
    """Does the section opened at ``heading`` have numbered steps in its body?"""
    end = next(
        (n for n in range(heading + 1, len(lines)) if _HEADING.match(lines[n])),
        len(lines),
    )
    return any(_NUMBERED.match(lines[n]) for n in range(heading + 1, end))


def _named_steps(text: str, tool: str) -> list[str]:
    """Every mention of ``tool`` that sits at a named step, as "L<n>: <step>".

    A mention counts when the mention line itself carries a step marker, or
    when the *enclosing* list item does — walking up past continuation lines
    and same-level siblings to the first line at a smaller indent, which is
    how a sub-bullet inherits its parent step (``pm-plan``'s scoping gate
    nests ``pm_scope``/``pm_estimate`` under numbered step 7).  Failing both,
    the enclosing heading counts if it names a phase or opens a numbered list.
    """
    mention = _mention_re(tool)
    lines = text.splitlines()
    hits: list[str] = []
    for i, line in enumerate(lines):
        if not mention.search(line):
            continue
        if STEP_MARKER.search(line):
            hits.append(f"L{i + 1}: {line.strip()}")
            continue
        indent = _indent(line)
        for j in range(i - 1, -1, -1):
            previous = lines[j]
            if _HEADING.match(previous):
                level = len(_HEADING.match(previous).group(1))
                if _PHASE_HEADING.search(previous) or (
                    level >= 3 and _section_is_a_numbered_list(lines, j)
                ):
                    hits.append(f"L{i + 1}: (under) {previous.strip()}")
                break
            if not previous.strip() or _indent(previous) >= indent:
                continue
            if STEP_MARKER.search(previous):
                hits.append(f"L{i + 1}: (under) {previous.strip()}")
            break
    return hits


def _mentions(text: str, tool: str) -> list[str]:
    """Every line calling ``tool``, step or not — used to report failures."""
    mention = _mention_re(tool)
    return [
        f"L{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if mention.search(line)
    ]


#: every skill/agent document the criterion covers: the templates that are the
#: source of truth, plus the rendered copies tracked in this checkout.
SKILL_DOCS = (
    _skill_templates()
    + _rendered_skills()
    + sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))
)

#: (document, tool) for every document that mentions that tool at all
GUIDANCE_CASES = [
    pytest.param(path, tool, id=f"{path.parent.name}-{path.name}-{tool}")
    for path in SKILL_DOCS
    for tool in GUIDANCE_TOOLS
    if _mention_re(tool).search(_text(path))
]


def test_the_document_set_is_non_empty_and_covers_the_known_skills():
    """Guard the corpus: an empty glob would make every test below vacuous."""
    names = {path.name for path in SKILL_DOCS}
    for expected in ("skill_pm.md.j2", "skill_pm_orchestrate.md.j2", "agent_pm.md.j2"):
        assert expected in names, f"{expected} missing from the document set"
    assert sum(1 for p in SKILL_DOCS if p.name == "SKILL.md") >= 5, (
        f"only {[str(p) for p in SKILL_DOCS]} — rendered skills are not being checked"
    )
    assert len(GUIDANCE_CASES) >= 12, (
        f"only {len(GUIDANCE_CASES)} (document, tool) pairs — the corpus shrank"
    )


def test_the_guidance_set_is_exactly_the_servers_read_only_advisory_tools():
    """Derive the set from the server, so a new guidance tool cannot slip past.

    ``readOnlyHint=True`` is what makes a tool advisory rather than a write;
    the summary line saying guidance/calibration/context is what makes it
    *guidance* rather than plain retrieval.
    """
    derived = {
        name
        for name, tool in _schemas().items()
        if tool.annotations
        and tool.annotations.readOnlyHint
        and GUIDANCE_SUMMARY.search((tool.description or "").split("\n\n")[0])
    }
    assert derived == set(GUIDANCE_TOOLS), (
        "the server's read-only advisory tools no longer match GUIDANCE_TOOLS — "
        f"derived {sorted(derived)}, declared {sorted(GUIDANCE_TOOLS)}. "
        "A new guidance tool must be given a named step in the skills (and "
        "added here); a tool that stopped being advisory must be removed."
    )


@pytest.mark.parametrize("tool", GUIDANCE_TOOLS)
def test_every_guidance_tool_is_registered_and_read_only(tool):
    """A skill cannot instruct a step around a tool the server does not serve."""
    registered = _schemas()
    assert tool in registered, f"{tool} is not a registered MCP tool"
    annotations = registered[tool].annotations
    assert annotations is not None, f"{tool} carries no annotations"
    assert annotations.readOnlyHint is True, (
        f"{tool} is not readOnlyHint=True — it is not a guidance tool"
    )


# ─── the predicate's own negative control ────────────────────────
#
# Every assertion below rests on ``_named_steps``.  If that predicate returned
# a hit for anything containing the tool name, the whole section would pass
# vacuously — so it is exercised directly, against text written to be
# unambiguous in each direction.

#: Text that *calls* a guidance tool but at no step — this is what keeps
#: ``STEP_MARKER`` honest now that bare names are filtered out earlier.
INVENTORY_ONLY = [
    pytest.param(
        "| `pm_estimate(<id>)` | guidance | returns calibration bands |",
        id="table-row-with-call",
    ),
    pytest.param(
        "## Tools available\n\n- `pm_estimate(<id>)` — returns calibration bands",
        id="tools-available-list",
    ),
    pytest.param(
        "The `pm_estimate(<id>)` tool exists and returns calibration bands.",
        id="prose-aside-with-call",
    ),
]

#: RULE 1's control: a bare name is not a mention at all, so the predicate
#: reports zero mentions *and* zero named steps, and
#: ``test_every_document_mentioning_a_guidance_tool_names_its_step`` never runs
#: for such a document.  The first case is ``skill_pm_do.md.j2`` line 44.
BARE_NAME_ONLY = [
    pytest.param("shown in `pm_context` responses", "pm_context", id="shown-in-responses"),
    pytest.param(
        "Dependency status is shown in `pm_grab` and `pm_context` responses "
        "(id, title, status, type).",
        "pm_context",
        id="dependency-status-aside",
    ),
    pytest.param("| pm_context | guidance | hub + project context |", "pm_context", id="table-row"),
    pytest.param("Tools: pm_context, pm_estimate", "pm_estimate", id="tool-inventory"),
    pytest.param(
        "## Tools available\n\n- `pm_estimate` — estimation context\n- `pm_scope` — scoping context",
        "pm_scope",
        id="tools-available-bare",
    ),
]

#: RULE 2's control: the routing bullets that carry the criterion in `/pm`.
ROUTING_STEP = [
    pytest.param(
        "- `context [project]` → `pm_context(project)` — full hub + project context",
        "pm_context",
        id="routing-bullet-context",
    ),
    pytest.param(
        "- `scope <story-id>` → `pm_scope(id)`, propose a task breakdown",
        "pm_scope",
        id="routing-bullet-scope",
    ),
    pytest.param(
        "- `scope <story-id>` → `pm_scope(id)`, calibrate each estimate with "
        "`pm_estimate(<id>)` (**Estimation**, above)",
        "pm_estimate",
        id="routing-bullet-scope-calibrates",
    ),
    pytest.param(
        "### Status & Queries\n\n- `board` → `pm_board`\n"
        "- `context` → `pm_context(project)` — full context",
        "pm_context",
        id="routing-bullet-under-heading",
    ),
]

NAMED_STEP = [
    pytest.param("3. **Calibrate: `pm_estimate(<id>)`**", id="numbered-bold"),
    pytest.param("4b. call `pm_estimate(<id>)` before writing points", id="numbered-letter"),
    pytest.param("   d. **Calibrate: `pm_estimate(<id>)`**", id="lettered"),
    pytest.param("- **Step 1 — Calibrate: `pm_estimate(<id>)`.**", id="bold-step-label"),
    pytest.param(
        "7. Scoping gate:\n   - For each story: `pm_estimate(id)` per task, create on approval.",
        id="nested-under-numbered-step",
    ),
]


@pytest.mark.parametrize("text", INVENTORY_ONLY)
def test_predicate_reports_no_named_step_for_inventory_only_text(text):
    """Inventory tells you the tool exists; it never names the step calling it."""
    assert _named_steps(text, "pm_estimate") + _named_steps(text, "pm_context") == [], (
        f"the predicate accepted inventory-only text as a named step:\n{text}"
    )


@pytest.mark.parametrize("text", NAMED_STEP)
def test_predicate_reports_a_named_step_for_step_text(text):
    """And the converse — otherwise every assertion below fails for free."""
    assert len(_named_steps(text, "pm_estimate")) == 1, (
        f"the predicate missed a named step:\n{text}"
    )


@pytest.mark.parametrize("text,tool", BARE_NAME_ONLY)
def test_predicate_ignores_a_bare_name_that_is_not_a_call(text, tool):
    """RULE 1: a name without ``(`` is a noun, not an instruction to call.

    Both halves matter: zero *mentions* is what makes the document-level test
    skip such a document entirely, and zero *named steps* is what stops the
    bare name from being smuggled in as evidence of one.
    """
    assert _mentions(text, tool) == [], f"a bare name was read as a call:\n{text}"
    assert _named_steps(text, tool) == [], f"a bare name was read as a step:\n{text}"


@pytest.mark.parametrize("text,tool", ROUTING_STEP)
def test_predicate_reports_a_named_step_for_a_routing_bullet(text, tool):
    """RULE 2: the command words are the step; the arrow maps them to the call."""
    assert len(_named_steps(text, tool)) == 1, (
        f"the predicate missed a routing bullet's step for {tool}:\n{text}"
    )


# ─── the criterion itself ────────────────────────────────────────


@pytest.mark.parametrize("path,tool", GUIDANCE_CASES)
def test_every_document_mentioning_a_guidance_tool_names_its_step(path, tool):
    """The AC, stated generically: mention it, and you must name its step.

    A document that names a guidance tool only in its routing table or as a
    prose aside is precisely the shape that produced 1–2 ``pm_estimate`` calls
    against 28–40 for ``pm_scope``: the reader learns the tool exists but never
    reaches a step that says to call it.
    """
    text = _text(path)
    steps = _named_steps(text, tool)
    assert steps, (
        f"{path}: mentions {tool} but never at a named step — every mention is "
        "inventory (routing bullet, table row or prose aside):\n  "
        + "\n  ".join(_mentions(text, tool))
    )


@pytest.mark.parametrize("tool", GUIDANCE_TOOLS)
def test_at_least_one_skill_template_names_a_step_for_each_guidance_tool(tool):
    """The floor the story was written against: a tool in no skill at all.

    Run against ``git show HEAD:``, this fails for ``pm_context`` — before
    US-PM-13-5 no ``skill_*`` template named a step for it, only the ``pm``
    agent did, and the agent is not what a worker or an orchestrator reads.
    """
    named = [
        path.name
        for path in _skill_templates()
        if path.name.startswith("skill_") and _named_steps(_text(path), tool)
    ]
    assert named, (
        f"no skill template names a step that calls {tool} — the guidance is "
        "registered but unreachable from any workflow"
    )


# ═══ the five worker safety rules (US-PM-25-3/7) ════════════════
#
# Sprints 5–7 each cost a task's worth of work to a worker that took one of
# these five actions.  US-PM-25-7 wrote them into the Worker Prompt Template so
# the lesson travels with every dispatch instead of living in an orchestrator's
# memory; this pins them verbatim, because a paraphrase of "never run git
# checkout" is exactly what a summarising edit produces and exactly what the
# worker then fails to obey.

#: the rules as they must read inside the fence, character for character
WORKER_SAFETY_RULES = [
    "Never run git checkout, git restore, git stash, or git reset",
    "Never call pm_create_* or any Store write outside a tmp_path-isolated fixture",
    "Edit tracked files directly with the Edit tool; do not stage code through scratchpad files",
    "they must end byte-identical — the branch diff shows it",
    "must never run the new command against the real repo",
]


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("rule", WORKER_SAFETY_RULES)
def test_worker_prompt_fence_carries_the_five_safety_rules_verbatim(path, rule):
    """Each rule is in the prompt the worker actually receives, not just nearby.

    The fence is what gets pasted into the subagent's context, so a rule that
    drifted into the surrounding prose would never reach a worker.
    """
    fence = _worker_fence(_text(path))
    assert rule in fence, (
        f"{path.name}: the worker prompt no longer says {rule!r} verbatim — a "
        "hard-won rule from Sprints 5–7 would stop travelling with dispatches"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_safety_rules_are_five_separate_bullets(path):
    """Merging two rules into one bullet is how the shortest one gets dropped."""
    fence = _worker_fence(_text(path))
    bullets = [line for line in fence.splitlines() if line.lstrip().startswith("- ")]
    carrying = [b for b in bullets if any(rule in b for rule in WORKER_SAFETY_RULES)]
    assert len(carrying) == len(WORKER_SAFETY_RULES), (
        f"{path.name}: {len(carrying)} bullets carry the "
        f"{len(WORKER_SAFETY_RULES)} safety rules:\n" + "\n".join(carrying)
    )
