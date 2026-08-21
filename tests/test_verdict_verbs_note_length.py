"""US-PM-9 acceptance: median note length drops well below the cap.

`tests/test_run_log_evidence.py` proves the mechanism one field at a time --
evidence is stored, the note is untouched, an over-long note alongside evidence
is flagged.  This module states the *criterion* the way it is worded: as a
median over every verdict path the rewritten `pm-orchestrate` skill instructs,
measured after the fact from what is on disk.

The load-bearing claim is not that the notes got shorter.  Anything gets shorter
if you delete half of it.  It is that **the information did not move out of the
record, only out of the prose** -- so every file path, test command and DoD line
that the old-style note would have carried is asserted present in the stored
`evidence`, and the old-style note is measured beside the new one to show the
size the criterion is being met against.

Two computations, mirroring `tests/test_verdict_verbs_completion_logging.py`:

1. **From disk** -- the run-log entries these calls wrote, read back through
   `Store.get_run_log`, with the median taken over `len(entry.note)`.
2. **From the recorded calls**, through
   :func:`tools.usage_telemetry.report.note_lengths` -- the same arithmetic the
   corpus metric runs over real transcripts, so the number the telemetry
   pipeline will publish is the number this test just measured.
"""

import pytest
import yaml

from projectman.store import NOTE_SUMMARY_RECOMMENDED, Store
from tools.usage_telemetry.baseline import NOTE_LENGTH_GATE_MEDIAN, NOTE_LENGTH_GATE_P90
from tools.usage_telemetry.extract import ToolCall, ToolResult
from tools.usage_telemetry.report import Distribution, note_lengths

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: One row per verdict verb, each carrying the skill's recommended shape: a
#: one-line note of at most 200 characters plus the three structured lists.
#:
#: The lists are sized like a real orchestrator verdict, not like a minimal
#: fixture -- the measured pre-fix corpus had a median note of 925 characters
#: precisely because a verdict has this many facts to record, and a toy fixture
#: would make the criterion trivially true.
VERDICTS = [
    (
        "pm_accept",
        "all DoD met; 47 tests pass",
        {
            "files": [
                "src/projectman/store.py",
                "src/projectman/models.py",
                "src/projectman/server.py",
                "src/projectman/audit.py",
                "src/projectman/templates/skill_pm_orchestrate.md.j2",
                "tests/test_store.py",
                "tests/test_run_log_evidence.py",
                "tests/test_skill_evidence.py",
                "docs/reference/evidence-contract.md",
            ],
            "tests": [
                {
                    "command": "uv run pytest tests/test_run_log_evidence.py -q",
                    "passed": True,
                    "summary": "47 passed in 3.10s",
                },
                {
                    "command": "uv run pytest tests/test_store.py -q",
                    "passed": True,
                    "summary": "112 passed in 6.44s",
                },
            ],
            "dod_met": [
                "evidence is stored on the run-log entry",
                "old lines with no evidence key still parse",
                "the note is unchanged and still required",
                "clamping never rejects the status write",
            ],
            "dod_unmet": [],
        },
    ),
    (
        "pm_review",
        "endpoint works; error paths untested",
        {
            "files": [
                "src/projectman/server.py",
                "src/projectman/web/api.py",
                "src/projectman/web/routes.py",
                "tests/test_server_verbs.py",
                "tests/test_web_api.py",
            ],
            "tests": [
                {
                    "command": "uv run pytest tests/test_server_verbs.py -q",
                    "passed": True,
                    "summary": "12 passed, 2 skipped in 1.90s",
                },
                {
                    "command": "uv run pytest tests/test_web_api.py -q",
                    "passed": True,
                    "summary": "31 passed in 2.20s",
                },
            ],
            "dod_met": [
                "the happy path is covered end to end",
                "the response shape matches the contract",
            ],
            "dod_unmet": [
                "error paths are untested",
                "no timeout handling on the upstream call",
            ],
        },
    ),
    (
        "pm_retry",
        "tests still red -- the fixture never loads",
        {
            "files": [
                "tests/conftest.py",
                "tests/test_audit.py",
                "src/projectman/audit.py",
            ],
            "tests": [
                {
                    "command": "uv run pytest tests/test_audit.py -q",
                    "passed": False,
                    "summary": "3 failed, 1 error in 2.70s",
                },
                {
                    "command": "uv run pytest tests/test_audit_findings.py -q",
                    "passed": False,
                    "summary": "1 failed, 18 passed in 1.40s",
                },
            ],
            "dod_met": [],
            "dod_unmet": [
                "the audit check is green",
                "the shared fixture loads without an error",
                "the finding is aggregated rather than one per task",
            ],
        },
    ),
    (
        "pm_park",
        "needs the staging DB credentials",
        {
            "files": [],
            "tests": [],
            "dod_met": ["migration written"],
            "dod_unmet": ["migration verified against staging"],
        },
    ),
]


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _fresh(tmp_project) -> Store:
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _verb(name):
    import projectman.server as server

    return getattr(server, name)


