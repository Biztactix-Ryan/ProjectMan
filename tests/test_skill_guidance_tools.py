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

* ``pm_context (US-PM-13-1)`` — the worker prompt template includes project
  architecture context;
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
    _outside_fences,
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
# per run, and the worker prompt fence carries the excerpt in a "Project
# context" section plus a rule letting the worker fetch more itself.

#: the pre-flight step that owns the fetch
CONTEXT_STEP = "4b."

#: ``pm_context(...)`` with its argument list captured
PM_CONTEXT_CALL = re.compile(r"\bpm_context\(([^)]*)\)")

#: ``max_doc_chars=<int>`` as written in the skill
MAX_DOC_CHARS_ARG = re.compile(r"\bmax_doc_chars\s*=\s*(\d+)")

#: the server default for ``max_doc_chars`` — the skill must ask for *less*
SERVER_DEFAULT_MAX_DOC_CHARS = 4000

#: kwargs the skill names on its pm_context calls; each must be a real parameter
NAMED_KWARGS = ["max_doc_chars", "limit"]


@pytest.mark.parametrize("path", DOCS)
def test_preflight_step_calls_pm_context_outside_the_worker_fence(path):
    """The orchestrator's own flow — not just the pasted worker prompt — fetches it."""
    flow = _outside_fences(_text(path))
    assert PM_CONTEXT_CALL.search(flow), (
        f"{path.name}: the orchestrator flow never calls pm_context()"
    )
    block = _step(flow, CONTEXT_STEP)
    assert PM_CONTEXT_CALL.search(block), (
        f"{path.name}: step {CONTEXT_STEP} does not call pm_context():\n{block}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_preflight_pm_context_call_is_bounded(path):
    """``max_doc_chars=`` is present and asks for less than the server default.

    The whole reason the step is safe to run once per sprint is the bound: an
    unbounded ``pm_context`` returned 48,588 chars in one study.
    """
    block = _step(_outside_fences(_text(path)), CONTEXT_STEP)
    calls = PM_CONTEXT_CALL.findall(block)
    assert calls, f"{path.name}: no pm_context() call in step {CONTEXT_STEP}"
    bounds = [MAX_DOC_CHARS_ARG.search(args) for args in calls]
    assert all(bounds), (
        f"{path.name}: step {CONTEXT_STEP} calls pm_context without max_doc_chars=: {calls}"
    )
    for match in bounds:
        value = int(match.group(1))
        assert 0 < value <= SERVER_DEFAULT_MAX_DOC_CHARS, (
            f"{path.name}: max_doc_chars={value} is not a bound below the "
            f"server default of {SERVER_DEFAULT_MAX_DOC_CHARS}"
        )


@pytest.mark.parametrize("path", DOCS)
def test_preflight_says_the_context_is_fetched_once_and_reused(path):
    """Per-worker re-fetching is the cost this step exists to avoid."""
    block = _step(_outside_fences(_text(path)), CONTEXT_STEP)
    assert "once" in block.lower(), (
        f"{path.name}: step {CONTEXT_STEP} never says the fetch happens once:\n{block}"
    )
    assert re.search(r"\breus", block, re.IGNORECASE), (
        f"{path.name}: step {CONTEXT_STEP} never says the excerpt is reused:\n{block}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_worker_prompt_fence_carries_a_project_context_section(path):
    """The AC's literal claim: the worker prompt template includes architecture."""
    fence = _worker_fence(_text(path))
    assert "Project context" in fence, (
        f"{path.name}: the worker prompt has no 'Project context' section"
    )
    assert re.search(r"architecture", fence, re.IGNORECASE), (
        f"{path.name}: the worker prompt's context section never names architecture"
    )


@pytest.mark.parametrize("path", DOCS)
def test_worker_prompt_fence_lets_the_worker_widen_the_excerpt(path):
    """A bounded excerpt is only safe if the worker is told how to read more."""
    fence = _worker_fence(_text(path))
    lines = [line for line in fence.splitlines() if "pm_context(" in line]
    assert lines, f"{path.name}: the worker prompt never names pm_context()"
    assert any(MAX_DOC_CHARS_ARG.search(line) or "max_doc_chars=" in line for line in lines), (
        f"{path.name}: the worker's pm_context rule omits max_doc_chars=: {lines}"
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
    """The honesty check: run the call the skill instructs, on oversized docs.

    Every assertion above is about text.  This one runs
    ``pm_context(max_doc_chars=2000, limit=5)`` against 20,000-char project
    docs and shows the return really is a bounded excerpt — otherwise step 4b
    would be pasting tens of thousands of chars into every worker prompt.
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
        "step 4b's bounded-excerpt claim does not hold"
    )

    embedded = yaml.safe_load(payload)["project_docs"]
    assert set(embedded) == {"project", "infrastructure", "security"}
    for key, text in embedded.items():
        body = text.split("\n…[truncated")[0]
        assert len(body) <= 2000, f"{key} embedded at {len(body)} chars, over max_doc_chars"
        assert "truncated" in text, f"{key} was not truncated despite being oversized"


@pytest.mark.parametrize("path", DOCS)
def test_inserting_step_4b_did_not_renumber_the_verdict_steps(path):
    """US-PM-13-5 inserted ``4b`` rather than renumbering.

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
def test_pm_skill_calibrates_before_it_sizes_and_writes(path):
    """`/pm`'s Estimation section: step 1 calibrates, step 2 writes — in that order."""
    text = _text(path)
    calibrate = _line_index(text, "Step 1 — Calibrate", path)
    write = _line_index(text, "Step 2 — Size and write", path)
    assert calibrate < write, (
        f"{path.name}: the write step (line {write}) precedes calibration (line {calibrate})"
    )
    step_one = text.splitlines()[calibrate]
    assert PM_ESTIMATE_CALL.search(step_one), (
        f"{path.name}: the calibrate step does not call pm_estimate(): {step_one!r}"
    )
    assert "points" in text.splitlines()[write].lower() or "write" in text.splitlines()[write]


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
    "calibrate_step,create_step",
    [("10. **Calibrate:", "11. Create approved tasks"), ("d. **Calibrate:", "e. Create approved tasks")],
    ids=["full-scan", "incremental"],
)
def test_autoscope_calibrate_step_precedes_the_create_step(path, calibrate_step, create_step):
    """Both autoscope workflows calibrate at the step before the one writing points."""
    text = _text(path)
    calibrate = _line_index(text, calibrate_step, path)
    create = _line_index(text, create_step, path)
    assert calibrate < create, (
        f"{path.name}: {create_step!r} (line {create}) is not preceded by "
        f"{calibrate_step!r} (line {calibrate})"
    )
    assert PM_ESTIMATE_CALL.search(text.splitlines()[calibrate])
    assert "pm_create_task" in text.splitlines()[create], (
        f"{path.name}: the step after calibration no longer creates tasks — "
        "the ordering assertion has gone vacuous"
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
def test_plan_scoping_gate_estimates_before_it_creates(path):
    """`/pm-plan`'s Phase 3 gate: pm_estimate comes before "create on approval"."""
    lines = [line for line in _text(path).splitlines() if PM_ESTIMATE_CALL.search(line)]
    assert lines, f"{path.name}: the scoping gate never calls pm_estimate()"
    gate = [line for line in lines if "create on approval" in line]
    assert gate, (
        f"{path.name}: no scoping-gate line pairs pm_estimate() with creation: {lines}"
    )
    for line in gate:
        assert line.index("pm_estimate(") < line.index("create on approval"), (
            f"{path.name}: creation precedes estimation on the gate line: {line!r}"
        )


@pytest.mark.parametrize("path", _both("agent-pm"))
def test_agent_estimate_step_says_it_runs_before_points_are_written(path):
    """The agent has no numbered write step to order against — it says so in prose."""
    lines = [line for line in _text(path).splitlines() if "**Estimate**" in line]
    assert lines, f"{path.name}: the agent lost its Estimate step"
    for line in lines:
        assert PM_ESTIMATE_CALL.search(line), f"{path.name}: {line!r} names no pm_estimate()"
        assert re.search(r"before\b[^\n]*\bpoints\b", line), (
            f"{path.name}: the Estimate step never says it runs before points "
            f"are written: {line!r}"
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
