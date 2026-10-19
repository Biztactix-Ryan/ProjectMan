"""US-PM-68-6 — task branches are ``orch/<run>--<task-id>``, never ``orch/<run>/<task-id>``.

Phase 0 cuts the run branch ``orch/<run>``; git stores that ref as a file
under ``refs/heads/orch/``, so it refuses to create ``orch/<run>/<task-id>``
while the run branch exists (a ref cannot be both a file and a directory).
The task branch is therefore a sibling, ``orch/<run>--<task-id>``, and step
23 lists the run's task branches with ``'<rb>--*'``.

These tests fail if the old nested form survives anywhere an orchestrator or
a worker reads it: the pm-orchestrate template, its tracked rendered copy, a
live render, the worker prompt fence, and the pm-do skill a worker follows.
The git case at the bottom shows the refusal is real, in a throwaway repo
under ``tmp_path`` — never against this repository.
"""

import re
import subprocess

import pytest

from projectman.cli import _render_template
from tests.test_orchestrate_worker_prompt import ORCHESTRATE_SOURCES, PM_DO_SOURCES
from tests.test_skill_guidance_tools import _worker_fence

#: every spelling of the nested form the skills used before US-PM-68-6
OLD_FORM = re.compile(
    r"orch/<(?:this run|run|run-id)>/(?:<task-id>|\*)"
    r"|<rb>/<task-id>"
    r"|'<rb>/\*'"
)

#: the sibling form, with the run spelled as the skills spell it
NEW_FORM = re.compile(r"orch/<(?:this run|run)>--<task-id>")


def _old_form_hits(text: str) -> list[str]:
    return OLD_FORM.findall(text)


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
def test_orchestrate_skill_carries_no_nested_task_branch(source):
    text = ORCHESTRATE_SOURCES[source]()
    hits = _old_form_hits(text)
    assert not hits, (
        f"pm-orchestrate ({source}) still names the nested task branch form, "
        f"which git refuses while orch/<run> exists: {hits}"
    )
    assert "`<tb>` = `<rb>--<task-id>`" in text, (
        f"pm-orchestrate ({source}): Phase 0 does not define <tb> as <rb>--<task-id>"
    )
    assert "git branch --list '<rb>--*'" in text, (
        f"pm-orchestrate ({source}): step 23 does not list the run's '<rb>--*' branches"
    )


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
def test_worker_prompt_cuts_the_sibling_task_branch(source):
    fence = _worker_fence(ORCHESTRATE_SOURCES[source]())
    assert not _old_form_hits(fence), f"worker prompt ({source}) cuts a nested branch"
    assert "git switch -c orch/<this run>--<task-id> orch/<this run>" in fence


@pytest.mark.parametrize("source", list(PM_DO_SOURCES), ids=list(PM_DO_SOURCES))
def test_pm_do_names_the_sibling_task_branch(source):
    text = PM_DO_SOURCES[source]()
    assert not _old_form_hits(text), f"pm-do ({source}) names the nested branch form"
    assert NEW_FORM.search(text), f"pm-do ({source}) names no orch/<run>--<task-id>"


def test_stop_conditions_force_delete_only_merged_task_branches():
    """``-d`` checks against HEAD, which lacks the run's merges, so it refuses."""
    text = _render_template("skill_pm_orchestrate.md.j2")
    stop = text.split("## Stop Conditions", 1)[1].split("\n## ", 1)[0]
    assert "git branch -D <tb>" in stop
    assert "git branch -d" not in stop
    assert "23's merged" in stop, "the -D is not tied to step 23's --merged list"


@pytest.mark.parametrize(
    "regressed",
    [
        "`git switch -c orch/<this run>/<task-id> orch/<this run>`",
        "`<tb>` = `<rb>/<task-id>`",
        "git branch --list 'orch/<this run>/*'",
        "on branch `orch/<run>/<task-id>`",
    ],
)
def test_the_old_form_detector_bites(regressed):
    """Falsification: each pre-US-PM-68-6 spelling is caught by the detector."""
    assert _old_form_hits(regressed)
    assert not _old_form_hits(regressed.replace("/<task-id>", "--<task-id>").replace("/*", "--*"))


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def test_git_refuses_the_nested_form_and_accepts_the_sibling(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    assert _git(
        repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "root",
    ).returncode == 0
    assert _git(repo, "branch", "orch/r1").returncode == 0

    nested = _git(repo, "branch", "orch/r1/T-1", "orch/r1")
    assert nested.returncode != 0, "git accepted a ref nested under orch/r1"

    sibling = _git(repo, "branch", "orch/r1--T-1", "orch/r1")
    assert sibling.returncode == 0, sibling.stderr
    listed = _git(repo, "branch", "--list", "orch/r1--*").stdout.split()
    assert listed == ["orch/r1--T-1"]
