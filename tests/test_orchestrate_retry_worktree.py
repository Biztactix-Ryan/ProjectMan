"""US-PM-68-9 — a retry worker continues in the first attempt's worktree.

Story US-PM-68's acceptance criterion:

    "A retry worker continues in the first attempt's worktree instead of a
    fresh one"

A worker dispatched with ``isolation: "worktree"`` gets a *fresh* worktree.
On a retry its task branch ``orch/<run>--<task-id>`` is still checked out in
the first attempt's worktree, and git refuses to check one branch out in two
worktrees, so the retry's ``git switch`` fails and the worker is stranded.  So
the retry path is pinned, on the template, the tracked rendered copy and a
live render:

* step 14 notes each dispatch's worktree path, so a retry can name it;
* step 19's Retry bullet dispatches the retry worker with **no** isolation,
  naming that path (the conflict retry goes through the same bullet);
* the worker prompt's retry line tells it to ``cd`` into the first report's
  worktree, fix on the same branch and amend to keep one commit, rebasing onto
  the run branch first after a merge conflict; and the first-line
  ``git switch -c`` is not run on a retry.

A falsification guard shows the pre-US-PM-68-9 wording fails every clause, and
a git case under ``tmp_path`` — never against this repository — shows the
refusal that motivates it is real.
"""

import re
import subprocess

import pytest

from tests.test_orchestrate_lanes import _step
from tests.test_orchestrate_skill_size import design_section
from tests.test_orchestrate_worker_prompt import ORCHESTRATE_SOURCES
from tests.test_skill_guidance_tools import _worker_fence


def _flat(text: str) -> str:
    return " ".join(text.split())


def _retry_bullet(text: str) -> str:
    step = _step(text, "19.")
    lines = [line for line in step.splitlines() if line.strip().startswith("- **Retry**")]
    assert len(lines) == 1, f"step 19 has no single Retry bullet:\n\n{step}"
    return lines[0]


def _retry_line(fence: str) -> str:
    match = re.search(r"<on retry:.*?\">", fence, re.DOTALL)
    assert match, f"the worker prompt has no <on retry: line:\n\n{fence}"
    return _flat(match.group())


CLAUSES = {
    "step 14 notes the worktree path per dispatch": lambda t: "worktree path"
    in _flat(_step(t, "14.")),
    "the retry worker is dispatched without isolation": lambda t: bool(
        re.search(r"no `isolation`", _retry_bullet(t))
    ),
    "the retry names the noted worktree path": lambda t: bool(
        re.search(r"14's path", _retry_bullet(t))
    ),
    "the retry worker cds into the first worktree": lambda t: bool(
        re.search(
            r"`cd <worktree path from the first report>`",
            _retry_line(_worker_fence(t)),
        )
    ),
    "the retry amends to keep one commit": lambda t: bool(
        re.search(r"amend to keep one commit", _retry_line(_worker_fence(t)))
    ),
    "a conflict retry rebases onto the run branch first": lambda t: bool(
        re.search(r"git rebase orch/<this run>` first", _retry_line(_worker_fence(t)))
    ),
    "a retry does not cut the branch again": lambda t: bool(
        re.search(r"\(not on retry\)", _flat(_worker_fence(t)))
    ),
}


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_a_retry_continues_in_the_first_worktree(source, clause):
    text = ORCHESTRATE_SOURCES[source]()
    assert CLAUSES[clause](text), f"{source}: the retry path fails: {clause}"


def test_the_clauses_reject_the_fresh_worktree_retry():
    """Falsification guard: the pre-US-PM-68-9 wording must fail every clause."""
    old = (
        "14. Note lane and `<tb>` before **each** dispatch; `--lanes 2`: one claim.\n"
        "19. **Verdict**\n"
        '    - **Retry** (first failure): `pm_retry(task_id, note="<why>")` → '
        "`todo`; dispatch **one** retry worker.\n"
        "20. Only `pm_accept` closes a task.\n"
        "\n```\nYou are executing a single ProjectMan task.\n"
        '<on retry: "last attempt failed: <failures>; fix on the same branch; after a\n'
        'merge conflict `git rebase orch/<this run>` first">\n'
        "First `git switch -c orch/<this run>--<task-id> orch/<this run>` (retry: plain\n"
        "`git switch`), then /projectman:pm-do.\n"
        "Report back under 1500 chars.\n```\n"
    )
    passed = [name for name, check in CLAUSES.items() if check(old)]
    # the rebase-on-conflict clause predates US-PM-68-9 and is kept, not added
    assert passed == ["a conflict retry rebases onto the run branch first"], passed


