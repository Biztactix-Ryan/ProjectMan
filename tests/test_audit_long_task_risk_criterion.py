"""Acceptance criterion for US-PM-50 (task US-PM-50-5).

    > pm_audit warns when an active sprint contains a task flagged as
    > long_task_risk

Pinned at the ``pm_audit`` MCP tool boundary — the tool function is imported
from :mod:`projectman.server` and called against a ``tmp_path`` store after a
``monkeypatch.chdir`` and a cache drop, the way
``test_estimate_scope_duration_history.py`` and
``test_long_task_risk_criterion.py`` call server tools — so what is asserted
is the report an MCP client actually receives.

``tests/test_audit.py`` (US-PM-50-10) covers ``audit.check_long_task_risk``
as a unit: the exact message wording, the bands under the ceiling, the
completed sprint, and the empty log.  None of that is repeated here.  This
file pins only what the criterion's own wording carries, plus the two things
that are only visible at the tool boundary:

1. the warning names the flagged task, is rendered ``[WARN]``, and the
   report's **Warnings** count is above zero — the audit *warns*;
2. it is never an error: the **Errors** count stays 0, so /pm-orchestrate,
   which halts a run on any error-level finding, keeps going;
3. "an *active* sprint" — the same store with the same history and the sprint
   left in ``planning`` produces no such finding;
4. the tool's two surfaces agree: the set of task ids the audit warns about is
   exactly the set ``pm_get_sprint`` lists under ``long_task_risk``.  The
   criterion says the audit warns about what that key flags, so the audit
   inventing, dropping or renaming one would falsify it;
5. the ``since=`` short-circuit, which is how /pm-orchestrate actually polls
   this tool, cannot hide the warning: a matching digest answers
   ``unchanged: true``, and a newly appended orchestrated transition changes
   the digest so the very next poll re-runs and re-reports.

History is seeded the way ``test_long_task_risk_criterion.py`` seeds it —
real ``Store`` writes into a ``tmp_path`` project, transitions appended
through ``LogEntry`` + ``append_log_entry`` — so the record shape under test
is the one production writes.  Three bands of three samples each (the minimum
a percentile is drawn from) straddle the 60-minute default ceiling, so two
tasks are flagged and one is not: a set comparison that would pass on "flag
everything" is not worth making.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from projectman.activity_log import append_log_entry
from projectman.audit import DIGEST_LINE_PREFIX, UNCHANGED_LINE
from projectman.models import LogEntry
from projectman.store import Store, clear_all_caches

BASE = datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc)

RUN = "orch-2026-09-09-385a"

#: Three samples per band — the fewest ``long_task_risk`` will judge on —
#: placed either side of the 60-minute default ceiling.  Nearest-rank over
#: three samples makes p50 the middle one and p90 the largest:
#:
#:   US-TST-1-1, 1pt: 10/15/20 -> p50 15, p90 20  (under — not flagged)
#:   US-TST-1-2, 2pt: 30/45/90 -> p50 45, p90 90  (over  — flagged)
#:   US-TST-1-3, 3pt: 20/40/70 -> p50 40, p90 70  (over  — flagged)
#:
#: (task, minutes from BASE to the grab, minutes the task ran)
TRANSITIONS = [
    ("US-TST-1-1", 0, 10),
    ("US-TST-1-1", 120, 15),
    ("US-TST-1-1", 240, 20),
    ("US-TST-1-2", 360, 30),
    ("US-TST-1-2", 480, 45),
    ("US-TST-1-2", 600, 90),
    ("US-TST-1-3", 720, 20),
    ("US-TST-1-3", 840, 40),
    ("US-TST-1-3", 960, 70),
]

#: What the two bands above the ceiling must come back as, on both surfaces.
FLAGGED = {"US-TST-1-2", "US-TST-1-3"}

_COUNTS_RE = re.compile(
    r"\*\*Errors:\*\* (\d+) \| \*\*Warnings:\*\* (\d+) \| \*\*Info:\*\* (\d+)"
)

#: The rendered report carries the finding's message, not its ``check`` key,
#: so the long-task findings are picked out by the phrase only Check 18's
#: message contains, and the id is read back off the line.
_RISK_LINE_RE = re.compile(r"^- \[(\w+)\] Task (\S+) \(\d+pt\) in active sprint ")
_RISK_MARK = "max_task_minutes ceiling"


def _append(store, item_id, minute, changes, run_id=RUN):
    append_log_entry(
        store.project_dir / "activity.jsonl",
        LogEntry(
            event_type="update",
            item_id=item_id,
            item_type="task",
            changes=changes,
            timestamp=BASE + timedelta(minutes=minute),
            actor="claude",
            source="cli",
            run_id=run_id,
        ),
    )


def _write_history(store, transitions=TRANSITIONS, run_id=RUN):
    """A grab/done pair per transition, in chronological order."""
    for item_id, start, ran in transitions:
        _append(
            store,
            item_id,
            start,
            # A grab moves the assignee at the same time as the status, the
            # way pm_grab's log line does.
            {
                "assignee": {"before": None, "after": "claude"},
                "status": {"before": "todo", "after": "in-progress"},
            },
            run_id=run_id,
        )
        _append(
            store,
            item_id,
            start + ran,
            {"status": {"before": "in-progress", "after": "done"}},
            run_id=run_id,
        )


@pytest.fixture
def risk_store(tmp_project):
    """A 1-, 2- and 3-point task planned into a sprint, with the history above.

    The sprint is left in ``planning``; each test moves it where it needs it,
    so the status is never incidental to what is being asserted.
    """
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    store.create_task("US-TST-1", "One pointer", "A task small enough to finish", points=1)
    store.create_task("US-TST-1", "Two pointer", "A task whose band runs long", points=2)
    store.create_task("US-TST-1", "Three pointer", "A task whose band runs long", points=3)
    store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
    _write_history(store)
    return store


def _cold(tmp_project, monkeypatch):
    """Point the server's tools at *tmp_project*, cache-free.

    Both the server's per-root store cache and the store layer's own caches
    are dropped, so every call reads what is on disk right now — these tests
    change sprint status and append to the log between calls.
    """
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


def _audit(tmp_project, monkeypatch, **kwargs):
    """Call the ``pm_audit`` tool against the tmp store."""
    _cold(tmp_project, monkeypatch)
    from projectman.server import pm_audit

    return pm_audit(**kwargs)


def _sprint_view(tmp_project, monkeypatch, sprint_id="SPRINT-TST-1"):
    """Call the ``pm_get_sprint`` tool against the tmp store."""
    _cold(tmp_project, monkeypatch)
    from projectman.server import pm_get_sprint

    return yaml.safe_load(pm_get_sprint(sprint_id))


def _counts(report):
    """(errors, warnings, info) off the report header."""
    match = _COUNTS_RE.search(report)
    assert match is not None, report
    return tuple(int(g) for g in match.groups())


def _risk_lines(report):
    return [line for line in report.splitlines() if _RISK_MARK in line]


def _risk_findings(report):
    """(severity, task id) per long-task finding in the rendered report."""
    found = []
    for line in _risk_lines(report):
        match = _RISK_LINE_RE.match(line)
        assert match is not None, line
        found.append(match.groups())
    return found


def _digest_of(report):
    lines = [l for l in report.splitlines() if l.startswith(DIGEST_LINE_PREFIX)]
    assert len(lines) == 1, report
    return lines[0][len(DIGEST_LINE_PREFIX) :]


# ═══ § the criterion: an active sprint's flagged tasks are warned about ═══


def test_criterion_active_sprint_with_a_flagged_task_gets_a_named_warning(
    risk_store, tmp_project, monkeypatch
):
    """The whole criterion in one call: the audit warns, once per flagged
    task, naming it — and the report's Warnings count says so."""
    risk_store.update_sprint("SPRINT-TST-1", status="active")

    report = _audit(tmp_project, monkeypatch)

    assert _risk_findings(report) == [("WARN", "US-TST-1-2"), ("WARN", "US-TST-1-3")]
    assert "SPRINT-TST-1" in _risk_lines(report)[0]
    _, warnings, _ = _counts(report)
    assert warnings > 0


