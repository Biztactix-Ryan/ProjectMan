"""US-PM-11-7 — the orchestrator threads the audit digest through its poll.

Story US-PM-11's diagnosis is that the usage studies read ``pm-orchestrate``'s
periodic ``pm_audit`` as waste — Study D found 92 of 139 calls byte-identical
within one session and recommended caching ``pm_audit`` per session.  That
recommendation is wrong: the repeat *is* the health check (step 21 re-runs the
audit every 3 accepted tasks and stops the run on a new ERROR-level finding),
and caching it would disable the one thing that catches drift mid-run.

US-PM-11-5/6 built the right fix on the server: every report carries a
``digest: <16 hex>`` line, and ``pm_audit(since=<digest>)`` answers an
unchanged project with ``unchanged: true`` in under 100 bytes without running a
single check.  This module pins the *skill* half — that the orchestrator
actually uses it — in both directions:

* the poll survives — step 21 still re-runs ``pm_audit`` and still stops on new
  ERROR-level findings, so a later "simplification" cannot quietly delete the
  health check the studies argued against;
* the poll is cheap — step 21 passes ``since=``, pre-flight step 2 records the
  digest that feeds it, and the changed branch refreshes it, so a later edit
  cannot silently restore the full-report cost;
* the pin is not cosmetic — the literals the skill tells the orchestrator to
  look for (``digest: ``, ``unchanged: true``) are the ones ``projectman.audit``
  actually emits, and ``since`` is really a parameter of the ``pm_audit`` tool.
  A skill watching for a phrase the server never prints would be a health check
  that always reads as "changed" — or worse, always as "fine".

Both the template (source of truth) and the tracked rendered ``SKILL.md`` are
checked via the shared ``DOCS`` parametrization; their byte-for-byte equality is
owned by ``tests/test_skill_verdict_verbs.py``, and the server-side semantics of
``since`` by ``tests/test_audit_since_short_circuit.py``.  Helpers are imported
rather than copied.
"""

import inspect
import re

import pytest

from projectman.audit import (
    DIGEST_LENGTH,
    DIGEST_LINE_PREFIX,
    UNCHANGED_LINE,
    run_audit,
)
from projectman.store import clear_all_caches
from tests.test_skill_guidance_tools import _step
from tests.test_skill_verdict_verbs import DOCS, _text

# ─── the steps under test ────────────────────────────────────────

#: pre-flight: the first ``pm_audit``, where the digest is first recorded
PREFLIGHT_STEP = "2."

#: the periodic health check
HEALTH_STEP = "21."

#: the stop-conditions block, which must stay consistent with step 21
STOP_HEADING = "## Stop Conditions"


