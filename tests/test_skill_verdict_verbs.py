"""US-PM-8-3 — the orchestrator skill must keep saying its verdicts by verb.

Story US-PM-8's diagnosis was that step 19 of ``pm-orchestrate`` asked the
model to spell each of its four terminal moves as a generic ``pm_update`` with
the right status + outcome + note *triple*.  The measured cost: 13% of
``status=done`` writes carried no run-log entry at all, and the outcome
vocabulary collapsed to ~90% ``success``.  US-PM-8-9 rewrote the skill so each
verdict is named by its own verb — Accept → ``pm_accept``, Retry →
``pm_retry``, Park → ``pm_park``, Accept-as-review → ``pm_review`` — with
``pm_release`` from US-PM-7 for the un-dispatched claim.

The verbs themselves are pinned structurally in ``tests/test_verdict_verbs.py``.
What *this* file pins is the instruction site, for the same reason
``test_skill_release_instructions.py`` exists: the ``pm_done_next`` docstring at
``server.py:1343`` already told the model to stop hand-rolling
``pm_grab``-then-``pm_update(done)``, and it lost — 512 hand-rolled pairs to 387
docstring-obeying calls.  A prose fix does not stay fixed on its own.

One deliberate exception, and the reason a naive "no ``pm_update`` anywhere"
assertion would be wrong: the **Worker Prompt Template**'s fenced block still
tells *workers* to self-report via ``pm_update``.  Workers do not pass verdicts;
the orchestrator does.  So the flow assertions here strip fenced blocks first,
and ``test_worker_prompt_fence_still_self_reports_via_pm_update`` keeps that
strip honest — if the fence ever stops mentioning ``pm_update``, the stripping
has gone vacuous and the negative tests below would pass for the wrong reason.

Both the template (source of truth) and the tracked rendered ``SKILL.md`` are
checked, plus their byte-for-byte equality, so neither can drift from the other.
"""

import re
import subprocess

import anyio
import pytest

from projectman.cli import _render_template
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
    RENDERED_SKILLS,
    REPO_ROOT,
    TEMPLATES,
)

ORCHESTRATE_TEMPLATE_NAME = "skill_pm_orchestrate.md.j2"

#: step 19's verdict bullets — bold label as written → the verb that must say it
VERDICTS = {
    "Accept": "pm_accept",
    "Retry": "pm_retry",
    "Park": "pm_park",
    "Accept-as-review": "pm_review",
}

#: the two documents that must agree, identified for readable test ids
DOCS = [
    pytest.param(ORCHESTRATE_TEMPLATE, id="template"),
    pytest.param(ORCHESTRATE_SKILL, id="rendered"),
]

#: ``pm_update(`` but never ``pm_update_sprint(`` — the latter is a different
#: tool and step 24 legitimately calls it with ``status=``.
PM_UPDATE_CALL = re.compile(r"\bpm_update\(")
FENCE = re.compile(r"^```", re.MULTILINE)


def _text(path) -> str:
    return path.read_text(encoding="utf-8")


