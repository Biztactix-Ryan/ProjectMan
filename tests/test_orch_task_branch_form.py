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
from pathlib import Path

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
    # the one ``-d`` left is the run branch's, run on ``<sb>`` after the clean-run
    # merge (US-PM-68-7) — there HEAD does carry it, so ``-d`` is the safe form
    assert re.findall(r"git branch -d [^`\s]+", stop) in ([], ["git branch -d <rb>"])
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


# ─── the reference docs a reader meets before the skill ────────────────────
#
# ``orchestrate-design.md`` and ``skills.md`` describe the branch model in
# prose; the tests above scan only the skills.  The design doc names the
# nested form once on purpose — to say git refuses it — so an old-form hit is
# allowed only inside that one explanatory sentence, matched verbatim (after
# whitespace is normalised).  Any other sentence naming the nested form fails,
# even one that mentions "refuses" nearby.

REFERENCE_DOCS = {
    name: Path(__file__).resolve().parent.parent / "docs" / "reference" / name
    for name in ("orchestrate-design.md", "skills.md")
}

#: the docs spell the run ``<run-id>``
DOC_NEW_FORM = "orch/<run-id>--<task-id>"


#: the one sentence allowed to name the nested form: it says git refuses it
ALLOWED_EXPLANATION = (
    "git stores `orch/<run-id>` as a file, so it refuses to create "
    "`orch/<run-id>/<task-id>` while the run branch exists"
)


def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _unexplained_old_form_hits(text: str) -> list[str]:
    return OLD_FORM.findall(_normalise_ws(text).replace(ALLOWED_EXPLANATION, ""))


@pytest.mark.parametrize("name", list(REFERENCE_DOCS), ids=list(REFERENCE_DOCS))
def test_reference_docs_name_the_sibling_task_branch(name):
    text = REFERENCE_DOCS[name].read_text(encoding="utf-8")
    assert DOC_NEW_FORM in text, f"docs/reference/{name} names no {DOC_NEW_FORM}"
    hits = _unexplained_old_form_hits(text)
    assert not hits, (
        f"docs/reference/{name} names the nested task branch form as the one "
        f"in use, which git refuses while orch/<run-id> exists: {hits}"
    )


def test_reference_doc_carries_the_allowed_explanation():
    """The allowance is pinned to text that exists — not a dead exemption."""
    text = _normalise_ws(REFERENCE_DOCS["orchestrate-design.md"].read_text(encoding="utf-8"))
    assert ALLOWED_EXPLANATION in text


@pytest.mark.parametrize(
    "regressed",
    [
        "a git worktree on `orch/<run-id>/<task-id>`, cut from the run branch",
        "by reading `git branch --list 'orch/<run-id>/*'` against",
        # "refuses" nearby must not excuse a nested form used as the instruction
        "If git refuses the push, cut `orch/<run-id>/<task-id>` instead.",
        "git refuses to create a tag, so cut `orch/<run-id>/<task-id>` instead",
        "git stores `orch/<run-id>` as a file, so it refuses to create\n"
        "`orch/<run-id>--<task-id>`; use `orch/<run-id>/<task-id>` instead",
    ],
)
def test_the_docs_detector_bites(regressed):
    """Falsification: the docs scan catches a nested form not explained away."""
    assert _unexplained_old_form_hits(regressed)
    # the exact explanatory sentence, however it is wrapped, is the only pass
    assert not _unexplained_old_form_hits(
        ALLOWED_EXPLANATION.replace(" `orch/<run-id>/", "\n`orch/<run-id>/")
    )
    assert _unexplained_old_form_hits(ALLOWED_EXPLANATION + " " + regressed)
