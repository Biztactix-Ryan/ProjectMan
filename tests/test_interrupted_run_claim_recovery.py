"""An interrupted run can identify which claims it owned (US-PM-14-1).

The story's other test modules pin the pieces: `test_claim_ownership.py` that
a claim records `claimed_by_run`/`claimed_at`, `test_skill_activity_report.py`
that `pm_activity(run_id=…)` filters and pages, `test_skill_resume_path.py`
that the skill's documented resume procedure runs against a real store.  This
module is the acceptance criterion itself, and it closes three gaps those
leave:

* the **three-way sort**.  A dead run's claims are not "open or done" — a run
  that claimed three tasks, accepted one, released one and died holding the
  third must come back as exactly `{held}` owned-and-open, `{accepted}` done,
  `{released}` back in the pool.  Getting this wrong in either direction is a
  real failure: re-adopting the released one steals work a later run may hold,
  and missing the held one leaves a task claimed forever.
* the **cross-check**.  The same answer has to fall out of `pm_active`'s
  `claimed_by_run` alone, because that is the cheap path a resuming run takes
  when it has not yet paged the log.  Two sources that can disagree are worse
  than one.
* **legacy claims**.  A task claimed before these fields existed has an
  assignee and nothing else.  It must come back *unattributed* — belonging to
  no run, including the current process's — never folded into whichever run
  happens to be asking.  Mis-attributing it would have a recovery loop adopt
  and re-run work an older writer is still doing.

Everything here is driven through ``mcp.call_tool``, the path a real MCP
client takes, so argument coercion and the tool bodies are both under test
rather than the Python functions alone.
"""

import json

import anyio
import pytest
import yaml

from projectman.store import PROCESS_RUN_ID, Store, clear_all_caches

RUN_A = "orch-2026-08-22-dead"
RUN_B = "orch-2026-08-22-live"
RUN_C = "orch-2026-08-22-other"

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Server tools resolve the project from the cwd."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    _store_cache.clear()
    clear_all_caches()


@pytest.fixture
def project(tmp_project):
    """An active story with six ready tasks, created below the wire."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, 7):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    clear_all_caches()
    return store


def _wire(tool_name, **arguments):
    """Call a tool the way a client does — through ``mcp.call_tool``."""
    from projectman.server import mcp as mcp_server

    result = anyio.run(mcp_server.call_tool, tool_name, arguments)
    # mcp<2 returns (content_blocks, structured); older shapes return the
    # blocks alone.  Either way the tool's string is the first block's text.
    blocks = result[0] if isinstance(result, tuple) else result
    if isinstance(blocks, list) and blocks and hasattr(blocks[0], "text"):
        return blocks[0].text
    return blocks


def _yaml(tool_name, **arguments):
    return yaml.safe_load(_wire(tool_name, **arguments))


def _slice(run_id, limit=200):
    """One run's whole activity slice, paged to exhaustion."""
    entries, offset = [], 0
    while True:
        page = _yaml("pm_activity", run_id=run_id, limit=limit, offset=offset)
        entries.extend(page["entries"])
        if not page["has_more"]:
            return entries, page["total"]
        offset += len(page["entries"])


def _claimed_in(entries):
    """Task ids this slice records a claim of (`status: todo → in-progress`)."""
    return sorted(
        {
            tid
            for e in entries
            if "status: todo → in-progress" in e
            for tid in [e.split()[3]]
        }
    )


def _state(task_id):
    return _yaml("pm_get", id=task_id, fields="status,assignee,claimed_by_run")


# ═══ (a) a run's slice is exactly its own claims ════════════════


def test_interleaved_runs_never_appear_in_each_others_slice(project):
    """Two runs touching the same tasks stay separable by run id alone."""
    _wire("pm_grab", task_id="US-TST-1-1", run_id=RUN_A)
    _wire("pm_grab", task_id="US-TST-1-2", run_id=RUN_B)
    _wire("pm_grab", task_id="US-TST-1-3", run_id=RUN_A)
    # A releases 1; B takes the very same task — the interleave that a
    # per-task or per-actor filter would smear together.
    _wire("pm_release", task_id="US-TST-1-1", run_id=RUN_A, note="unwinding")
    _wire("pm_grab", task_id="US-TST-1-1", run_id=RUN_B)

    a_entries, a_total = _slice(RUN_A)
    b_entries, b_total = _slice(RUN_B)

    assert all(f"run {RUN_A}" in e for e in a_entries), a_entries
    assert all(f"run {RUN_B}" in e for e in b_entries), b_entries
    assert a_total == len(a_entries) and b_total == len(b_entries)

    # Every claim A made is in A's slice; the claim B made on the same task
    # is not, even though it names the same task id.
    assert _claimed_in(a_entries) == ["US-TST-1-1", "US-TST-1-3"]
    assert _claimed_in(b_entries) == ["US-TST-1-1", "US-TST-1-2"]
    assert not any(f"run {RUN_B}" in e for e in a_entries)