def test_criterion_the_warning_is_never_an_error(risk_store, tmp_project, monkeypatch):
    """/pm-orchestrate halts a run on any error-level finding.  "The tasks you
    are about to run are large" is advice for the next planning pass, so it
    must never be the thing that stops the run that would work through them."""
    risk_store.update_sprint("SPRINT-TST-1", status="active")

    report = _audit(tmp_project, monkeypatch)

    assert {severity for severity, _ in _risk_findings(report)} == {"WARN"}
    errors = _counts(report)[0]
    assert errors == 0
    assert "[ERROR]" not in report


def test_criterion_a_planning_sprint_is_not_warned_about(
    risk_store, tmp_project, monkeypatch
):
    """"an *active* sprint" — same store, same history, same tasks, sprint
    still in planning: nothing.  Shaping the sprint is pm-plan's check."""
    assert risk_store.get_sprint("SPRINT-TST-1")[0].status.value == "planning"

    report = _audit(tmp_project, monkeypatch)

    assert _risk_findings(report) == []
    # And it is the sprint's status doing it, not a missing signal: the same
    # store flags both tasks the moment the sprint goes active.
    risk_store.update_sprint("SPRINT-TST-1", status="active")
    assert {task for _, task in _risk_findings(_audit(tmp_project, monkeypatch))} == FLAGGED


