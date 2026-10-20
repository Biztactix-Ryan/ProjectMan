"""US-PM-68-7 — a clean orchestrate run lands itself; any other run stays a branch.

Story US-PM-68's criterion: "A run with nothing parked, in review or unmerged
merges its run branch into the branch it started from and deletes it; otherwise
it keeps the run branch and prints the merge command."

Pinned here, on the template and on the rendered skill:

* Phase 0 records the start branch, ``<sb>``, with ``git branch --show-current``;
* Stop Conditions gates the merge on the run log (nothing parked, in review or
  unmerged) and on a fresh ``git status --short`` outside ``.project/``;
* the clean path is ``git merge --ff-only <rb>`` on ``<sb>``, falling back to
  ``--no-ff -m "<this run>"``, then ``git branch -d <rb>``, and is reported;
* every other run keeps ``<rb>`` and prints ``git merge --no-ff <rb>``;
* the merge comes after ``<rw>`` is removed — git refuses to delete a branch
  checked out in a worktree.

The git behaviour the wording relies on (``-d`` succeeds on ``<sb>`` after the
merge; ``--ff-only`` refuses once ``<sb>`` moved, and ``--no-ff`` then lands it)
is checked against a throwaway repository under ``tmp_path`` — never this one.
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


def _phase_0(text: str) -> str:
    return text.split("## Phase 0", 1)[1].split("\n## ", 1)[0]


def _clean_run_clause(stop: str) -> str:
    """The sentence after the run worktree's removal: the merge decision."""
    tail = stop.split("remove `<rw>` last", 1)[1]
    return tail.split("\n", 1)[0]


def _lands_a_clean_run(stop: str) -> bool:
    """The whole clean-run contract, as one predicate the guard can bite on."""
    if "remove `<rw>` last" not in stop:
        return False
    clause = _clean_run_clause(stop)
    gate = all(word in clause for word in ("parked", "review", "unmerged"))
    recheck = "git status --short" in clause and "outside `.project/`" in clause
    ff = re.search(r"on `<sb>`[^.]{0,10}`git merge --ff-only <rb>`", clause)
    fallback = '--no-ff -m "<this run>"' in clause
    delete = "git branch -d <rb>" in clause
    report = "report" in clause
    otherwise = re.search(r"else keep `<rb>`, print `git merge --no-ff <rb>`", clause)
    ordered = (
        clause.index("git merge --ff-only") < clause.index("git branch -d <rb>")
        if ff and delete
        else False
    )
    return all((gate, recheck, ff, fallback, delete, report, otherwise, ordered))


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
def test_stop_conditions_land_a_clean_run_and_keep_any_other(path):
    stop = _stop_conditions(_text(path))
    assert _lands_a_clean_run(stop), (
        "Stop Conditions does not say: clean run -> ff-merge <rb> into <sb> and "
        f"delete it; else keep <rb> and print the merge command:\n\n{stop}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_merge_comes_after_the_run_worktree_is_removed(path):
    """``git branch -d <rb>`` fails while ``<rw>`` still has it checked out."""
    stop = _stop_conditions(_text(path))
    assert stop.index("remove `<rw>` last") < stop.index("git merge --ff-only <rb>")


def test_the_detector_rejects_the_print_only_tail():
    """Falsification: the pre-change Stop Conditions never merged anything."""
    stop = _stop_conditions(_text(DOCS[0].values[0]))
    current_tail = "remove `<rw>` last" + _clean_run_clause(stop)
    regressed = stop.replace(current_tail, PRE_CHANGE_TAIL)
    assert regressed != stop
    assert not _lands_a_clean_run(regressed)
    # and each half of the contract is load-bearing on its own
    assert not _lands_a_clean_run(stop.replace("git branch -d <rb>", "git branch -D <rb>"))
    assert not _lands_a_clean_run(stop.replace("else keep `<rb>`", "else drop `<rb>`"))
    assert not _lands_a_clean_run(stop.replace("parked", "failed"))


def test_design_doc_says_a_clean_run_lands_and_a_parked_run_stays_a_branch():
    section = design_section("## Isolation model")
    assert "A clean run lands" in section
    assert "stays a branch to read" in section
    assert "git branch --show-current" in section


def test_installation_documents_the_permission_rule_the_merge_needs():
    text = INSTALLATION.read_text(encoding="utf-8")
    assert "### Letting a clean orchestrate run merge" in text
    assert "auto-mode classifier" in text
    assert '"Bash(git merge --ff-only orch/*)"' in text


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


def test_the_safety_rule_detectors_bite_on_the_trimmed_wording():
    """Falsification: the over-trimmed steps 6-10 and 12 are rejected."""
    text = _text(DOCS[0].values[0])
    plan = _plan_step(text, "6-10.")
    grab = _plan_step(text, "12.")
    assert not _flags_out_of_sprint_blockers(plan.replace(", flag out-of-sprint blockers", ""))
    assert not _never_takes_a_task_held_elsewhere(grab.replace("; never one held elsewhere", ""))


# ─── the git behaviour the wording relies on, in a throwaway repo ──


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _commit(repo, name):
    (repo / name).write_text(name, encoding="utf-8")
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


def test_a_moved_start_branch_refuses_ff_and_takes_no_ff(repo):
    repo, wt = repo
    _commit(repo, "moved")
    assert _git(repo, "worktree", "remove", str(wt)).returncode == 0
    assert _git(repo, "merge", "--ff-only", "orch/run").returncode != 0
    assert _git(repo, "merge", "--no-ff", "-m", "run", "orch/run").returncode == 0
    assert _git(repo, "branch", "-d", "orch/run").returncode == 0
    assert (repo / "task").exists() and (repo / "moved").exists()