def test_the_design_doc_explains_why_a_retry_reuses_the_worktree():
    section = _flat(design_section("## Validation and verdicts"))
    assert "first attempt's worktree" in section, section
    assert "isolation" in section and "checked out" in section, section


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def test_a_fresh_worktree_cannot_switch_to_a_branch_checked_out_elsewhere(tmp_path):
    """The refusal is real: why the retry must cd rather than switch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "f")
    assert _git(repo, "commit", "-q", "-m", "init").returncode == 0
    assert _git(repo, "branch", "orch/r").returncode == 0
    first = tmp_path / "first"
    assert _git(repo, "worktree", "add", "-q", "-b", "orch/r--T-1", str(first), "orch/r").returncode == 0
    fresh = tmp_path / "fresh"
    assert _git(repo, "worktree", "add", "-q", "--detach", str(fresh), "orch/r").returncode == 0

    refused = _git(fresh, "switch", "orch/r--T-1")
    assert refused.returncode != 0, "git let two worktrees check out one branch"

    (first / "f").write_text("y\n", encoding="utf-8")
    _git(first, "commit", "-q", "-am", "T-1")
    (first / "f").write_text("z\n", encoding="utf-8")
    assert _git(first, "commit", "-q", "-a", "--amend", "--no-edit").returncode == 0
    count = _git(first, "rev-list", "--count", "orch/r..orch/r--T-1").stdout.strip()
    assert count == "1", "amending in the first worktree did not keep one commit"


# --- US-PM-68-4: the prescribed retry flow, end to end, under tmp_path ------


def _ok(cwd, *args):
    result = _git(cwd, *args)
    assert result.returncode == 0, f"git {' '.join(args)} failed:\n{result.stderr}"
    return result.stdout.strip()


def _run_layout(tmp_path):
    """A repo with run branch ``orch/r`` merged in its own worktree ``rw``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _ok(repo, "init", "-q", "-b", "main")
    _ok(repo, "config", "user.email", "t@example.invalid")
    _ok(repo, "config", "user.name", "t")
    _ok(repo, "config", "commit.gpgsign", "false")
    (repo / "f").write_text("base\n", encoding="utf-8")
    (repo / "g").write_text("base\n", encoding="utf-8")
    _ok(repo, "add", "f", "g")
    _ok(repo, "commit", "-q", "-m", "init")
    _ok(repo, "branch", "orch/r", "HEAD")
    rw = tmp_path / "rw"
    _ok(repo, "worktree", "add", "-q", str(rw), "orch/r")
    return repo, rw


def _first_attempt(repo, path, task, filename, content):
    """What an isolated first worker does: own worktree, `switch -c`, one commit."""
    _ok(repo, "worktree", "add", "-q", "--detach", str(path), "orch/r")
    _ok(path, "switch", "-q", "-c", f"orch/r--{task}", "orch/r")
    (path / filename).write_text(content, encoding="utf-8")
    _ok(path, "commit", "-q", "-am", task)
    return _ok(path, "rev-parse", "HEAD")


def _commits_ahead(cwd, task):
    return _ok(cwd, "rev-list", "--count", f"orch/r..orch/r--{task}")


def test_a_retry_in_the_first_worktree_amends_to_one_commit_and_ff_merges(tmp_path):
    """Retry: cd into the first worktree, fix, amend; the run branch ff-merges it."""
    repo, rw = _run_layout(tmp_path)
    first = tmp_path / "first"
    first_sha = _first_attempt(repo, first, "T-1", "f", "attempt 1\n")

    # the retry worker skips the first line: re-cutting the branch is refused
    assert _git(first, "switch", "-c", "orch/r--T-1", "orch/r").returncode != 0

    # retry: same worktree, same branch, amend
    assert _ok(first, "branch", "--show-current") == "orch/r--T-1"
    (first / "f").write_text("attempt 2\n", encoding="utf-8")
    _ok(first, "commit", "-q", "-a", "--amend", "--no-edit")
    retry_sha = _ok(first, "rev-parse", "HEAD")
    assert retry_sha != first_sha
    assert _commits_ahead(first, "T-1") == "1"

    # step 19 Accept: merge in <rw> while the task branch stays checked out in first
    _ok(rw, "merge", "--ff-only", "orch/r--T-1")
    assert _ok(rw, "rev-parse", "HEAD") == retry_sha
    assert (rw / "f").read_text(encoding="utf-8") == "attempt 2\n"
    merged = _git(rw, "merge-base", "--is-ancestor", first_sha, "HEAD")
    assert merged.returncode != 0, "the failed first attempt reached the run branch"


def test_a_conflict_retry_rebases_in_the_first_worktree_and_keeps_one_commit(tmp_path):
    """Conflict retry: `git rebase orch/r` in the first worktree, then one commit."""
    repo, rw = _run_layout(tmp_path)
    lane_a, lane_b = tmp_path / "lane-a", tmp_path / "lane-b"
    _first_attempt(repo, lane_a, "T-A", "f", "from A\n")
    # B is cut before A's merge and touches the same file
    _first_attempt(repo, lane_b, "T-B", "f", "from B\n")

    _ok(rw, "merge", "--ff-only", "orch/r--T-A")
    assert _git(rw, "merge", "--no-ff", "-m", "T-B", "orch/r--T-B").returncode != 0
    _ok(rw, "merge", "--abort")

    # retry worker: cd into B's first worktree, rebase onto the run branch first
    assert _git(lane_b, "rebase", "orch/r").returncode != 0, "expected a rebase conflict"
    (lane_b / "f").write_text("from A\nfrom B\n", encoding="utf-8")
    _ok(lane_b, "add", "f")
    _ok(lane_b, "-c", "core.editor=true", "rebase", "--continue")
    # ...then the retry's fix, amended into the same commit
    (lane_b / "g").write_text("fixed by B's retry\n", encoding="utf-8")
    _ok(lane_b, "commit", "-q", "-a", "--amend", "--no-edit")

    assert _ok(lane_b, "branch", "--show-current") == "orch/r--T-B"
    assert _commits_ahead(lane_b, "T-B") == "1"
    _ok(rw, "merge", "--ff-only", "orch/r--T-B")
    assert (rw / "f").read_text(encoding="utf-8") == "from A\nfrom B\n"
    assert (rw / "g").read_text(encoding="utf-8") == "fixed by B's retry\n"
    log = _ok(rw, "log", "--format=%s", "main..orch/r").splitlines()
    assert log == ["T-B", "T-A"], log
