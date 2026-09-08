"""Completions carrying no evidence are detectable (US-PM-9-8).

`docs/reference/evidence-contract.md` §5 is the binding design.  Its rule, as
narrowed by US-PM-43-6 and US-PM-43-7 so that every counted task is one
someone can act on:

    A completion without evidence is a task with `status == done` whose run
    log contains no entry whose `evidence` is not `None`, and which could have
    carried evidence — its run log has an entry written at or after this
    store's first evidence-bearing entry, or its `done` transition carries a
    `run_id`.  Anything else is a pre-contract completion and is not counted.

The line is the store's own first evidence, never a date: a store that has
never recorded evidence has never used the contract, so a bare verdict in it
counts for nothing, while a run-stamped `done` still counts everywhere.

Study C measured 163 of 1,266 done writes carrying no note or outcome at all —
today that is invisible.  Two paths make it visible, and both are asserted
here: the audit finding `done-without-evidence` (§5) and the query
`pm_run_log(id, has_evidence=False)` (§4, delivered by US-PM-9-7).

The properties that matter are exactly the ones a careless implementation
gets wrong:

* **presence, never truthiness** — `Evidence()` with four empty lists is the
  genuinely non-code task saying "nothing to show", and counts as evidence;
* **only completions that could have carried evidence** — a legacy done task
  with no run log and no run-stamped completion is invisible to this check,
  and so is a verdict written before this store had ever recorded evidence,
  because neither can gain any without history being edited;
* **one aggregate finding**, not one per task, so DRIFT.md gets one line;
* **warning, not error** — /pm-orchestrate halts a sprint on any error-level
  finding, and every task completed before evidence shipped trips this check;
* archived tasks and not-yet-done tasks are outside the definition entirely.

Covers contract §8's "US-PM-9-3" bullet.
"""

import json

import anyio
import mcp.types as types
import pytest

from projectman.audit import (
    _first_evidence_timestamp,
    check_completions_without_evidence,
    run_audit,
)
from projectman.models import Evidence
from projectman.store import Store, clear_all_caches

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

CHECK = "done-without-evidence"

SAMPLE_EVIDENCE = {
    "files": ["src/projectman/audit.py"],
    "tests": [
        {
            "command": "uv run pytest tests/test_audit_evidence.py",
            "passed": True,
            "summary": "9 passed",
        }
    ],
    "dod_met": ["done-without-evidence fires"],
    "dod_unmet": [],
}


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def store(tmp_project) -> Store:
    """One active story with six ready tasks."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, 7):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    return store


def _adopt_the_contract(store: Store, task_id: str = "US-TST-1-6") -> None:
    """Record this store's first evidence-bearing run-log entry.

    US-PM-43-7 measures "could have carried evidence" against the store's own
    first evidence rather than a date, so a fixture that wants a *later* bare
    verdict counted has to show the contract in use here first.  The carrier
    task stays open — it is the log entry's timestamp that matters, and an
    open task is outside the check entirely.
    """
    store.update(
        task_id, outcome="info", note="proved something on a sibling task",
        evidence=Evidence(files=["src/projectman/audit.py"]),
    )


def _findings(tmp_project) -> list[dict]:
    """The check's own findings, read from a Store that trusts nothing cached."""
    clear_all_caches()
    return check_completions_without_evidence(Store(tmp_project))


def _flagged(tmp_project) -> list[str]:
    findings = _findings(tmp_project)
    return findings[0]["items"] if findings else []


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


# ═══ §5 — what counts as a completion without evidence ══════════


def test_a_run_stamped_done_task_with_no_run_log_at_all_is_flagged(
    store, tmp_project
):
    """The 13% of completions with no run log — the measured invisible case.

    Under US-PM-43-6 the completion must be one that could have carried
    evidence, and a ``done`` transition stamped with a ``run_id`` is exactly
    that: an orchestrator accepted it under the contract and attached nothing.
    """
    store.update("US-TST-1-1", status="done", run_id="orch-test-1")
    assert not (tmp_project / ".project" / "logs" / "US-TST-1-1.jsonl").exists()

    assert _flagged(tmp_project) == ["US-TST-1-1"]