def _step_19(text: str) -> str:
    """The step-19 block: from the line starting ``19.`` up to ``20.``."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("19.")]
    ends = [n for n, line in enumerate(lines) if line.startswith("20.")]
    assert starts, "no line starting with '19.' — the verdict step vanished"
    assert ends, "no line starting with '20.' — cannot bound the verdict step"
    start = starts[0]
    end = next(n for n in ends if n > start)
    return "\n".join(lines[start:end])


def _fences(text: str) -> list[str]:
    """The contents of every fenced ``` block, in order."""
    parts = FENCE.split(text)
    # parts alternate outside/inside/outside/... — odd indices are inside fences
    return parts[1::2]


def _outside_fences(text: str) -> str:
    """The prose the orchestrator itself follows, with fenced blocks removed."""
    return "\n".join(FENCE.split(text)[0::2])


def _schemas() -> dict:
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ═══ step 19 — one verb per verdict ═════════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_step_19_block_is_extractable_and_is_the_verdict_step(path):
    """Guard the slice itself: every assertion below is scoped to this text."""
    block = _step_19(_text(path))
    assert "Verdict" in block.splitlines()[0], block.splitlines()[0]
    assert len(block.splitlines()) >= 5, "step 19 lost its verdict bullets"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("label,verb", sorted(VERDICTS.items()))
def test_each_verdict_bullet_names_its_own_verb(path, label, verb):
    """Accept→pm_accept, Retry→pm_retry, Park→pm_park, Accept-as-review→pm_review.

    Label and verb must land on the *same* bullet: a skill that lists the four
    verbs somewhere in step 19 but pairs them with the wrong verdicts would be
    worse than useless, and a text-wide ``in`` check could not tell.
    """
    bullets = [
        line for line in _step_19(_text(path)).splitlines() if f"**{label}**" in line
    ]
    assert len(bullets) == 1, f"expected exactly one **{label}** bullet in {path.name}"
    assert f"{verb}(" in bullets[0], (
        f"{path.name}: the **{label}** bullet does not call {verb}(): {bullets[0]!r}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_19_names_all_four_verbs_and_no_others(path):
    """No fifth verdict, and no verb quietly dropped."""
    named = set(re.findall(r"\bpm_[a-z_]+(?=\()", _step_19(_text(path))))
    assert named == set(VERDICTS.values()), named


@pytest.mark.parametrize("path", DOCS)
def test_step_19_never_spells_a_verdict_as_pm_update(path):
    """The regression itself: the verdict is a verb, never a values triple."""
    offenders = [
        line.strip()
        for line in _step_19(_text(path)).splitlines()
        if PM_UPDATE_CALL.search(line)
    ]
    assert not offenders, f"{path.name} step 19 spells a verdict as pm_update:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_19_never_calls_pm_done_next(path):
    """``pm_accept`` absorbed ``pm_done_next``'s next-task return (US-PM-8-9)."""
    offenders = [
        line.strip()
        for line in _step_19(_text(path)).splitlines()
        if "pm_done_next" in line
    ]
    assert not offenders, f"{path.name} step 19 still calls pm_done_next:\n" + "\n".join(
        offenders
    )


# ═══ the whole orchestrator flow, outside the worker prompt ═════


@pytest.mark.parametrize("path", DOCS)
def test_orchestrator_flow_never_instructs_pm_done_next(path):
    """Not just step 19 — no step of the orchestrator's own flow may reach for it."""
    offenders = [
        line.strip()
        for line in _outside_fences(_text(path)).splitlines()
        if "pm_done_next" in line
    ]
    assert not offenders, f"{path.name} instructs pm_done_next outside a fence:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("path", DOCS)
def test_orchestrator_flow_never_instructs_a_status_carrying_pm_update(path):
    """A ``pm_update(..., status=...)`` anywhere in the flow is a verdict in disguise."""
    offenders = [
        line.strip()
        for line in _outside_fences(_text(path)).splitlines()
        if PM_UPDATE_CALL.search(line) and "status=" in line
    ]
    assert not offenders, f"{path.name} instructs pm_update with a status:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("path", DOCS)
def test_worker_prompt_fence_still_self_reports_via_pm_update(path):
    """The deliberate exception — and the guard on the two tests above.

    Workers do not pass verdicts; they self-report, and the worker prompt says
    so inside its fenced block.  If that mention ever disappears, the fence
    stripping has stopped excluding anything and the negative assertions above
    would be passing vacuously.
    """
    fenced = "\n".join(_fences(_text(path)))
    assert "pm_update" in fenced, (
        f"{path.name}: no fenced block mentions pm_update — the worker prompt "
        "changed, so the fence-stripping in this module needs re-checking"
    )


# ═══ the rendered copy is generated, not hand-maintained ════════


def test_rendered_orchestrate_skill_is_byte_identical_to_its_template():
    """``setup-claude`` renders this template with no kwargs; the tracked copy
    must be exactly what that produces, or the source of truth is not."""
    assert _text(ORCHESTRATE_SKILL) == _render_template(ORCHESTRATE_TEMPLATE_NAME)


# ═══ the named verbs exist ══════════════════════════════════════


@pytest.mark.parametrize("verb", sorted(VERDICTS.values()))
def test_every_verb_named_in_step_19_is_a_registered_tool(verb):
    """The skill can never instruct a verb the server does not serve."""
    assert verb in _schemas()


def test_the_skill_names_exactly_the_registered_verdict_verbs():
    """Cross-check in the other direction: the set in the skill is the set here."""
    named = set(re.findall(r"\bpm_[a-z_]+(?=\()", _step_19(_text(ORCHESTRATE_SKILL))))
    registered = set(_schemas())
    assert named <= registered, sorted(named - registered)
    assert named == set(VERDICTS.values())


# ═══ park with a decision (US-PM-64-5) ══════════════════════════
#
# US-PM-64-9 gave ``pm_park`` a ``decision`` argument that raises a decision
# blocking the parked task; US-PM-64-10 told the skills to use it.  A worker
# needing a human call leaves a structured question, not a free-text note, so
# the instruction sites are pinned: pm-do's outcome step, the orchestrator's
# Park verb and the worker prompt's blocker rule.  Phase 4's "Decisions raised"
# section is pinned in ``test_skill_activity_report.py``; the budgets both
# skills must stay within, in ``test_orchestrate_skill_size.py`` and
# ``test_skill_guard_prose.py``.

#: pm-do, template and tracked rendered copy
PM_DO_DOCS = [
    pytest.param(TEMPLATES / "skill_pm_do.md.j2", id="pm-do-template"),
    pytest.param(RENDERED_SKILLS / "pm-do" / "SKILL.md", id="pm-do-rendered"),
]

#: the last commit before US-PM-64-10 taught the skills the decision argument
PRE_DECISION_COMMIT = "07a2d08"

DECISION_ARG = re.compile(r"\bdecision=")


def _decision_keys() -> tuple:
    from projectman.server import _PARK_DECISION_KEYS

    return _PARK_DECISION_KEYS


def _numbered_block(text: str, start: str, end: str) -> str:
    """Lines from the one starting ``start`` up to the next starting ``end``."""
    lines = text.splitlines()
    first = next((n for n, line in enumerate(lines) if line.startswith(start)), None)
    assert first is not None, f"no line starting with {start!r}"
    last = next(
        (n for n in range(first + 1, len(lines)) if lines[n].startswith(end)), len(lines)
    )
    return "\n".join(lines[first:last])


def pm_do_human_call_bullets(text: str) -> list[str]:
    """pm-do step 6 bullets that park a human call with a decision."""
    return [
        line
        for line in _numbered_block(text, "6.", "7.").splitlines()
        if "human" in line.lower() and "pm_park(" in line and DECISION_ARG.search(line)
    ]


def park_bullet_mentions_decision(text: str) -> bool:
    """Step 19's **Park** bullet names the ``decision=`` argument."""
    bullets = [line for line in _step_19(text).splitlines() if "**Park**" in line]
    return len(bullets) == 1 and bool(DECISION_ARG.search(bullets[0]))


def worker_blocker_rule(text: str) -> str:
    """The worker prompt's blocker rule, whitespace-collapsed; empty if absent."""
    fence = next((f for f in _fences(text) if "You are executing" in f), "")
    flat = " ".join(fence.split())
    start = flat.find("Blockers:")
    if start < 0:
        return ""
    end = flat.find("Report back", start)
    return flat[start:end] if end > start else flat[start:]


def worker_blocker_rule_parks_with_decision(text: str) -> bool:
    rule = worker_blocker_rule(text)
    return "pm_park(" in rule and bool(DECISION_ARG.search(rule))


@pytest.mark.parametrize("path", PM_DO_DOCS)
def test_pm_do_parks_a_human_call_with_a_decision(path):
    """A worker needing a human call parks with a decision, not a bare note."""
    bullets = pm_do_human_call_bullets(_text(path))
    assert len(bullets) == 1, (
        f"{path.name} step 6 has {len(bullets)} human-call pm_park(decision=) "
        "bullets, expected exactly one"
    )


@pytest.mark.parametrize("path", PM_DO_DOCS)
def test_pm_do_names_every_decision_key_pm_park_accepts(path):
    """The keys pm-do spells are exactly the ones pm_park validates."""
    (bullet,) = pm_do_human_call_bullets(_text(path))
    payload = re.search(r"decision=\{([^}]*)\}", bullet)
    assert payload, f"{path.name}: the decision argument spells no {{...}} payload"
    named = {key.strip() for key in payload.group(1).split(",")}
    assert named == set(_decision_keys()), (
        f"{path.name} names decision keys {sorted(named)}; pm_park accepts "
        f"{sorted(_decision_keys())}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_park_verb_mentions_the_decision_argument(path):
    """Step 19's Park verb tells the orchestrator about ``decision=``."""
    assert park_bullet_mentions_decision(_text(path)), (
        f"{path.name}: the **Park** bullet does not mention decision="
    )


@pytest.mark.parametrize("path", DOCS)
def test_worker_blocker_rule_parks_a_human_call_with_a_decision(path):
    """The worker prompt's blocker rule names pm_park with ``decision=``."""
    rule = worker_blocker_rule(_text(path))
    assert rule, f"{path.name}: no 'Blockers:' rule in the worker prompt fence"
    assert worker_blocker_rule_parks_with_decision(_text(path)), (
        f"{path.name}: the blocker rule does not park with decision=: {rule!r}"
    )


def test_pm_park_serves_the_decision_argument():
    """The argument every check above names is one the server accepts."""
    properties = _schemas()["pm_park"].inputSchema["properties"]
    assert "decision" in properties, sorted(properties)


def test_the_decision_checks_reject_the_pre_decision_skills():
    """Falsification guard: the skills before US-PM-64-10 fail every check."""

    def old(name: str) -> str:
        try:
            return subprocess.run(
                ["git", "show", f"{PRE_DECISION_COMMIT}:src/projectman/templates/{name}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no history
            pytest.skip(f"git history for {PRE_DECISION_COMMIT} unavailable")

    orchestrate = old(ORCHESTRATE_TEMPLATE_NAME)
    pm_do = old("skill_pm_do.md.j2")
    assert _numbered_block(pm_do, "6.", "7.") and worker_blocker_rule(orchestrate), (
        "guard input lost its anchors"
    )
    assert not pm_do_human_call_bullets(pm_do)
    assert not park_bullet_mentions_decision(orchestrate)
    assert not worker_blocker_rule_parks_with_decision(orchestrate)
