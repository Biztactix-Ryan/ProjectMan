"""US-PM-14-6 — pre-flight classifies claims instead of guessing at them.

``pm-orchestrate``'s Phase 1 step 3 used to read, in full:

    Call ``pm_board`` and ``pm_active``. If sprint tasks are ``in-progress``
    and assigned to someone that isn't a previous orchestrator run, warn and
    ask before proceeding.

Every load-bearing word there was a guess.  "Isn't a previous orchestrator
run" was unanswerable — ``assignee`` is ``claude`` for every run of every
agent on the machine — so the step always degraded to asking a human, which
is exactly what a crashed run cannot do.  US-PM-14-5 supplied the missing
facts: ``claimed_by_run`` on the task, ``claim_age`` / ``stale`` on
``pm_active``, ``run_id`` on the activity-log event, and a ``run_id``
parameter on every claim-taking verb.  US-PM-14-6 spends them.

This module pins the instruction site, in the manner of
``tests/test_skill_audit_digest.py`` — over the template (source of truth) and
the tracked rendered ``SKILL.md`` alike, with their byte-for-byte equality
owned by ``tests/test_skill_verdict_verbs.py``:

* **the run id exists** — Phase 0 mints an ``orch-`` prefixed id and step 3's
  classification is defined in terms of that prefix;
* **the run id is spent** — ``run_id=`` rides on the orchestrator's own
  ``pm_grab`` and accepting verb, and on the worker prompt's ``pm_grab``, so
  the next run has something to recover *from*;
* **the classification is deterministic** — ``claimed_by_run``, ``stale`` and
  a real ``pm_activity`` query decide it, human claims are never touched, and
  the warn-and-ask sentence is gone from the whole document;
* **the pin is not cosmetic** — the field names the skill tells the
  orchestrator to read are pulled out of its own prose and checked against a
  real ``pm_active`` response holding a real stale claim, and every keyword
  argument it names is checked against the real tool signature.  A skill
  telling the orchestrator to read a key the server never emits would be a
  recovery path that silently recovers nothing.
"""

import inspect
import re
from datetime import datetime

import pytest
import yaml

from tests.test_skill_guidance_tools import _step, _worker_fence
from tests.test_skill_verdict_verbs import DOCS, _outside_fences, _text

# ─── the steps under test ────────────────────────────────────────

#: the claim-classification step
CLASSIFY_STEP = "3."

#: the task-picking step, which must agree with step 3's verdicts
PICK_STEP = "12."

#: the heading Phase 0 grew for the run id
RUN_ID_HEADING = "### Run id"

#: the prefix that separates an orchestrator's claim from a human's
RUN_ID_PREFIX = "orch-"

#: the guess this task deleted, in the spellings it could come back as
BANNED_PHRASES = ("ask before proceeding", "warn and ask")

#: the claim-metadata keys step 3 is built on
CLAIM_KEYS = ("claimed_by_run", "claim_age", "stale")


def _run_id_section(text: str) -> str:
    """Phase 0's run-id subsection: its heading up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(RUN_ID_HEADING)]
    assert starts, f"no {RUN_ID_HEADING!r} heading — the run id is never minted"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


# ═══ 1. the run id exists ═══════════════════════════════════════


@pytest.mark.parametrize("doc", DOCS)
def test_phase_0_mints_a_run_id_for_this_run(doc):
    """Without an id chosen up front there is nothing to recognize later."""
    section = _run_id_section(_text(doc))
    assert RUN_ID_PREFIX in section, (
        f"{doc}: the run-id section never names the {RUN_ID_PREFIX!r} prefix "
        "step 3 classifies on"
    )
    lowered = section.lower()
    assert "mint" in lowered or "choose" in lowered, (
        f"{doc}: the run-id section does not tell the orchestrator to pick an "
        f"id for this run:\n{section}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_run_id_section_precedes_the_step_that_spends_it(doc):
    """Minting after pre-flight would leave step 3 with nothing to compare."""
    text = _text(doc)
    assert text.index(_run_id_section(text)) < text.index(_step(text, CLASSIFY_STEP)), (
        f"{doc}: the run id is minted after step {CLASSIFY_STEP} reads it"
    )


# ═══ 2. the run id is spent ═════════════════════════════════════


@pytest.mark.parametrize("doc", DOCS)
def test_the_orchestrators_own_claim_carries_the_run_id(doc):
    """``pm_grab`` without ``run_id=`` records an anonymous per-process owner."""
    flow = _outside_fences(_text(doc))
    grabs = re.findall(r"pm_grab\(([^)]*)\)", flow)
    assert grabs, f"{doc}: the orchestrator flow never calls pm_grab()"
    assert any("run_id=" in args for args in grabs), (
        f"{doc}: no pm_grab in the orchestrator flow passes run_id=: {grabs}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_task_picking_step_reclaims_under_this_run(doc):
    """Step 12 is where a recovered claim actually changes hands."""
    step = _step(_text(doc), PICK_STEP)
    assert "run_id=" in step, (
        f"step {PICK_STEP} in {doc} re-claims without run_id=, so a recovered "
        f"task stays owned by the dead run:\n{step}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_accepting_verb_carries_the_run_id(doc):
    """``pm_accept`` claims the *next* task — that claim needs an owner too."""
    accepts = re.findall(r"pm_accept\(([^)]*)\)", _text(doc), re.DOTALL)
    assert accepts, f"{doc}: pm_accept is never called"
    assert any("run_id=" in args for args in accepts), (
        f"{doc}: no pm_accept passes run_id=, so the task it pre-claims is "
        f"owned by nobody: {accepts}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_worker_prompt_passes_the_orchestrators_run_id(doc):
    """A worker's own ``pm_grab`` must claim under the run that dispatched it."""
    fence = _worker_fence(_text(doc))
    grabs = re.findall(r"pm_grab\(([^)]*)\)", fence)
    assert grabs, f"{doc}: the worker prompt never names pm_grab()"
    assert all("run_id=" in args for args in grabs), (
        f"{doc}: a worker's pm_grab omits run_id=, so its claim is not "
        f"attributable to this run: {grabs}"
    )