def test_criterion_the_audit_warns_about_exactly_what_long_task_risk_flags(
    risk_store, tmp_project, monkeypatch
):
    """"a task flagged as long_task_risk" — the audit's set of ids is the
    sprint view's set of ids, neither wider nor narrower.

    Both surfaces are read off the same store in the same state, so this
    falsifies an audit that warned about every task in the sprint (US-TST-1-1
    is in it and is not flagged) as well as one that missed a flagged task.
    """
    risk_store.update_sprint("SPRINT-TST-1", status="active")

    audited = {task for _, task in _risk_findings(_audit(tmp_project, monkeypatch))}
    view = _sprint_view(tmp_project, monkeypatch)

    flagged = {entry["id"] for entry in view["long_task_risk"]}
    assert audited == flagged == FLAGGED
    # The unflagged task really is in the sprint — the sets agreeing is not
    # an accident of the sprint holding only flagged tasks.
    assert "US-TST-1-1" not in flagged
    planned = {story["story_id"] for story in view["story_progress"]}
    in_sprint = {
        task.id
        for story_id in planned
        for task in risk_store.list_tasks(story_id=story_id, archived=False)
    }
    assert FLAGGED < in_sprint
    assert "US-TST-1-1" in in_sprint


# ═══ § the orchestrator's poll: since= cannot hide the warning ═══════════


def test_a_matching_since_short_circuits_with_unchanged_true(
    risk_store, tmp_project, monkeypatch
):
    """The poll /pm-orchestrate actually makes: nothing changed, so the answer
    is the digest and ``unchanged: true`` rather than the report again."""
    risk_store.update_sprint("SPRINT-TST-1", status="active")
    first = _audit(tmp_project, monkeypatch)
    digest = _digest_of(first)

    answer = _audit(tmp_project, monkeypatch, since=digest)

    assert _digest_of(answer) == digest
    assert UNCHANGED_LINE in answer.splitlines()
    assert _risk_findings(answer) == []
    assert len(answer) < len(first)


def test_a_new_orchestrated_transition_gives_a_new_digest_and_a_fresh_report(
    risk_store, tmp_project, monkeypatch
):
    """A worker finishing a task appends to activity.jsonl, which is inside
    the digest's hashed inputs — so the stale ``since`` no longer matches and
    the next poll re-runs the checks and re-reports the warning."""
    risk_store.update_sprint("SPRINT-TST-1", status="active")
    stale = _digest_of(_audit(tmp_project, monkeypatch))

    _write_history(risk_store, transitions=[("US-TST-1-2", 1080, 95)])

    fresh = _audit(tmp_project, monkeypatch, since=stale)

    assert _digest_of(fresh) != stale
    assert UNCHANGED_LINE not in fresh.splitlines()
    assert {task for _, task in _risk_findings(fresh)} == FLAGGED
