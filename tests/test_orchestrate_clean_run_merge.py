"""The run branch always lands; only review/parked task branches stay behind.

US-PM-68-7 first landed a run only when nothing was parked, in review or
unmerged.  But a task's work reaches the run branch ``<rb>`` only through an
accept, so ``<rb>`` never holds unaccepted work: parked and review tasks live on
their own task branches ``<tb>`` and are never merged into it.  Holding ``<rb>``
back for them made a user merge nineteen accepted commits by hand because one
task was in review.  The rule since 2026-10-20:

* Phase 0 records the start branch, ``<sb>``, with ``git branch --show-current``;
* Stop Conditions merges ``<rb>`` into ``<sb>`` *regardless* of parked/review
  tasks: ``git merge --ff-only <rb>``, falling back to ``--no-ff -m "<this run>"``,
  then ``git branch -d <rb>``, and reports it;
* a ``<rb>`` with no commits beyond ``<sb>`` is just deleted;
* only a dirty tree outside ``.project/``, or a conflicting merge (aborted with
  ``git merge --abort``), keeps ``<rb>`` and prints ``git merge --no-ff <rb>``;
* parked/review ``<tb>`` branches and worktrees are kept and listed as
  ``not landed: <task> <tb> <worktree>``;
* the merge comes after ``<rw>`` is removed — git refuses to delete a branch
  checked out in a worktree.

The git behaviour the wording relies on is checked against throwaway
repositories under ``tmp_path`` — never this one.
"""

import re
import subprocess

import pytest

from tests.test_orchestrate_skill_size import REPO_ROOT, design_section
from tests.test_skill_audit_digest import _stop_conditions
from tests.test_skill_verdict_verbs import DOCS, _text

INSTALLATION = REPO_ROOT / "docs" / "installation.md"

#: the pre-US-PM-68-7 Stop Conditions tail: always print, never merge
PRE_CHANGE_TAIL = "remove `<rw>` last, after 23's list. Print `git merge --no-ff <rb>`."

#: the US-PM-68-7 tail: any parked/review/unmerged task kept the whole run branch
GATED_TAIL = (
    "remove `<rw>` last, after 23's list. Then, if 22's log has nothing parked, in "
    "review or unmerged and `git status --short` is clean outside `.project/`, on "
    '`<sb>`: `git merge --ff-only <rb>` (moved: `--no-ff -m "<this run>"`), '
    "`git branch -d <rb>`, report it; else keep `<rb>`, print `git merge --no-ff <rb>`."
)

NOT_LANDED_LINE = "`not landed: <task> <tb> <worktree>`"


def _phase_0(text: str) -> str:
    return text.split("## Phase 0", 1)[1].split("\n## ", 1)[0]


def _merge_clause(stop: str) -> str:
    """The sentence after the run worktree's removal: the merge decision."""
    tail = stop.split("remove `<rw>` last", 1)[1]
    return tail.split("\n", 1)[0]


def _always_lands_the_run(stop: str) -> bool:
    """The whole landing contract, as one predicate the guard can bite on."""
    if "remove `<rw>` last" not in stop or NOT_LANDED_LINE not in stop:
        return False
    clause = _merge_clause(stop)
    ungated = "regardless" in clause and not re.search(r"nothing parked|in review", clause)
    empty = re.search(r"not ahead[^;]{0,20}`-d`", clause)
    recheck = "git status --short" in clause and "outside `.project/`" in clause
    ff = re.search(r"[Oo]n `<sb>`.{0,160}`git merge --ff-only <rb>`", clause)
    fallback = '--no-ff -m "<this run>"' in clause
    delete = "git branch -d <rb>" in clause
    report = "report" in clause
    kept = re.search(
        r"dirty or conflict \(`git merge --abort`\) → keep `<rb>`, print `git merge --no-ff <rb>`",
        clause,
    )
    ordered = (
        clause.index("git merge --ff-only") < clause.index("git branch -d <rb>")
        if ff and delete
        else False
    )
    return all((ungated, empty, recheck, ff, fallback, delete, report, kept, ordered))


@pytest.mark.parametrize("path", DOCS)
def test_phase_0_records_the_start_branch(path):
    phase_0 = _phase_0(_text(path))
    assert "`<sb>` = `git branch --show-current`" in phase_0, (
        f"Phase 0 never records the branch the run started from:\n\n{phase_0}"
    )
    assert phase_0.index("<sb>") < phase_0.index("git branch orch/<this run> HEAD"), (
        "<sb> must be read before the run branch is cut"
    )