# ═══ 3. the classification is deterministic ═════════════════════


@pytest.mark.parametrize("doc", DOCS)
def test_step_3_is_extractable_and_is_the_classification_step(doc):
    """Guard the slice: every assertion below is scoped to this text."""
    step = _step(_text(doc), CLASSIFY_STEP)
    assert "pm_active" in step, f"step {CLASSIFY_STEP} in {doc} no longer reads pm_active"
    assert len(step.splitlines()) >= 4, (
        f"step {CLASSIFY_STEP} in {doc} lost its classification branches:\n{step}"
    )


@pytest.mark.parametrize("doc", DOCS)
@pytest.mark.parametrize("key", CLAIM_KEYS)
def test_step_3_consults_the_claim_metadata(doc, key):
    """The three facts that replaced the guess."""
    step = _step(_text(doc), CLASSIFY_STEP)
    assert key in step, (
        f"step {CLASSIFY_STEP} in {doc} never reads `{key}` — it is back to "
        "inferring ownership from the assignee"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_step_3_queries_the_activity_log(doc):
    """The acceptance criterion: liveness is answered by ``pm_activity``."""
    step = _step(_text(doc), CLASSIFY_STEP)
    calls = re.findall(r"pm_activity\(([^)]*)\)", step)
    assert calls, (
        f"step {CLASSIFY_STEP} in {doc} never calls pm_activity — the "
        "authoritative record of what the previous run did goes unread"
    )
    assert any("item_id=" in args for args in calls), (
        f"step {CLASSIFY_STEP} in {doc} calls pm_activity unscoped: {calls}"
    )
    assert any("event_type=" in args for args in calls), (
        f"step {CLASSIFY_STEP} in {doc} calls pm_activity without an "
        f"event_type filter: {calls}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_step_3_classifies_on_the_run_id_prefix(doc):
    """An orchestrator's claim and a human's are told apart by the prefix."""
    step = _step(_text(doc), CLASSIFY_STEP)
    assert RUN_ID_PREFIX in step, (
        f"step {CLASSIFY_STEP} in {doc} does not name the {RUN_ID_PREFIX!r} "
        "prefix, so it cannot tell an orchestrator's claim from a human's"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_step_3_reclaims_a_dead_runs_task(doc):
    """Recovery is an action, not an observation — and it leaves a record."""
    step = _step(_text(doc), CLASSIFY_STEP)
    assert re.search(r"pm_grab\([^)]*run_id=", step), (
        f"step {CLASSIFY_STEP} in {doc} never re-claims with "
        f"pm_grab(..., run_id=...):\n{step}"
    )
    assert "recovered from run" in step, (
        f"step {CLASSIFY_STEP} in {doc} takes a claim back without logging "
        "'recovered from run <old>' — the recovery leaves no trace"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_step_3_never_touches_a_human_claim(doc):
    """The one class of claim that stays untouched whatever its age."""
    step = _step(_text(doc), CLASSIFY_STEP)
    lowered = step.lower()
    assert "human" in lowered, (
        f"step {CLASSIFY_STEP} in {doc} no longer distinguishes a human's claim"
    )
    assert "never touch" in lowered, (
        f"step {CLASSIFY_STEP} in {doc} does not forbid taking a human's "
        f"claim:\n{step}"
    )


@pytest.mark.parametrize("doc", DOCS)
@pytest.mark.parametrize("phrase", BANNED_PHRASES)
def test_the_guess_is_gone_from_the_whole_document(doc, phrase):
    """Not just step 3: no other site may restate the sentence it replaced."""
    text = _text(doc).lower()
    assert phrase not in text, (
        f"{doc} still instructs {phrase!r} — the ownership guess is back"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_picking_step_defers_to_the_classification(doc):
    """Step 12's own ownership sentence must not re-derive the guess."""
    step = _step(_text(doc), PICK_STEP)
    assert f"step {CLASSIFY_STEP.rstrip('.')}" in step, (
        f"step {PICK_STEP} in {doc} decides ownership on its own instead of "
        f"using step {CLASSIFY_STEP}'s classification:\n{step}"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_a_resume_anchor_exists_for_the_documented_path(doc):
    """US-PM-14-4's criterion has a home; US-PM-14-8 fills it in."""
    headings = [
        line for line in _text(doc).splitlines() if line.startswith("## ")
    ]
    assert any("Resume" in line for line in headings), (
        f"{doc}: no Resume heading — the recovery procedure has nowhere to be "
        f"documented: {headings}"
    )


# ═══ 4. the pin is not cosmetic ═════════════════════════════════


def _tools() -> dict:
    from projectman import server

    return {
        name: getattr(getattr(server, name), "fn", getattr(server, name))
        for name in ("pm_active", "pm_activity", "pm_grab", "pm_release", "pm_accept")
    }


@pytest.mark.parametrize(
    "tool,kwarg",
    [
        ("pm_grab", "run_id"),
        ("pm_release", "run_id"),
        ("pm_accept", "run_id"),
        ("pm_active", "stale_after"),
        ("pm_activity", "item_id"),
        ("pm_activity", "event_type"),
    ],
)
def test_the_kwargs_the_skill_names_are_real_parameters(tool, kwarg):
    """A skill naming a parameter the signature lacks would fail mid-run."""
    params = inspect.signature(_tools()[tool]).parameters
    assert kwarg in params, f"{tool} has no {kwarg} parameter for the skill to pass"


@pytest.mark.parametrize("doc", DOCS)
def test_the_event_type_the_skill_filters_on_is_one_the_log_emits(doc):
    """``event_type="update"`` must name a real ``EventType`` member."""
    from projectman.models import EventType

    step = _step(_text(doc), CLASSIFY_STEP)
    values = re.findall(r'pm_activity\([^)]*event_type="([a-z]+)"', step)
    assert values, f"{doc}: step {CLASSIFY_STEP} names no literal event_type"
    known = {e.value for e in EventType}
    assert set(values) <= known, (
        f"{doc} filters pm_activity on {set(values) - known}, which the "
        f"activity log never writes (known: {sorted(known)})"
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_fields_step_3_reads_are_in_a_real_pm_active_response(
    doc, tmp_project, store, monkeypatch
):
    """The whole point, end to end: build a stale claim and read it back.

    Step 3 tells the orchestrator to branch on ``claimed_by_run`` / ``stale``
    and to consult ``stale_tasks`` / ``stale_after_hours``.  A constant can
    keep its name in ``server.py`` while the *response* stops carrying it, so
    the keys are pulled out of the skill's own prose and looked for in a real
    ``pm_active`` payload for a task claimed by a dead ``orch-`` run.
    """
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache, pm_active
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    from tests.test_claim_ownership import _backdate_claim, _story_with_tasks

    _story_with_tasks(store)
    dead_run = "orch-2026-08-21-dead"
    store.claim_task("US-TST-1-1", "claude", run_id=dead_run)
    _backdate_claim(store, "US-TST-1-1", minutes=600)

    result = yaml.safe_load(pm_active())
    task = result["active_tasks"][0]

    step = _step(_text(doc), CLASSIFY_STEP)
    quoted = set(re.findall(r"`([a-z_]+)`", step))

    for key in CLAIM_KEYS:
        assert key in quoted, f"{doc}: step {CLASSIFY_STEP} stopped quoting `{key}`"
        assert key in task, (
            f"{doc} tells the orchestrator to read `{key}` on an in-progress "
            f"task, but a real stale entry is {task!r}"
        )
    for key in ("stale_tasks", "stale_after_hours"):
        assert key in quoted, f"{doc}: step {CLASSIFY_STEP} stopped quoting `{key}`"
        assert key in result, (
            f"{doc} tells the orchestrator to read `{key}`, but a real "
            f"pm_active response has {sorted(result)}"
        )

    # ...and the values are the ones the classification branches on.
    assert task["stale"] is True
    assert task["claimed_by_run"] == dead_run
    assert task["claimed_by_run"].startswith(RUN_ID_PREFIX)
    assert result["stale_tasks"] == ["US-TST-1-1"]


def test_a_reclaim_by_a_new_run_really_takes_the_dead_runs_task(
    tmp_project, store, monkeypatch
):
    """Step 3's recovery move, executed: ``pm_grab(..., run_id=<this run>)``."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache, pm_grab
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    from tests.test_claim_ownership import _backdate_claim, _story_with_tasks

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="orch-2026-08-21-dead")
    stale_at = _backdate_claim(store, "US-TST-1-1", minutes=600)

    task = yaml.safe_load(pm_grab("US-TST-1-1", run_id="orch-2026-08-22-live"))[
        "grabbed"
    ]["task"]
    assert task["claimed_by_run"] == "orch-2026-08-22-live"
    assert datetime.fromisoformat(str(task["claimed_at"])) > stale_at, (
        "a takeover by a different run must reset claimed_at, or the "
        "recovered task would look stale to the run that just claimed it"
    )
