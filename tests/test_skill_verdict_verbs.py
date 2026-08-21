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

import anyio
import pytest

from projectman.cli import _render_template
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
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