def _evidence_strings(evidence: dict) -> list[str]:
    """Every fact in ``evidence`` -- the facts the old note had to carry."""
    facts = list(evidence.get("files", []))
    for test in evidence.get("tests", []):
        facts.append(test["command"])
        if test.get("summary"):
            facts.append(test["summary"])
    facts += list(evidence.get("dod_met", []))
    facts += list(evidence.get("dod_unmet", []))
    return facts


def _legacy_note(summary: str, evidence: dict) -> str:
    """The prose note this verdict carried *before* US-PM-9 -- the same facts.

    This is the shape `pm-orchestrate` steps 17-19 used to produce: the three
    lists flattened into one sentence, which is why note lengths clustered at
    the cap. It is the control the new note is measured against.
    """
    parts = [summary]
    if evidence.get("files"):
        parts.append("files changed: " + ", ".join(evidence["files"]))
    for test in evidence.get("tests", []):
        verdict = "passed" if test["passed"] else "FAILED"
        parts.append(f"ran {test['command']} -- {verdict} ({test.get('summary')})")
    if evidence.get("dod_met"):
        parts.append("DoD met: " + ", ".join(evidence["dod_met"]))
    if evidence.get("dod_unmet"):
        parts.append("DoD outstanding: " + ", ".join(evidence["dod_unmet"]))
    return "; ".join(parts)


def _as_tool_call(seq: int, verb: str, arguments: dict) -> ToolCall:
    """The transcript record the harness would have written for this call."""
    call = ToolCall(
        tool_use_id=f"note-length-{seq}",
        name=f"mcp__projectman__{verb}",
        input=dict(arguments),
        timestamp="2026-08-21T00:00:00Z",
        session="note-length-sweep",
        session_id="note-length-sweep",
        project="test-project",
        source_file="/tmp/note-length-sweep.jsonl",
        line_no=seq + 1,
        seq=seq,
    )
    call.result = ToolResult(tool_use_id=call.tool_use_id, is_error=False, text="ok")
    return call