def _stop_conditions(text: str) -> str:
    """The stop-conditions block: its heading up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(STOP_HEADING)]
    assert starts, f"no {STOP_HEADING!r} heading — cannot check consistency"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


# ─── the poll survives ───────────────────────────────────────────


@pytest.mark.parametrize("doc", DOCS)
def test_the_health_check_still_re_runs_the_audit(doc):
    """Step 21 must remain a real ``pm_audit`` call, not a cached lookup."""
    step = _step(_text(doc), HEALTH_STEP)
    assert "pm_audit" in step, (
        f"step {HEALTH_STEP} no longer calls pm_audit in {doc} — the health "
        "check the studies recommended deleting has been deleted"
    )
    assert "every 3 accepted tasks" in step, (
        f"step {HEALTH_STEP} in {doc} lost its cadence — the poll must stay "
        "periodic, not once-per-run"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_health_check_still_stops_on_new_errors(doc):
    """The safety property: a changed audit with new ERRORs halts the run."""
    step = _step(_text(doc), HEALTH_STEP)
    assert "stop" in step.lower(), f"step {HEALTH_STEP} in {doc} no longer stops"
    assert "ERROR-level" in step, (
        f"step {HEALTH_STEP} in {doc} no longer names ERROR-level findings as "
        "the stop condition"
    )


# ─── the poll is cheap ───────────────────────────────────────────


@pytest.mark.parametrize("doc", DOCS)
def test_preflight_records_the_digest(doc):
    """Step 2 must capture the digest step 21 spends."""
    step = _step(_text(doc), PREFLIGHT_STEP)
    assert DIGEST_LINE_PREFIX.strip() in step, (
        f"pre-flight step {PREFLIGHT_STEP} in {doc} never mentions the digest, "
        f"so step {HEALTH_STEP} has nothing to pass as since="
    )
    assert "last audit digest" in step, (
        f"pre-flight step {PREFLIGHT_STEP} in {doc} does not name the recorded "
        "value 'last audit digest' — step 21 refers to it by that name"
    )
    assert f"<{DIGEST_LENGTH} hex>" in step, (
        f"pre-flight step {PREFLIGHT_STEP} in {doc} no longer describes the "
        f"digest's shape ({DIGEST_LENGTH} hex chars)"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_health_check_passes_the_previous_digest(doc):
    """The acceptance criterion itself: step 21 calls ``pm_audit(since=...)``."""
    step = _step(_text(doc), HEALTH_STEP)
    assert "pm_audit(since=" in step, (
        f"step {HEALTH_STEP} in {doc} calls pm_audit without since= — every "
        "poll pays for a full report again"
    )
    assert "last audit digest" in step, (
        f"step {HEALTH_STEP} in {doc} does not spend the 'last audit digest' "
        "recorded in pre-flight"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_an_unchanged_answer_passes_the_check(doc):
    """The cheap branch is spelled out, using the line the server prints."""
    step = _step(_text(doc), HEALTH_STEP)
    assert UNCHANGED_LINE in step, (
        f"step {HEALTH_STEP} in {doc} never mentions {UNCHANGED_LINE!r} — the "
        "orchestrator cannot recognize the short answer"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_changed_branch_refreshes_the_digest(doc):
    """Without this the poll re-sends a stale digest and never short-circuits."""
    step = _step(_text(doc), HEALTH_STEP)
    lowered = step.lower()
    assert "new last audit digest" in lowered, (
        f"step {HEALTH_STEP} in {doc} does not update the last audit digest "
        "after a changed report — every later poll would miss"
    )


# ─── consistency and the reviewer note ───────────────────────────


@pytest.mark.parametrize("doc", DOCS)
def test_the_stop_conditions_stay_consistent_with_the_cheap_answer(doc):
    """The block must not read as if an ``unchanged`` answer could stop a run."""
    block = _stop_conditions(_text(doc))
    assert "pm_audit" in block, f"{doc}: stop conditions no longer mention pm_audit"
    assert "unchanged" in block, (
        f"{doc}: the stop-conditions block does not account for the "
        "short-circuit answer, so it contradicts step 21"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_reviewer_note_defends_the_repeat(doc):
    """The studies' 'waste' finding must not be re-applied by a later reader."""
    step = _step(_text(doc), HEALTH_STEP)
    lowered = step.lower()
    assert "reviewers" in lowered, (
        f"step {HEALTH_STEP} in {doc} lost the note for reviewers explaining "
        "why the repeated pm_audit calls are intentional"
    )
    assert "by design" in lowered or "as designed" in lowered, (
        f"{doc}: the reviewer note no longer says the repeat is deliberate"
    )
    assert "cach" in lowered, (
        f"{doc}: the reviewer note no longer rejects caching pm_audit per "
        "session — the recommendation it exists to refuse"
    )


# ─── the pin is not cosmetic ─────────────────────────────────────


def test_the_literals_the_skill_watches_for_are_the_ones_audit_emits():
    """Guards the phrases above against a server-side rename."""
    assert UNCHANGED_LINE == "unchanged: true"
    assert DIGEST_LINE_PREFIX == "digest: "
    assert DIGEST_LENGTH == 16


