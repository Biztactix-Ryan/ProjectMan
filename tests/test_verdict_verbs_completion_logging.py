"""US-PM-8 acceptance: the share of completions with no run-log entry is zero.

`tests/test_verdict_verbs.py::test_no_verdict_can_reach_disk_without_a_run_log_entry`
proves the property one verb at a time.  This module states the acceptance
criterion the way the criterion is worded -- as a *share over every completion
path the orchestrator skill now instructs*, measured after the fact from what
is on disk:

* `pm_accept`             -- the Accept verdict;
* `pm_done_next`          -- with a note, with no note, and with a blank note,
                             the three shapes that used to produce the silent
                             gap (the sentinel `DONE_NEXT_NO_NOTE` closes the
                             last two);
* `pm_retry` / `pm_park` / `pm_review` -- the other three verdicts.

Two computations, deliberately:

1. **From disk** -- every task these calls touched is re-read from the store
   and the share lacking an entry is counted directly.  This owes nothing to
   the telemetry package: if the server stopped writing entries, it fails.
2. **From the recorded calls**, through
   :func:`tools.usage_telemetry.report.completion_logging` -- the same
   arithmetic the corpus metric will run over real transcripts.  Tying the two
   halves together is the point: the number the telemetry pipeline will publish
   is the number this test just measured on the new code.
"""

import pathlib

import pytest

from projectman.store import Store
from tools.usage_telemetry.extract import ToolCall, ToolResult
from tools.usage_telemetry.report import completion_logging

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: Every completion path `pm-orchestrate` now instructs, as
#: ``(verb, extra kwargs)``.  The three `pm_done_next` rows are the note
#: shapes, not three different verbs.
COMPLETION_PATHS = [
    ("pm_accept", {"note": "work accepted -- tests green"}),
    ("pm_done_next", {"note": "finished the parser"}),
    ("pm_done_next", {}),
    ("pm_done_next", {"note": "   "}),
    ("pm_retry", {"note": "tests still red -- the fixture never loads"}),
    ("pm_park", {"note": "needs the staging DB credentials"}),
    ("pm_review", {"note": "endpoint works; error paths untested"}),
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


def _as_tool_call(seq: int, verb: str, arguments: dict) -> ToolCall:
    """The transcript record the harness would have written for this call."""
    call = ToolCall(
        tool_use_id=f"verdict-{seq}",
        name=f"mcp__projectman__{verb}",
        input=dict(arguments),
        timestamp="2026-08-21T00:00:00Z",
        session="verdict-sweep",
        session_id="verdict-sweep",
        project="test-project",
        source_file="/tmp/verdict-sweep.jsonl",
        line_no=seq + 1,
        seq=seq,
    )
    call.result = ToolResult(tool_use_id=call.tool_use_id, is_error=False, text="ok")
    return call


def _drive_every_completion_path(tmp_project):
    """Run each path on its own task; return the recorded calls and task ids."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, len(COMPLETION_PATHS) + 1):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)

    recorded, task_ids = [], []
    for seq, (verb, kwargs) in enumerate(COMPLETION_PATHS):
        task_id = f"US-TST-1-{seq + 1}"
        # Each verb is a verdict on a task the caller holds, so claim first --
        # exactly the beat the skill instructs.
        _fresh(tmp_project).claim_task(task_id, "claude")
        arguments = {"task_id": task_id, **kwargs}
        _verb(verb)(task_id, **kwargs)
        recorded.append(_as_tool_call(seq, verb, arguments))
        task_ids.append(task_id)
    return recorded, task_ids


def test_no_completion_path_leaves_a_task_without_a_run_log_entry(tmp_project):
    """Measured from disk: 0 of 7 completions lack an entry. The AC, literally."""
    _, task_ids = _drive_every_completion_path(tmp_project)

    store = _fresh(tmp_project)
    missing = [tid for tid in task_ids if not store.get_run_log(tid)]

    share = len(missing) / len(task_ids)
    assert share == 0.0, f"{len(missing)} of {len(task_ids)} lack an entry: {missing}"
    for tid in task_ids:
        entries = store.get_run_log(tid)
        assert len(entries) == 1, (tid, entries)
        assert entries[0].outcome, tid
        # Blank and absent notes are filled by the sentinel, never left empty.
        assert entries[0].note and entries[0].note.strip(), tid


def test_the_telemetry_metric_scores_the_same_sweep_at_zero(tmp_project):
    """The corpus metric, run over the calls this sweep actually made.

    This is the bridge between the two halves of the criterion: part A's
    ``completion_logging`` is the definition the live corpus will be measured
    with, and on the post-fix code path it reports 0.0.
    """
    recorded, _ = _drive_every_completion_path(tmp_project)

    summary = completion_logging(recorded)
    # `pm_retry`/`pm_park`/`pm_review` are verdicts but not completions -- they
    # do not mark work done -- so the denominator is accept + the three
    # `pm_done_next` shapes.
    assert summary.completions == 4
    assert summary.without_run_log == 0
    assert summary.without_run_log_rate == 0.0


def test_a_bare_done_update_is_the_gap_this_sweep_no_longer_contains(tmp_project):
    """Control: the compat path still scores as a gap, so the 0.0 means something.

    ``pm_update(status="done")`` with neither note nor outcome writes no entry
    (contract section 4 keeps it working).  If this call scored 0 too, the
    metric would be blind and the assertions above would be vacuous.
    """
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    store.create_task("US-TST-1", "Task 1", READY_BODY, points=1)
    _fresh(tmp_project).claim_task("US-TST-1-1", "claude")

    from projectman.server import pm_update

    pm_update("US-TST-1-1", status="done")

    assert _fresh(tmp_project).get_run_log("US-TST-1-1") == []
    bare = _as_tool_call(0, "pm_update", {"id": "US-TST-1-1", "status": "done"})
    summary = completion_logging([bare])
    assert summary.completions == 1
    assert summary.without_run_log_rate == 1.0


def test_the_contract_names_the_paths_this_sweep_covers():
    """Guard against the skill gaining a fifth verdict this file never runs."""
    contract = (
        pathlib.Path(__file__).resolve().parents[1]
        / "docs"
        / "reference"
        / "verdict-verbs-contract.md"
    )
    text = contract.read_text(encoding="utf-8")
    for verb in {verb for verb, _ in COMPLETION_PATHS}:
        assert verb in text, verb