def _drive_every_verdict(tmp_project):
    """Run each verdict on its own task; return the recorded calls and task ids."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, len(VERDICTS) + 1):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)

    recorded, task_ids = [], []
    for seq, (verb, note, evidence) in enumerate(VERDICTS):
        task_id = f"US-TST-1-{seq + 1}"
        _fresh(tmp_project).claim_task(task_id, "claude")
        kwargs = {"note": note, "evidence": evidence}
        if verb == "pm_accept":
            # Not part of the criterion, and claiming the next task would
            # collide with the next row's own claim.
            kwargs["next_task"] = False
        _verb(verb)(task_id, **kwargs)
        recorded.append(_as_tool_call(seq, verb, {"task_id": task_id, **kwargs}))
        task_ids.append(task_id)
    return recorded, task_ids


def _stored_entries(tmp_project, task_ids):
    store = _fresh(tmp_project)
    entries = []
    for task_id in task_ids:
        log = store.get_run_log(task_id)
        assert len(log) == 1, (task_id, log)
        entries.append(log[0])
    return entries


# -- the criterion, measured from disk ---------------------------------------


def test_the_median_stored_note_is_well_below_the_cap(tmp_project):
    """The AC, literally: median note length over every verdict path."""
    _, task_ids = _drive_every_verdict(tmp_project)
    entries = _stored_entries(tmp_project, task_ids)

    lengths = Distribution.of(len(entry.note) for entry in entries)
    assert lengths.count == len(VERDICTS)
    assert lengths.median <= NOTE_SUMMARY_RECOMMENDED
    assert lengths.median <= NOTE_LENGTH_GATE_MEDIAN
    assert lengths.p90 <= NOTE_LENGTH_GATE_P90
    # "Well below the cap" is the claim; the cap is 4096.
    assert lengths.maximum < 4096 // 4


def test_no_single_note_exceeds_the_one_line_recommendation(tmp_project):
    _, task_ids = _drive_every_verdict(tmp_project)
    for entry in _stored_entries(tmp_project, task_ids):
        assert len(entry.note) <= NOTE_SUMMARY_RECOMMENDED, entry.note


def test_every_fact_the_old_note_carried_is_present_in_the_evidence(tmp_project):
    """The information did not get shorter -- only the note did.

    Each fact the pre-US-PM-9 prose note would have flattened is asserted
    present in a *structured field* of the stored entry, so shrinking the note
    cannot be mistaken for dropping the record.
    """
    _, task_ids = _drive_every_verdict(tmp_project)
    entries = _stored_entries(tmp_project, task_ids)

    for (verb, _note, evidence), entry in zip(VERDICTS, entries):
        assert entry.evidence is not None, verb
        stored = _evidence_strings(entry.evidence.model_dump())
        for fact in _evidence_strings(evidence):
            assert fact in stored, (verb, fact, stored)
        # The lists round-trip whole, not merely as a superset.
        assert entry.evidence.files == evidence["files"], verb
        assert entry.evidence.dod_met == evidence["dod_met"], verb
        assert entry.evidence.dod_unmet == evidence["dod_unmet"], verb
        assert [t.command for t in entry.evidence.tests] == [
            t["command"] for t in evidence["tests"]
        ], verb
        assert [t.passed for t in entry.evidence.tests] == [
            t["passed"] for t in evidence["tests"]
        ], verb


def test_the_facts_are_no_longer_flattened_into_the_note(tmp_project):
    """No file path or test command survives inside the prose."""
    _, task_ids = _drive_every_verdict(tmp_project)
    entries = _stored_entries(tmp_project, task_ids)

    for (verb, _note, evidence), entry in zip(VERDICTS, entries):
        for path in evidence["files"]:
            assert path not in entry.note, (verb, path)
        for test in evidence["tests"]:
            assert test["command"] not in entry.note, (verb, test["command"])


def test_the_same_facts_as_prose_would_have_blown_past_the_recommendation(tmp_project):
    """The control: without the move, these very notes are long again.

    If the legacy shape were also short, the criterion would be measuring the
    fixtures rather than the fix.
    """
    legacy = Distribution.of(
        len(_legacy_note(note, evidence)) for _verb_, note, evidence in VERDICTS
    )
    _, task_ids = _drive_every_verdict(tmp_project)
    actual = Distribution.of(
        len(entry.note) for entry in _stored_entries(tmp_project, task_ids)
    )

    assert legacy.median > NOTE_SUMMARY_RECOMMENDED
    assert legacy.median > actual.median * 2


# -- the same number, through the telemetry metric ----------------------------


def test_the_telemetry_metric_scores_the_same_sweep_below_the_gate(tmp_project):
    """The bridge: the corpus metric, run over the calls this sweep made."""
    recorded, _ = _drive_every_verdict(tmp_project)

    dist = note_lengths(recorded)
    assert dist.count == len(VERDICTS)
    assert dist.median <= NOTE_LENGTH_GATE_MEDIAN
    assert dist.p90 <= NOTE_LENGTH_GATE_P90


def test_the_legacy_prose_shape_would_fail_the_same_gate(tmp_project):
    """Control for the metric: the pre-fix corpus shape does not pass it."""
    legacy_calls = [
        _as_tool_call(
            seq,
            verb,
            {"task_id": f"US-TST-1-{seq + 1}", "note": _legacy_note(note, evidence)},
        )
        for seq, (verb, note, evidence) in enumerate(VERDICTS)
    ]
    dist = note_lengths(legacy_calls)
    assert dist.median > NOTE_LENGTH_GATE_MEDIAN


# -- the advisory that keeps the median down ---------------------------------


def test_a_long_note_alongside_evidence_is_flagged_note_long(tmp_project):
    """`note_long` is the feedback loop; without it the median drifts back up."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    store.create_task("US-TST-1", "Task 1", READY_BODY, points=1)
    _fresh(tmp_project).claim_task("US-TST-1-1", "claude")

    long_note = "x" * 900
    body = yaml.safe_load(
        _verb("pm_review")("US-TST-1-1", note=long_note, evidence=VERDICTS[1][2])
    )

    assert body["note_long"] is True
    assert body["note_length"] == 900
    assert body["note_recommended"] == NOTE_SUMMARY_RECOMMENDED == 200
    # Advisory only: the note is stored whole and the status change still landed.
    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.note == long_note
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "review"