def test_a_record_longer_than_one_page_is_complete_only_after_paging(project):
    """`has_more` is load-bearing: a one-page read would lose claims."""
    for n in range(1, 6):
        _wire("pm_grab", task_id=f"US-TST-1-{n}", run_id=RUN_A)

    first = _yaml("pm_activity", run_id=RUN_A, limit=2, offset=0)
    assert first["has_more"] is True
    assert len(_claimed_in(first["entries"])) < 5, (
        "the first page already held every claim — this is not a paging test"
    )

    entries, total = _slice(RUN_A, limit=2)
    assert total == len(entries) == first["total"]
    assert _claimed_in(entries) == [f"US-TST-1-{n}" for n in range(1, 6)]


# ═══ (b) owned-and-open vs done vs released ═════════════════════


@pytest.fixture
def dead_run(project):
    """Run A claimed T1/T2/T3, accepted T1, released T2, died holding T3."""
    for n in (1, 2, 3):
        _wire("pm_grab", task_id=f"US-TST-1-{n}", run_id=RUN_A)
    _wire(
        "pm_accept",
        task_id="US-TST-1-1",
        note="all DoD met",
        next_task=False,
        run_id=RUN_A,
    )
    _wire("pm_release", task_id="US-TST-1-2", run_id=RUN_A, note="worker stopped")
    return project


def _sort_from_the_log():
    """The recovery procedure: run slice + current task state → three sets."""
    entries, _ = _slice(RUN_A)
    touched = _claimed_in(entries)
    held, done, released = [], [], []
    for tid in touched:
        s = _state(tid)
        if s["status"] == "done":
            done.append(tid)
        elif s["status"] == "in-progress" and s.get("claimed_by_run") == RUN_A:
            held.append(tid)
        else:
            released.append(tid)
    return held, done, released


def test_the_dead_runs_claims_sort_three_ways(dead_run):
    held, done, released = _sort_from_the_log()
    assert held == ["US-TST-1-3"], f"held={held}"
    assert done == ["US-TST-1-1"], f"done={done}"
    assert released == ["US-TST-1-2"], f"released={released}"


def test_the_released_task_is_back_in_the_pool_and_unowned(dead_run):
    """Released is not merely 'not held' — the claim is gone entirely."""
    s = _state("US-TST-1-2")
    assert s["status"] == "todo"
    assert not s.get("assignee")
    assert s.get("claimed_by_run") is None


def test_the_accepted_task_keeps_its_worker_but_drops_its_claim(dead_run):
    """Done work is attributable, but a finished claim can never go stale."""
    s = _state("US-TST-1-1")
    assert s["status"] == "done"
    assert s["assignee"] == "claude"
    assert s.get("claimed_by_run") is None


def test_a_later_run_taking_the_released_task_does_not_change_the_sort(dead_run):
    """Run C picks up what A released; A's answer is unchanged."""
    _wire("pm_grab", task_id="US-TST-1-2", run_id=RUN_C)

    held, done, released = _sort_from_the_log()
    assert held == ["US-TST-1-3"], f"held={held}"
    assert done == ["US-TST-1-1"], f"done={done}"
    assert released == ["US-TST-1-2"], (
        "a task A released and C now holds must never come back as A's — "
        f"released={released}"
    )


# ═══ (c) pm_active alone agrees ═════════════════════════════════


def _owned_from_pm_active(run_id):
    active = _yaml("pm_active")
    return sorted(
        t["id"]
        for t in active["active_tasks"]
        if t.get("claimed_by_run") == run_id
    )


def test_pm_active_alone_names_the_same_owned_claims(dead_run):
    held, _, _ = _sort_from_the_log()
    assert _owned_from_pm_active(RUN_A) == held == ["US-TST-1-3"]


