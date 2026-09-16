"""US-PM-54 — the orchestrator keeps the prompt cache warm through worker waits.

Every full prompt-cache miss measured on long orchestrated runs sat right after
a worker wait longer than the one-hour cache TTL, and each re-sent the whole
context at the 2x write price (19-45% of a run's input spend).  The fix is a
cached read before the entry expires: Phase 0 arms one session-only cron job
whose prompt has the orchestrator answer in a few words, and Phase 4 deletes
it.  These tests pin the shape that makes it work — the cadence, the
self-deleting prompt, the marker ``orch-cost`` counts firings by — and that the
rationale lives in the design doc rather than the skill.
"""

import re

from projectman.orch_cost import HEARTBEAT_MARKER

from tests.test_orchestrate_skill_size import (
    ORCHESTRATE_SKILL,
    REPO_ROOT,
    TEMPLATE_REPO_PATH,
    design_section,
)

TEMPLATE = REPO_ROOT / TEMPLATE_REPO_PATH


def _phase(text: str, heading: str) -> str:
    """The text of one ``## `` section of the skill."""
    match = re.search(rf"^## {re.escape(heading)}.*?(?=^## |\Z)", text, re.S | re.M)
    assert match, f"no section {heading!r}"
    return match.group(0)


def test_phase_0_arms_one_session_cron_heartbeat_every_30_minutes():
    phase0 = _phase(TEMPLATE.read_text(encoding="utf-8"), "Phase 0")
    assert phase0.count("CronCreate(") == 1
    # 13 and 43 past the hour: two beats an idle hour, each well inside the
    # one-hour TTL even with the scheduler's jitter, and off the :00/:30 marks.
    assert 'cron="13,43 * * * *"' in phase0
    assert "session-only" in phase0


def test_the_heartbeat_prompt_is_cheap_and_self_deleting():
    phase0 = _phase(TEMPLATE.read_text(encoding="utf-8"), "Phase 0")
    prompt = re.search(r'prompt="([^"]+)"', phase0)
    assert prompt, "the CronCreate call carries no prompt"
    text = prompt.group(1)
    # A few words and no tools: every token a beat emits is re-read by every
    # later call, and a tool call would make a beat two API calls, not one.
    assert "five words" in text and "no tools" in text
    # No run in flight -> the job removes itself, so a run that dies before
    # Phase 4 stops beating instead of paying a cached read every 30 minutes
    # until the session closes.
    assert "no run in flight" in text and "CronDelete" in text


def test_the_prompt_opens_with_the_marker_orch_cost_counts():
    """The run id is minted ``orch-…``, so ``Heartbeat <this run>`` fires as
    ``Heartbeat orch-…`` — exactly what ``orch_cost.HEARTBEAT_MARKER`` looks for."""
    phase0 = _phase(TEMPLATE.read_text(encoding="utf-8"), "Phase 0")
    assert 'prompt="Heartbeat <this run>' in phase0
    assert HEARTBEAT_MARKER == "Heartbeat orch-"
    assert "Mint `orch-" in phase0


def test_phase_4_deletes_the_heartbeat():
    phase4 = _phase(TEMPLATE.read_text(encoding="utf-8"), "Phase 4")
    assert "`CronDelete` the heartbeat" in phase4


def test_the_rendered_skill_carries_the_same_heartbeat():
    rendered = ORCHESTRATE_SKILL.read_text(encoding="utf-8")
    assert 'cron="13,43 * * * *"' in rendered
    assert "`CronDelete` the heartbeat" in rendered


def test_design_doc_holds_the_rationale_the_skill_does_not():
    doc = re.sub(r"\s+", " ", design_section("## Heartbeat"))
    for phrase in (
        "cachebeat",
        "30 minutes",
        "five-minute cache",
        "promptCacheTtl",
        "usage credits",
        "orch-cost",
    ):
        assert phrase in doc, f"Heartbeat section never mentions {phrase!r}"
    # The comparison that justifies the cadence is in the doc, not the skill.
    assert "ping every 4 minutes" in doc
    skill = TEMPLATE.read_text(encoding="utf-8")
    assert "cachebeat" not in skill
    assert not re.search(r"\bping", skill, re.IGNORECASE)
