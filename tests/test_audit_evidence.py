"""Completions carrying no evidence are detectable (US-PM-9-8).

`docs/reference/evidence-contract.md` §5 is the binding design.  Its rule:

    A completion without evidence is a task with `status == done` whose run
    log contains no entry whose `evidence` is not `None`.  A task with no run
    log at all qualifies.

Study C measured 163 of 1,266 done writes carrying no note or outcome at all —
today that is invisible.  Two paths make it visible, and both are asserted
here: the audit finding `done-without-evidence` (§5) and the query
`pm_run_log(id, has_evidence=False)` (§4, delivered by US-PM-9-7).

The properties that matter are exactly the ones a careless implementation
gets wrong:

* **presence, never truthiness** — `Evidence()` with four empty lists is the
  genuinely non-code task saying "nothing to show", and counts as evidence;
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

from projectman.audit import check_completions_without_evidence, run_audit
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


def test_a_done_task_with_no_run_log_at_all_is_flagged(store, tmp_project):
    """The 13% of completions with no run log — the measured invisible case."""
    store.update("US-TST-1-1", status="done")
    assert not (tmp_project / ".project" / "logs" / "US-TST-1-1.jsonl").exists()

    assert _flagged(tmp_project) == ["US-TST-1-1"]


def test_a_done_task_whose_entries_all_lack_evidence_is_flagged(store, tmp_project):
    """A note and an outcome say what happened; they do not prove it."""
    store.update("US-TST-1-1", status="in-progress", outcome="info", note="started")
    store.update("US-TST-1-1", status="done", outcome="success", note="finished it")

    entries = Store(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 2 and all(e.evidence is None for e in entries)

    assert _flagged(tmp_project) == ["US-TST-1-1"]


def test_both_kinds_land_in_one_warning_finding(store, tmp_project):
    """One aggregate finding, the shape of ``done-story-incomplete-tasks``."""
    store.update("US-TST-1-1", status="done")  # no log at all
    store.update("US-TST-1-2", status="done", outcome="success", note="no evidence")

    findings = _findings(tmp_project)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["check"] == CHECK
    assert finding["severity"] == "warning"
    assert sorted(finding["items"]) == ["US-TST-1-1", "US-TST-1-2"]
    # The count travels in the message so DRIFT.md's one line is self-sufficient.
    assert "2 done task(s)" in finding["message"]


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
    store.update("US-TST-1-1", status="done")
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
    store.update("US-TST-1-1", status="done")
    clear_all_caches()

    report = run_audit(tmp_project)
    assert "[WARN]" in report
    assert "1 done task(s) have no structured evidence" in report

    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "no structured evidence" in drift
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
    store.update("US-TST-1-1", status="done", outcome="success", note="no proof")

    is_error, report = _audit_over_the_wire()
    assert not is_error, report

    line = "[WARN] 1 done task(s) have no structured evidence"
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
    assert "no structured evidence" not in report

    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "no structured evidence" not in drift


def test_items_names_exactly_the_offenders_in_a_mixed_project(store, tmp_project):
    """Every state the definition distinguishes, side by side in one project."""
    store.update(                                     # done + evidence: clean
        "US-TST-1-1", status="done", outcome="success", note="proved it",
        evidence=Evidence(files=["src/projectman/audit.py"]),
    )
    store.update(                                     # done, log but no evidence
        "US-TST-1-2", status="done", outcome="success", note="no proof"
    )
    store.update("US-TST-1-3", status="done")         # done, no log at all
    store.update(                                     # still open: nothing to prove
        "US-TST-1-4", status="in-progress", outcome="info", note="working"
    )
    store.update("US-TST-1-5", status="done")         # done, no log, then archived
    store.archive("US-TST-1-5")

    findings = _findings(tmp_project)
    assert len(findings) == 1
    assert sorted(findings[0]["items"]) == ["US-TST-1-2", "US-TST-1-3"]
    assert "2 done task(s)" in findings[0]["message"]