def test_a_legacy_done_task_is_not_counted_but_an_accepted_one_is(
    store, tmp_project
):
    """The US-PM-43-6 rule, both sides of it, in one project.

    A pre-contract completion — no run log, no run-stamped transition — has
    nothing evidence could have hung off and no way to ever gain one short of
    rewriting history, so counting it produces a warning that can never be
    cleared.  447 of those on this repo drowned the findings a reader could
    act on.  An orchestrator-accepted completion with no evidence is the real
    gap and still fires.
    """
    store.update("US-TST-1-1", status="done")  # legacy: no log, no run_id
    store.update("US-TST-1-2", status="done", run_id="orch-test-1")

    logs = tmp_project / ".project" / "logs"
    assert not (logs / "US-TST-1-1.jsonl").exists()
    assert not (logs / "US-TST-1-2.jsonl").exists()

    assert _flagged(tmp_project) == ["US-TST-1-2"]


# ═══ §5 — the line is this store's own first evidence (US-PM-43-7) ══


def test_a_store_that_has_never_recorded_evidence_reports_nothing(
    store, tmp_project
):
    """Bare verdicts alone are not a finding: this project predates the contract.

    Every entry here is a note/outcome written when nothing could have carried
    evidence — the state of 67 tasks on the ProjectMan repo itself.  Counting
    them produces a warning that can only be cleared by editing history, which
    is the noise US-PM-43 set out to remove.
    """
    store.update("US-TST-1-1", status="in-progress", outcome="info", note="started")
    store.update("US-TST-1-1", status="done", outcome="success", note="finished it")
    store.update("US-TST-1-2", status="done", outcome="success", note="finished too")

    logs = tmp_project / ".project" / "logs"
    assert not any('"evidence"' in p.read_text() for p in logs.glob("*.jsonl"))

    assert _findings(tmp_project) == []


def test_only_verdicts_written_after_the_first_evidence_are_counted(
    store, tmp_project
):
    """The cutoff moves with the record, and it is a real before/after.

    One task's verdict predates any evidence in this store; another's follows
    it.  Only the later one could have carried evidence, so only it is named —
    no date appears anywhere in the rule.
    """
    store.update("US-TST-1-1", status="done", outcome="success", note="before")
    assert _flagged(tmp_project) == []

    _adopt_the_contract(store)  # the store's first evidence-bearing entry
    store.update("US-TST-1-2", status="done", outcome="success", note="after")

    assert _flagged(tmp_project) == ["US-TST-1-2"]

    first = _first_evidence_timestamp(Store(tmp_project))
    assert first is not None
    fresh = Store(tmp_project)
    assert fresh.get_run_log("US-TST-1-1")[0].timestamp < first
    assert fresh.get_run_log("US-TST-1-2")[0].timestamp >= first


def test_a_run_stamped_done_still_counts_in_a_store_with_no_evidence(
    store, tmp_project
):
    """Limb 2 is unconditional — a new project is not given a free pass.

    Nothing in this store carries evidence, so no bare verdict counts; but an
    orchestrator that accepts a task under a run has agreed to the contract,
    and that acceptance is caught from the very first run.
    """
    store.update("US-TST-1-1", status="done", outcome="success", note="pre-contract")
    store.update("US-TST-1-2", status="done", run_id="orch-test-1")

    assert _first_evidence_timestamp(Store(tmp_project)) is None
    assert _flagged(tmp_project) == ["US-TST-1-2"]


def test_a_legacy_done_task_that_later_gets_a_verdict_is_counted(
    store, tmp_project
):
    """A run-log entry is the other half of the rule: something to attach to.

    The task's completion predates any run, but a verdict was written against
    it *after* this store had recorded evidence elsewhere — so evidence could
    have been recorded on that entry too, and the warning names something a
    person can still fix.
    """
    store.update("US-TST-1-1", status="done")
    assert _flagged(tmp_project) == []

    _adopt_the_contract(store)
    store.update("US-TST-1-1", outcome="success", note="checked it by hand")
    assert _flagged(tmp_project) == ["US-TST-1-1"]