def test_the_two_sources_still_agree_once_a_third_run_is_in_flight(dead_run):
    """Cheap path and log path must not diverge under concurrency."""
    _wire("pm_grab", task_id="US-TST-1-2", run_id=RUN_C)
    _wire("pm_grab", task_id="US-TST-1-4", run_id=RUN_C)

    held, _, _ = _sort_from_the_log()
    assert _owned_from_pm_active(RUN_A) == held == ["US-TST-1-3"]
    assert _owned_from_pm_active(RUN_C) == ["US-TST-1-2", "US-TST-1-4"]
    assert _owned_from_pm_active(RUN_B) == []


# ═══ (d) no claim is ever unattributed ══════════════════════════


def test_a_claim_made_without_a_run_id_carries_the_process_default(project):
    """Omitting `run_id` at the wire still produces an owner."""
    grabbed = _yaml("pm_grab", task_id="US-TST-1-1")["grabbed"]["task"]
    assert grabbed["claimed_by_run"] == PROCESS_RUN_ID
    assert _state("US-TST-1-1")["claimed_by_run"] == PROCESS_RUN_ID
    assert _owned_from_pm_active(PROCESS_RUN_ID) == ["US-TST-1-1"]
    # ...and the log agrees, so the default is recoverable, not just stored.
    entries, _ = _slice(PROCESS_RUN_ID)
    assert _claimed_in(entries) == ["US-TST-1-1"]


# ═══ (e) legacy claims are unattributed, not mis-attributed ═════


@pytest.fixture
def legacy_claim(project, tmp_project):
    """The literal on-disk shape from before claim metadata existed."""
    (tmp_project / ".project" / "tasks" / "US-TST-1-6.md").write_text(
        "---\n"
        "id: US-TST-1-6\n"
        "story_id: US-TST-1\n"
        "title: Legacy task\n"
        "status: in-progress\n"
        "points: 1\n"
        "assignee: claude\n"
        "tags: []\n"
        "depends_on: []\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n" + READY_BODY
    )
    clear_all_caches()
    from projectman.server import _store_cache

    _store_cache.clear()
    return project


def test_a_legacy_claim_belongs_to_no_run_at_all(legacy_claim):
    """It is in-progress and assigned, and owned by nobody."""
    s = _state("US-TST-1-6")
    assert s["status"] == "in-progress"
    assert s["assignee"] == "claude"
    assert s.get("claimed_by_run") is None

    active = _yaml("pm_active")
    entry = next(t for t in active["active_tasks"] if t["id"] == "US-TST-1-6")
    assert entry.get("claimed_by_run") is None, entry
    assert entry.get("stale") is not True, (
        "an unknown-age claim must never be reported stale — a recovery loop "
        "would steal live work from an older writer"
    )


def test_a_legacy_claim_is_not_folded_into_the_asking_run(legacy_claim):
    """No run id — not the process default, not a live run — claims it."""
    _wire("pm_grab", task_id="US-TST-1-1", run_id=RUN_A)

    for run_id in (RUN_A, RUN_B, PROCESS_RUN_ID):
        assert "US-TST-1-6" not in _owned_from_pm_active(run_id)
        entries, _ = _slice(run_id)
        assert not any("US-TST-1-6" in e for e in entries), (run_id, entries)


def test_a_legacy_claim_is_reported_by_the_procedure_as_unattributed(legacy_claim):
    """The resume sort must surface it as needing a human, not adopt it."""
    _wire("pm_grab", task_id="US-TST-1-1", run_id=RUN_A)

    held, _, _ = _sort_from_the_log()
    assert held == ["US-TST-1-1"], held

    unattributed = sorted(
        t["id"]
        for t in _yaml("pm_active")["active_tasks"]
        if not t.get("claimed_by_run")
    )
    assert unattributed == ["US-TST-1-6"], unattributed


def test_the_legacy_claim_is_still_in_the_log_unfiltered(legacy_claim, tmp_project):
    """Absence from every run slice is a filter, not a lost write."""
    log = tmp_project / ".project" / "activity.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert any(e.get("item_id") == "US-TST-1-6" for e in lines), (
        "the task was never logged at all, so this proves nothing about the filter"
    )
    assert all(
        "run_id" not in e or e["run_id"] is None
        for e in lines
        if e.get("item_id") == "US-TST-1-6"
    )