def test_pm_audit_really_takes_a_since_parameter():
    """A skill passing ``since=`` to a tool without it would error mid-run."""
    from projectman import server

    fn = getattr(server.pm_audit, "fn", server.pm_audit)
    params = inspect.signature(fn).parameters
    assert "since" in params, "pm_audit has no since parameter for step 21 to pass"


# ─── the literals, checked against a real response ───────────────
#
# The two tests above pin the skill's phrases to ``projectman.audit``'s module
# constants, which is one hop short of the thing that matters: a constant can
# keep its value while the *renderer* stops printing it where the skill says to
# look.  The tests below close that hop for US-PM-11-4 — they pull the literal
# tokens out of the skill's own prose and hand them to a real ``run_audit``.


def _quoted_in(step: str, needle: str) -> str:
    """The backtick-quoted span of *step* containing *needle*.

    Reads the literal the skill actually tells the orchestrator to look for,
    so these tests cannot pass by re-asserting a constant the skill no longer
    quotes.
    """
    spans = [s for s in re.findall(r"`([^`]+)`", step) if needle in s]
    assert spans, f"no backtick-quoted token containing {needle!r} in:\n{step}"
    return spans[0]


@pytest.mark.parametrize("doc", DOCS)
def test_the_digest_line_the_skill_reads_is_where_a_real_report_puts_it(doc, tmp_project):
    """Step 2 says "the ``digest:`` line under the report's title" — verify it."""
    clear_all_caches()
    step = _step(_text(doc), PREFLIGHT_STEP)
    quoted = _quoted_in(step, "digest:")  # e.g. "digest: <16 hex>"
    prefix = quoted.split("<")[0]

    report = run_audit(tmp_project).splitlines()
    title = next(n for n, line in enumerate(report) if line.startswith("# "))
    following = next(line for line in report[title + 1:] if line.strip())
    assert following.startswith(prefix), (
        f"{doc} tells the orchestrator to read a {prefix!r} line under the "
        f"report's title, but a real report puts {following!r} there"
    )
    value = following[len(prefix):].strip()
    assert re.fullmatch(r"[0-9a-f]{%d}" % DIGEST_LENGTH, value), (
        f"{doc} describes the digest as {quoted!r}, but a real report emits "
        f"{value!r}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_unchanged_phrase_the_skill_watches_for_is_what_a_real_poll_answers(
    doc, tmp_project
):
    """Step 21's pass condition, run against a real ``pm_audit(since=...)``."""
    clear_all_caches()
    health = _step(_text(doc), HEALTH_STEP)
    pass_phrase = _quoted_in(health, "unchanged")
    prefix = _quoted_in(_step(_text(doc), PREFLIGHT_STEP), "digest:").split("<")[0]

    first = run_audit(tmp_project)
    digest = next(
        line[len(prefix):].strip()
        for line in first.splitlines()
        if line.startswith(prefix)
    )
    answer = run_audit(tmp_project, since=digest)
    assert pass_phrase in answer, (
        f"{doc} passes the health check on {pass_phrase!r}, but the real "
        f"unchanged answer is:\n{answer}"
    )
    assert len(answer) < len(first), "the short answer is not shorter"


@pytest.mark.parametrize("doc", DOCS)
def test_no_other_pm_audit_mention_contradicts_the_digest_flow(doc):
    """Every other place the skill names ``pm_audit`` must agree with step 21."""
    text = _text(doc)
    calls = set(re.findall(r"pm_audit\(([^)]*)\)", text))
    assert calls == {"since=<last audit digest>"}, (
        f"{doc} calls pm_audit with arguments somewhere other than step "
        f"{HEALTH_STEP}'s since= form: {sorted(calls)}"
    )
    for line in text.splitlines():
        if "cach" in line.lower():
            assert "disable" in line.lower(), (
                f"{doc} mentions caching without rejecting it: {line!r}"
            )