def test_a_done_task_whose_entries_all_lack_evidence_is_flagged(store, tmp_project):
    """A note and an outcome say what happened; they do not prove it."""
    _adopt_the_contract(store)
    store.update("US-TST-1-1", status="in-progress", outcome="info", note="started")
    store.update("US-TST-1-1", status="done", outcome="success", note="finished it")

    entries = Store(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 2 and all(e.evidence is None for e in entries)

    assert _flagged(tmp_project) == ["US-TST-1-1"]


def test_both_kinds_land_in_one_warning_finding(store, tmp_project):
    """One aggregate finding, the shape of ``done-story-incomplete-tasks``."""
    _adopt_the_contract(store)
    store.update("US-TST-1-1", status="done", run_id="orch-test-1")  # no log at all
    store.update("US-TST-1-2", status="done", outcome="success", note="no evidence")

    findings = _findings(tmp_project)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["check"] == CHECK
    assert finding["severity"] == "warning"
    assert sorted(finding["items"]) == ["US-TST-1-1", "US-TST-1-2"]
    # The count travels in the message so DRIFT.md's one line is self-sufficient,
    # and the message states the rule that produced it (US-PM-43-6).
    assert "2 done task(s) that could have carried evidence" in finding["message"]
    assert "run_id" in finding["message"]


def test_empty_evidence_is_still_evidence(store, tmp_project):
    """Presence, never truthiness: ``Evidence()`` says "nothing to show"."""
    store.update(
        "US-TST-1-1", status="done", outcome="success", note="docs only",
        evidence=Evidence(),
    )
    entry = Store(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.evidence is not None
    assert not entry.evidence.files and not entry.evidence.tests
    assert not entry.evidence.dod_met and not entry.evidence.dod_unmet

    assert _findings(tmp_project) == []


def test_an_archived_done_task_is_not_flagged(store, tmp_project):
    """Archived work is abandoned history, not a completion anyone defends."""
    store.update("US-TST-1-1", status="done", run_id="orch-test-1")
    store.archive("US-TST-1-1")

    assert Store(tmp_project).get_task("US-TST-1-1")[0].archived is True
    assert _findings(tmp_project) == []


def test_tasks_that_are_not_done_are_not_flagged(store, tmp_project):
    """The check is about completions; open work has nothing to prove yet."""
    store.update("US-TST-1-1", status="todo")
    store.update("US-TST-1-2", status="in-progress", outcome="info", note="working")
    store.update("US-TST-1-3", status="review", outcome="partial", note="needs eyes")
    store.update("US-TST-1-4", status="blocked", outcome="blocked", note="stuck")

    assert _findings(tmp_project) == []


def test_a_project_with_evidenced_completions_stays_clean(store, tmp_project):
    """No offenders means no finding at all — not an empty-items finding."""
    for task_id in ("US-TST-1-1", "US-TST-1-2"):
        store.update(
            task_id, status="done", outcome="success", note="proved it",
            evidence=Evidence(files=["src/projectman/audit.py"]),
        )
    assert _findings(tmp_project) == []


# ═══ the finding reaches the audit report ═══════════════════════


def test_the_finding_is_wired_into_run_audit_and_drift_md(store, tmp_project):
    store.update("US-TST-1-1", status="done", run_id="orch-test-1")
    clear_all_caches()

    report = run_audit(tmp_project)
    assert "[WARN]" in report
    assert "1 done task(s) that could have carried evidence" in report

    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "1 done task(s) that could have carried evidence" in drift
    # Warning, not error: /pm-orchestrate halts a sprint on error-level
    # findings, and every legacy completion trips this check.
    assert "[ERROR] 1 done task" not in report


# ═══ §4 — the query side answers it for a single item ═══════════


def test_pm_run_log_has_evidence_false_returns_only_the_bare_entries(
    store, tmp_project
):
    store.update("US-TST-1-1", status="in-progress", outcome="info", note="bare one")
    store.update(
        "US-TST-1-1", status="review", outcome="partial", note="proved something",
        evidence=Evidence(files=["src/projectman/audit.py"]),
    )
    store.update("US-TST-1-1", status="done", outcome="success", note="bare two")

    is_error, body = _call_over_the_wire(
        "pm_run_log", {"id": "US-TST-1-1", "has_evidence": False}
    )
    assert not is_error
    entries = json.loads(body)
    assert [e["note"] for e in entries] == ["bare two", "bare one"]
    assert all(e.get("evidence") is None for e in entries)

    is_error, body = _call_over_the_wire(
        "pm_run_log", {"id": "US-TST-1-1", "has_evidence": True}
    )
    assert not is_error
    with_evidence = json.loads(body)
    assert [e["note"] for e in with_evidence] == ["proved something"]


# ═══ the finding is repairable ══════════════════════════════════


def test_the_finding_disappears_after_an_accept_carrying_evidence(
    store, tmp_project
):
    """pm_accept with evidence is the fix, and the audit proves it took.

    The repair needs one intermediate step that is not a deviation but the
    product's own rule: `pm_accept` on an already-done task is the expected
    negative `already_done` and writes nothing (`server.py` `_do_accept`,
    guard_done), precisely so a completion is never double-counted.  So the
    flagged task goes back through `pm_retry` — the verdict that says "this
    was not really finished" — and is then accepted *with* evidence.  That
    also proves the check reads the whole log: the earlier evidence-less
    entries survive, and one evidence-bearing entry among them clears it.
    """
    _adopt_the_contract(store)
    store.claim_task("US-TST-1-1", "claude")
    store.update("US-TST-1-1", status="done", outcome="success", note="no proof")
    assert _flagged(tmp_project) == ["US-TST-1-1"]

    is_error, body = _call_over_the_wire(
        "pm_accept",
        {
            "task_id": "US-TST-1-1",
            "note": "premature",
            "next_task": False,
            "evidence": SAMPLE_EVIDENCE,
        },
    )
    assert not is_error, body
    assert "already_done" in body, "guard_done must refuse a second completion"
    assert _flagged(tmp_project) == ["US-TST-1-1"], "and must have written nothing"

    is_error, body = _call_over_the_wire(
        "pm_retry", {"task_id": "US-TST-1-1", "note": "no evidence was recorded"}
    )
    assert not is_error, body

    is_error, body = _call_over_the_wire(
        "pm_accept",
        {
            "task_id": "US-TST-1-1",
            "note": "all DoD met; suite green",
            "next_task": False,
            "evidence": SAMPLE_EVIDENCE,
        },
    )
    assert not is_error, body

    fresh = Store(tmp_project)
    assert fresh.get_task("US-TST-1-1")[0].status.value == "done"
    assert len(fresh.get_run_log("US-TST-1-1", has_evidence=False)) == 2
    assert [e.evidence.files for e in fresh.get_run_log("US-TST-1-1", has_evidence=True)] == [
        SAMPLE_EVIDENCE["files"]
    ]
    assert _findings(tmp_project) == []


# ═══ §5 end-to-end — the finding reaches the pm_audit tool ══════


def _audit_over_the_wire(arguments: dict | None = None) -> tuple[bool, str]:
    """``pm_audit`` through the real tools/call handler, off a cold store."""
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()
    return _call_over_the_wire("pm_audit", arguments or {})


def test_pm_audit_over_the_wire_names_the_finding_and_writes_drift(
    store, tmp_project
):
    """Detection is only real if it survives the MCP boundary.

    ``run_audit`` is the check's caller; ``pm_audit`` is what an orchestrator
    actually invokes.  This asserts the whole path — tool call, rendered
    response, and the DRIFT.md that pm_audit always writes.
    """
    _adopt_the_contract(store)
    store.update("US-TST-1-1", status="done", outcome="success", note="no proof")

    is_error, report = _audit_over_the_wire()
    assert not is_error, report

    line = "[WARN] 1 done task(s) that could have carried evidence"
    assert report.count(line) == 1, report
    # Exactly one done-without-evidence warning, and it is not an error.
    assert "[ERROR] 1 done task(s)" not in report

    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert drift.count(line) == 1, drift


def test_pm_audit_reports_nothing_when_every_completion_is_evidenced(
    store, tmp_project
):
    """The goal state the sprint is aiming at is reachable, not theoretical."""
    for task_id in ("US-TST-1-1", "US-TST-1-2"):
        store.update(
            task_id, status="done", outcome="success", note="proved it",
            evidence=Evidence(files=["src/projectman/audit.py"]),
        )

    is_error, report = _audit_over_the_wire()
    assert not is_error, report
    assert "could have carried evidence" not in report

    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "could have carried evidence" not in drift


def test_items_names_exactly_the_offenders_in_a_mixed_project(store, tmp_project):
    """Every state the definition distinguishes, side by side in one project."""
    store.update(                                     # done + evidence: clean
        "US-TST-1-1", status="done", outcome="success", note="proved it",
        evidence=Evidence(files=["src/projectman/audit.py"]),
    )
    store.update(                                     # done, log but no evidence
        # ...and written after US-TST-1-1's evidence, so it could have carried
        # some: the US-PM-43-7 line is this store's own first evidence.
        "US-TST-1-2", status="done", outcome="success", note="no proof"
    )
    store.update(                                     # done under a run, no log
        "US-TST-1-3", status="done", run_id="orch-test-1"
    )
    store.update(                                     # still open: nothing to prove
        "US-TST-1-4", status="in-progress", outcome="info", note="working"
    )
    store.update(                                     # done, no log, then archived
        "US-TST-1-5", status="done", run_id="orch-test-1"
    )
    store.archive("US-TST-1-5")
    store.update("US-TST-1-6", status="done")         # legacy: no log, no run_id

    findings = _findings(tmp_project)
    assert len(findings) == 1
    assert sorted(findings[0]["items"]) == ["US-TST-1-2", "US-TST-1-3"]
    assert "2 done task(s) that could have carried evidence" in findings[0]["message"]