@pytest.mark.parametrize("path", DOCS)
def test_stop_conditions_always_land_the_run_branch(path):
    stop = _stop_conditions(_text(path))
    assert _always_lands_the_run(stop), (
        "Stop Conditions does not say: regardless of parked/review, ff-merge <rb> "
        "into <sb> and delete it; only dirt or a conflict keeps <rb>:\n\n" + stop
    )


@pytest.mark.parametrize("path", DOCS)
def test_stop_conditions_keep_and_list_the_review_and_parked_task_branches(path):
    stop = _stop_conditions(_text(path))
    head = stop.split("remove `<rw>` last", 1)[0]
    assert re.search(r"parked/review keep both, listed as " + re.escape(NOT_LANDED_LINE), head), (
        f"Stop Conditions no longer keeps and lists the parked/review <tb>:\n\n{stop}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_merge_comes_after_the_run_worktree_is_removed(path):
    """``git branch -d <rb>`` fails while ``<rw>`` still has it checked out."""
    stop = _stop_conditions(_text(path))
    assert stop.index("remove `<rw>` last") < stop.index("git merge --ff-only <rb>")


def test_the_detector_rejects_the_print_only_and_the_gated_tails():
    """Falsification: neither earlier Stop Conditions tail passes the detector."""
    stop = _stop_conditions(_text(DOCS[0].values[0]))
    current_tail = "remove `<rw>` last" + _merge_clause(stop)
    for old_tail in (PRE_CHANGE_TAIL, GATED_TAIL):
        regressed = stop.replace(current_tail, old_tail)
        assert regressed != stop
        assert not _always_lands_the_run(regressed)
    # and each half of the contract is load-bearing on its own
    for old, new in (
        ("git branch -d <rb>", "git branch -D <rb>"),
        ("regardless", "if nothing parked"),
        ("(`git merge --abort`)", ""),
        ("keep `<rb>`", "drop `<rb>`"),
        ("not ahead", "ahead"),
        (NOT_LANDED_LINE, "`<tb>`"),
    ):
        mutated = stop.replace(old, new)
        assert mutated != stop, old
        assert not _always_lands_the_run(mutated), old


def test_design_doc_says_the_run_branch_always_lands():
    section = re.sub(r"\s+", " ", design_section("## Isolation model"))
    assert "The run branch always lands" in section
    assert "never holds unaccepted work" in section
    assert "Review and parked branches are what the user reads" in section
    assert "git branch --show-current" in section
    assert "git merge --abort" in section
    assert "nothing parked, nothing sent to review" not in section


def test_installation_documents_the_permission_rule_the_merge_needs():
    text = INSTALLATION.read_text(encoding="utf-8")
    assert "### Letting a clean orchestrate run merge" in text
    section = text.split("### Letting a clean orchestrate run merge", 1)[1].split("\n### ", 1)[0]
    flat = re.sub(r"\s+", " ", section)
    assert "auto-mode classifier" in flat
    assert '"Bash(git merge --ff-only orch/*)"' in section
    assert ".claude/settings.local.json" in flat
    assert "lands even when some tasks were parked or sent to review" in flat
    assert "A run with parked or review work never merges" not in flat


# ─── safety rules the budget trims for this task must not take ─────
#
# Fitting the merge clause into MAX_CHARS once cost two rules their words.
# Each is pinned on its own step so the next trim fails here, not in a run.


def _plan_step(text: str, prefix: str) -> str:
    """The one line of numbered step ``prefix`` (these steps are single lines)."""
    lines = [line for line in text.splitlines() if line.startswith(prefix)]
    assert len(lines) == 1, f"expected one line starting {prefix!r}, found {len(lines)}"
    return lines[0]


def _flags_out_of_sprint_blockers(step: str) -> bool:
    return bool(re.search(r"flag[^.;]{0,20}out-of-sprint blockers", step))


def _never_takes_a_task_held_elsewhere(step: str) -> bool:
    return bool(re.search(r"never[^.;]{0,20}held elsewhere", step))


@pytest.mark.parametrize("path", DOCS)
def test_plan_steps_flag_out_of_sprint_blockers(path):
    step = _plan_step(_text(path), "6-10.")
    assert _flags_out_of_sprint_blockers(step), (
        f"steps 6-10 no longer say to flag out-of-sprint blockers:\n\n{step}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_12_never_takes_a_task_held_elsewhere(path):
    """``unassigned`` only implies it; the prohibition is said out loud."""
    step = _plan_step(_text(path), "12.")
    assert _never_takes_a_task_held_elsewhere(step), (
        f"step 12 no longer forbids taking a task held elsewhere:\n\n{step}"
    )


def _refill_stays_compatible_with_the_lane_in_flight(step: str) -> bool:
    """Step 11 checks only B against A; refilling A must check it against B too."""
    return bool(re.search(r"refill[^.]{0,30}\(11/12, compatible with the task in flight\)", step))


@pytest.mark.parametrize("path", DOCS)
def test_step_15_refills_a_lane_compatible_with_the_task_in_flight(path):
    step = _plan_step(_text(path), "15.")
    assert _refill_stays_compatible_with_the_lane_in_flight(step), (
        f"step 15's refill no longer requires compatibility with the task in flight:\n\n{step}"
    )


def test_the_safety_rule_detectors_bite_on_the_trimmed_wording():
    """Falsification: the over-trimmed steps 6-10, 12 and 15 are rejected."""
    text = _text(DOCS[0].values[0])
    plan = _plan_step(text, "6-10.")
    grab = _plan_step(text, "12.")
    refill = _plan_step(text, "15.")
    assert not _flags_out_of_sprint_blockers(plan.replace(", flag out-of-sprint blockers", ""))
    assert not _never_takes_a_task_held_elsewhere(grab.replace("; never one held elsewhere", ""))
    trimmed = refill.replace("(11/12, compatible with the task in flight)", "(11/12)")
    assert trimmed != refill
    assert not _refill_stays_compatible_with_the_lane_in_flight(trimmed)


# ─── the git behaviour the wording relies on, in a throwaway repo ──


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _commit(repo, name, content=None):
    (repo / name).write_text(content or name, encoding="utf-8")
    assert _git(repo, "add", name).returncode == 0
    assert _git(repo, "commit", "-q", "-m", name).returncode == 0


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _commit(repo, "base")
    assert _git(repo, "branch", "orch/run").returncode == 0
    wt = tmp_path / "rw"
    assert _git(repo, "worktree", "add", "-q", str(wt), "orch/run").returncode == 0
    _commit(wt, "task")
    return repo, wt


def test_ff_merge_then_safe_delete_on_the_start_branch(repo):
    repo, wt = repo
    assert _git(repo, "branch", "-d", "orch/run").returncode != 0, (
        "git let -d delete a branch still checked out in <rw>"
    )
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert _git(repo, "merge", "--ff-only", "orch/run").returncode == 0
    assert _git(repo, "branch", "-d", "orch/run").returncode == 0
    assert (repo / "task").exists()


# ─── the whole stop-condition decision, end to end in a throwaway repo ──
#
# ``_land_or_keep`` is the Stop Conditions clause transcribed step for step:
# list the parked/review task branches as not landed; an empty ``<rb>`` is
# deleted; else gate on ``git status --short`` outside ``.project/``, then
# ff-only (falling back to ``--no-ff``, aborting a conflict) and ``-d``, or keep
# and print.  The run log's outcomes never gate the merge.

#: run-log outcomes whose task branch is kept and reported as not landed
NOT_LANDED_OUTCOMES = ("parked", "review")


def _dirty_outside_project(repo) -> bool:
    status = _git(repo, "status", "--short").stdout.splitlines()
    return any(not line[3:].startswith(".project/") for line in status if line.strip())


def _land_or_keep(repo, sb, rb, log, this_run="orch-test"):
    """Return ``(outcome, printed merge command or None, not-landed lines)``.

    ``outcome`` is ``"merged"``, ``"deleted"`` (no commits beyond ``<sb>``) or
    ``"kept"``.
    """
    not_landed = [
        f"not landed: {e['id']} {e['tb']} {e['worktree']}"
        for e in log
        if e["outcome"] in NOT_LANDED_OUTCOMES
    ]
    assert _git(repo, "branch", "--show-current").stdout.strip() == sb
    ahead = int(_git(repo, "rev-list", "--count", f"{sb}..{rb}").stdout.strip())
    if ahead == 0:
        assert _git(repo, "branch", "-d", rb).returncode == 0
        return "deleted", None, not_landed
    keep = ("kept", f"git merge --no-ff {rb}", not_landed)
    if _dirty_outside_project(repo):
        return keep
    if _git(repo, "merge", "--ff-only", rb).returncode != 0:
        if _git(repo, "merge", "--no-ff", "-m", this_run, rb).returncode != 0:
            assert _git(repo, "merge", "--abort").returncode == 0
            return keep
    assert _git(repo, "branch", "-d", rb).returncode == 0
    return "merged", None, not_landed


def _branch_exists(repo, name) -> bool:
    return _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}").returncode == 0


def _head(repo, ref="HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


CLEAN_LOG = [{"id": "T-1", "outcome": "merged"}, {"id": "T-2", "outcome": "merged"}]
KEPT = ("kept", "git merge --no-ff orch/run", [])


def test_decision_clean_run_fast_forwards_and_deletes_the_run_branch(repo):
    repo, wt = repo
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    run_tip = _head(repo, "orch/run")
    assert _land_or_keep(repo, "main", "orch/run", CLEAN_LOG) == ("merged", None, [])
    assert not _branch_exists(repo, "orch/run")
    assert _head(repo) == run_tip, "a clean run on an unmoved <sb> must fast-forward"


@pytest.mark.parametrize("outcome", NOT_LANDED_OUTCOMES)
def test_decision_a_review_or_parked_task_does_not_hold_the_run_back(repo, tmp_path, outcome):
    """The accepted work lands; the held task's branch and worktree stay as they are."""
    repo, wt = repo
    tb, tw = "orch/run--T-3", tmp_path / "tw"
    assert _git(repo, "worktree", "add", "-q", "-b", tb, str(tw), "orch/run").returncode == 0
    _commit(tw, "held-work")
    tb_tip = _head(repo, tb)
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    run_tip = _head(repo, "orch/run")
    log = CLEAN_LOG + [{"id": "T-3", "outcome": outcome, "tb": tb, "worktree": str(tw)}]
    result = _land_or_keep(repo, "main", "orch/run", log)
    assert result == ("merged", None, [f"not landed: T-3 {tb} {tw}"])
    assert not _branch_exists(repo, "orch/run")
    assert _head(repo) == run_tip and (repo / "task").exists()
    assert _branch_exists(repo, tb) and _head(repo, tb) == tb_tip, f"the {outcome} <tb> moved"
    assert (tw / "held-work").exists(), f"the {outcome} task's worktree is gone"
    assert not (repo / "held-work").exists(), f"the {outcome} task's work leaked into <sb>"


def test_decision_a_moved_start_branch_takes_no_ff(repo):
    repo, wt = repo
    _commit(repo, "moved")
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    assert _land_or_keep(repo, "main", "orch/run", CLEAN_LOG) == ("merged", None, [])
    assert not _branch_exists(repo, "orch/run")
    parents = _git(repo, "rev-list", "--parents", "-n1", "HEAD").stdout.split()
    assert len(parents) == 3, "the --no-ff fallback must leave a merge commit"
    assert (repo / "task").exists() and (repo / "moved").exists()


@pytest.mark.parametrize("dirt", ["untracked", "modified"])
def test_decision_a_dirty_tree_outside_project_keeps_the_run_branch(repo, dirt):
    repo, wt = repo
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    if dirt == "untracked":
        (repo / "stray.txt").write_text("x", encoding="utf-8")
    else:
        (repo / "base").write_text("edited", encoding="utf-8")
    before = _head(repo)
    assert _land_or_keep(repo, "main", "orch/run", CLEAN_LOG) == KEPT
    assert _branch_exists(repo, "orch/run")
    assert _head(repo) == before


def test_decision_a_conflict_aborts_and_keeps_the_run_branch(repo):
    repo, wt = repo
    _commit(repo, "task", "a different task file on <sb>")
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    before = _head(repo)
    assert _land_or_keep(repo, "main", "orch/run", CLEAN_LOG) == KEPT
    assert _branch_exists(repo, "orch/run")
    assert _head(repo) == before
    assert _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode != 0, (
        "the conflicting merge was left in progress, not aborted"
    )
    assert _git(repo, "status", "--short").stdout.strip() == ""


def test_decision_a_run_branch_with_no_commits_is_just_deleted(repo, tmp_path):
    repo, wt = repo
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    assert _git(repo, "branch", "orch/empty", "main").returncode == 0
    before = _head(repo)
    assert _land_or_keep(repo, "main", "orch/empty", CLEAN_LOG) == ("deleted", None, [])
    assert not _branch_exists(repo, "orch/empty")
    assert _head(repo) == before


def test_decision_dirt_only_under_project_still_lands_the_run(repo):
    """``outside .project/`` is load-bearing: Store churn never blocks the merge."""
    repo, wt = repo
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    (repo / ".project").mkdir()
    (repo / ".project" / "activity.jsonl").write_text("{}\n", encoding="utf-8")
    assert _land_or_keep(repo, "main", "orch/run", CLEAN_LOG) == ("merged", None, [])
    assert not _branch_exists(repo, "orch/run")
    assert (repo / "task").exists()
