"""US-PM-48-1 — validation must be *dispatched*, not performed by the orchestrator.

Story US-PM-48's acceptance criterion:

    "The orchestrate skill template dispatches a validator subagent after each
    worker and never runs the tests or md5 comparison in its own context"

The point of the story is context cost.  A skill that merely *mentions* a
validator while still telling the orchestrator to run ``pytest`` and compare
md5s itself would save nothing: the test output, md5 listings and diff stats
would land in the orchestrator's context exactly as before.  So the criterion
has two halves, and both are pinned here on the Validation steps (16-19):

* **positive** — step 17 spawns a validator ``Agent`` (``general-purpose``,
  foreground, no worktree) using the Validator Prompt Template, and it sits
  after the worker dispatch (step 15) in the per-task cycle step 14 calls
  "before **each** dispatch";
* **negative** — steps 16-19 hand the orchestrator no ``pytest`` / ``md5sum`` /
  ``git diff --stat`` command of its own, and say in as many words never to run
  them itself.  The only check that stays in the orchestrator's own context is
  the projected ``pm_get(task_id, fields="status,assignee")`` status check,
  which is trust-but-verify and costs two fields.

The negative half is deliberately structural rather than prose-matching: a
shell command *for the orchestrator to run* is an inline code span that starts
with the command word, so step 19's ``pm_accept(..., "command": "pytest -q")``
— which relays the validator's report rather than running anything — does not
trip it.  The same forbidden commands are asserted to be *present* in the
Validator Prompt Template fence, so the work is proven moved rather than
deleted.

Both documents are checked, the Jinja template (source of truth) and the
tracked rendered ``.claude/skills/pm-orchestrate/SKILL.md`` an orchestrating
agent actually loads, plus the render produced by ``_render_template`` itself.
Byte-for-byte equality of template and tracked copy is owned by
``test_orchestrate_skill_size.py::test_tracked_rendered_skill_matches_the_template``
and is not re-asserted.

The last test is a falsification guard: the same document with step 17 rewritten
to have the orchestrator run the tests and md5s itself must fail these checks.
A checklist that never fires is not evidence.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_orchestrate_validator_prompt import _validator_fence
from tests.test_skill_verdict_verbs import (
    ORCHESTRATE_TEMPLATE_NAME,
    DOCS,
    _text,
)

#: the Validation block the criterion is about — step 16 up to step 20
FIRST_STEP = "16."
AFTER_LAST_STEP = "20."

#: the worker dispatch the validator must come *after*
WORKER_STEP = "15."

#: inline code spans: `like this`
CODE_SPAN = re.compile(r"`([^`\n]+)`")

#: a span is a command the orchestrator would run when it *starts* with one of
#: these.  Anchored on purpose: ``pm_accept(..., "command": "pytest -q")`` in
#: step 19 quotes a command the validator ran, it does not run one.
FORBIDDEN_COMMAND = re.compile(
    r"^(pytest|md5sum|md5\b|python\s+-m\s+pytest|uv\s+run|git\s+diff)",
    re.IGNORECASE,
)

#: the orchestrator's one remaining check, projected to two fields
STATUS_CHECK = re.compile(r"pm_get\([^)]*fields\s*=\s*[\"']status,\s*assignee[\"']")

#: "never run them yourself" or any equivalent negation aimed at the reader
NOT_YOURSELF = re.compile(
    r"(never|not|don't|do not)\b[^.\n]{0,80}\byourself\b", re.IGNORECASE
)

#: what step 17 must say about the subagent it spawns
DISPATCH_MARKS = [
    "Agent",
    "general-purpose",
    "foreground",
    "no worktree",
    "Validator Prompt Template",
]


def _steps_16_to_19(text: str) -> str:
    """The Validation block: from the line starting ``16.`` up to ``20.``."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(FIRST_STEP)]
    ends = [n for n, line in enumerate(lines) if line.startswith(AFTER_LAST_STEP)]
    assert starts, f"no line starting with {FIRST_STEP!r} — the validation steps vanished"
    assert ends, f"no line starting with {AFTER_LAST_STEP!r} — cannot bound them"
    start = starts[0]
    end = next(n for n in ends if n > start)
    return "\n".join(lines[start:end])


def _line_starting(text: str, prefix: str) -> tuple[int, str]:
    """``(line number, line)`` of the first line starting with ``prefix``."""
    for n, line in enumerate(text.splitlines()):
        if line.startswith(prefix):
            return n, line
    raise AssertionError(f"no line starting with {prefix!r}")


def _orchestrator_commands(block: str) -> list[str]:
    """Inline code spans in ``block`` that read as a shell command to run."""
    return [
        span.strip()
        for span in CODE_SPAN.findall(block)
        if FORBIDDEN_COMMAND.match(span.strip())
    ]


# ═══ the criterion, clause by clause ════════════════════════════
# Each clause takes the whole document, so the falsification guard can mutate
# one step and push the result through the very same checks.


def _spawns_a_validator_subagent(text: str) -> bool:
    """Step 17 dispatches an Agent, foreground and worktree-free, with the prompt."""
    block = _steps_16_to_19(text)
    step_17 = [
        line for line in block.splitlines() if line.startswith("17.")
    ]
    if not step_17:
        return False
    line = step_17[0]
    return all(mark in line for mark in DISPATCH_MARKS)


def _validator_runs_after_the_worker(text: str) -> bool:
    """The validation block follows the worker dispatch in the per-task cycle."""
    try:
        worker_at, worker_line = _line_starting(text, WORKER_STEP)
        validation_at, _ = _line_starting(text, FIRST_STEP)
    except AssertionError:
        return False
    if "Agent" not in worker_line:
        return False  # step 15 is not the worker dispatch — the order proves nothing
    return worker_at < validation_at


def _orchestrator_runs_no_checks_itself(text: str) -> bool:
    """Steps 16-19 give the orchestrator no pytest/md5/diff command of its own."""
    return not _orchestrator_commands(_steps_16_to_19(text))


def _tells_the_orchestrator_not_to_run_them(text: str) -> bool:
    """The block says, in some wording, never to run the checks yourself."""
    return bool(NOT_YOURSELF.search(_steps_16_to_19(text)))


def _only_check_left_is_the_projected_status_get(text: str) -> bool:
    """The orchestrator's own check is ``pm_get(..., fields="status,assignee")``."""
    return bool(STATUS_CHECK.search(_steps_16_to_19(text)))


def _validator_prompt_carries_the_checks(text: str) -> bool:
    """The work moved rather than vanished: the fence names both diffs and tests.

    US-PM-51-8 replaced the md5 list with the branch diff — ``--stat`` for what
    changed and ``--name-only`` for the touched-path list the forbidden-file
    check is judged from — so that is what the fence must still carry.
    """
    fence = _validator_fence(text)
    return (
        "git diff --stat" in fence
        and "git diff --name-only" in fence
        and re.search(r"\btests?\b", fence, re.IGNORECASE) is not None
    )


CLAUSES = {
    "spawns a validator subagent": _spawns_a_validator_subagent,
    "validator runs after the worker": _validator_runs_after_the_worker,
    "orchestrator runs no checks itself": _orchestrator_runs_no_checks_itself,
    "tells the orchestrator not to run them": _tells_the_orchestrator_not_to_run_them,
    "only check left is the projected status get": _only_check_left_is_the_projected_status_get,
    "validator prompt carries the checks": _validator_prompt_carries_the_checks,
}

#: the clauses a step 17 that runs the checks inline must break.  The status
#: check and the validator fence live outside step 17, so they survive the
#: mutation — naming the expected set keeps the guard honest about that.
GUARD_MUST_BREAK = [
    "spawns a validator subagent",
    "orchestrator runs no checks itself",
    "tells the orchestrator not to run them",
]


@pytest.mark.parametrize("path", DOCS)
def test_validation_block_is_extractable(path):
    """Guard the slice: every assertion below is scoped to this text."""
    block = _steps_16_to_19(_text(path))
    assert "Validation" in block, "steps 16-19 are not the validation block"
    assert len(block.splitlines()) >= 4, "the validation block lost its steps"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_validation_steps_satisfy_each_clause(path, clause):
    """The acceptance criterion, one clause per case, on template and render."""
    text = _text(path)
    assert CLAUSES[clause](text), (
        f"{path.name} fails: {clause}\n\n{_steps_16_to_19(text)}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_no_orchestrator_side_test_or_md5_command(path):
    """Named separately because its failure message must show the offender."""
    found = _orchestrator_commands(_steps_16_to_19(_text(path)))
    assert not found, (
        f"{path.name} steps 16-19 tell the orchestrator to run {found} itself — "
        "that output is exactly what US-PM-48 moves into the validator"
    )


def test_rendered_template_dispatches_the_validator():
    """Rendering the template — not just reading the tracked copy — yields it."""
    rendered = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    for name, check in CLAUSES.items():
        assert check(rendered), f"rendered {ORCHESTRATE_TEMPLATE_NAME} fails: {name}"


# ─── US-PM-51-7: the worker dispatch in step 15 ──────────────────
#
# Step 15 used to read "foreground, no worktree" — the stage-only model's one
# shared checkout.  ADR-005 replaced that half: the worker is dispatched *into*
# a worktree and works on its own branch cut from the run branch, which is what
# makes one task's edits separable from another's.  The validator's dispatch in
# step 17 is deliberately unchanged and is still pinned above.

#: the Agent-tool option that gives the worker a checkout of its own
WORKTREE_ISOLATION = re.compile(r'isolation:\s*"worktree"')

#: the per-task branch, carrying both the run id and the task id
TASK_BRANCH = re.compile(r"orch/<this run>/<task-id>")

#: the run branch it is cut from — spelled out, or by the Phase 0 shorthand
RUN_BRANCH_REF = re.compile(r"run branch|`<rb>`")

#: US-PM-51-8: the accept path merges the task branch onto the run branch
FF_ONLY = re.compile(r"merge --ff-only")
NO_FF = re.compile(r"--no-ff -m \"<task-id>\"")
MERGE_ABORT = re.compile(r"merge --abort")
CONFLICT_RETRY = re.compile(r"pm_retry", re.IGNORECASE)
CONFLICT_PARKS = re.compile(r"second conflict parks", re.IGNORECASE)

#: and validation reads the branch diff, in the worker's own worktree
BRANCH_DIFF = re.compile(r"git diff --stat <run branch>\.\.\.<task branch>")
TOUCHED_PATHS = re.compile(r"git diff --name-only")
TESTS_IN_WORKTREE = re.compile(r"tests in the worktree", re.IGNORECASE)


def _accept_bullet(text: str) -> str:
    """Step 19's **Accept** bullet — where a merged branch is merged."""
    bullets = [
        line for line in text.splitlines() if line.strip().startswith("- **Accept**:")
    ]
    assert len(bullets) == 1, f"expected one **Accept** bullet, found {len(bullets)}"
    return bullets[0]


@pytest.mark.parametrize("path", DOCS)
def test_step_15_dispatches_the_worker_into_its_own_worktree(path):
    """``isolation: "worktree"`` is the isolation half of ADR-005."""
    _, line = _line_starting(_text(path), WORKER_STEP)
    assert WORKTREE_ISOLATION.search(line), (
        f'{path.name}: step 15 does not dispatch with isolation: "worktree", so '
        f"two tasks would still edit one checkout:\n\n{line}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_15_names_the_task_branch_cut_from_the_run_branch(path):
    """A worktree with no branch of its own still shares one history."""
    _, line = _line_starting(_text(path), WORKER_STEP)
    assert TASK_BRANCH.search(line), (
        f"{path.name}: step 15 names no orch/<run-id>/<task-id> branch for the "
        f"worker:\n\n{line}"
    )
    assert RUN_BRANCH_REF.search(line), (
        f"{path.name}: step 15 does not say the task branch is cut from the run "
        f"branch (`<rb>`), so it could start anywhere:\n\n{line}"
    )


def test_rendered_template_dispatches_the_worker_into_a_worktree():
    """The render, not just the tracked copy, carries the worktree dispatch."""
    _, line = _line_starting(_render_template(ORCHESTRATE_TEMPLATE_NAME), WORKER_STEP)
    assert WORKTREE_ISOLATION.search(line) and TASK_BRANCH.search(line), (
        f"rendered {ORCHESTRATE_TEMPLATE_NAME} step 15 is not a worktree "
        f"dispatch on a task branch:\n\n{line}"
    )


# ─── US-PM-51-8: merge on accept, validate from the branch diff ──
#
# The snapshot model is gone: there is no tar and no md5 list, so the accept
# path has to *do* something with the branch (merge it onto the run branch, in
# the run worktree) and the validator has to read the branch diff instead of a
# snapshot.  Both are pinned here because a skill that dispatches into
# worktrees and then never merges them produces a run branch with no work on it.


@pytest.mark.parametrize("path", DOCS)
def test_the_accept_path_merges_the_task_branch_onto_the_run_branch(path):
    """Fast-forward where it can, a merge commit titled with the task id where it cannot."""
    bullet = _accept_bullet(_text(path))
    assert FF_ONLY.search(bullet), (
        f"{path.name}: accept never fast-forwards the task branch:\n\n{bullet}"
    )
    assert NO_FF.search(bullet), (
        f"{path.name}: accept has no merge-commit fallback titled with the task "
        f"id:\n\n{bullet}"
    )
    assert "next dispatch" in bullet, (
        f"{path.name}: accept does not merge before the next dispatch, so a "
        f"dependent task would branch off work that is not there:\n\n{bullet}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_a_merge_conflict_is_one_validation_failure_then_a_park(path):
    """Abort, retry with the conflicting paths, park on the second conflict."""
    bullet = _accept_bullet(_text(path))
    assert MERGE_ABORT.search(bullet), (
        f"{path.name}: a failed merge is not aborted, so the run worktree is "
        f"left mid-merge:\n\n{bullet}"
    )
    assert CONFLICT_RETRY.search(bullet) and "evidence.files" in bullet, (
        f"{path.name}: a conflict does not become a retry carrying the "
        f"conflicting paths:\n\n{bullet}"
    )
    assert "rebase onto" in bullet, (
        f"{path.name}: the retry is not told how to clear the conflict:\n\n{bullet}"
    )
    assert CONFLICT_PARKS.search(bullet), (
        f"{path.name}: a second conflict does not park:\n\n{bullet}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_validator_reads_the_branch_diff_in_the_task_worktree(path):
    """No snapshot path, no md5 line: the branch diff *is* the boundary."""
    fence = _validator_fence(_text(path))
    assert BRANCH_DIFF.search(fence), (
        f"{path.name}: the validator prompt has no branch diff:\n\n{fence}"
    )
    assert TOUCHED_PATHS.search(fence), (
        f"{path.name}: the validator gets no touched-path list to judge the "
        f"files the task must not touch from:\n\n{fence}"
    )
    assert TESTS_IN_WORKTREE.search(fence), (
        f"{path.name}: the validator is not told to run the DoD tests in the "
        f"task's worktree, where the code actually is:\n\n{fence}"
    )
    assert not re.search(r"\bmd5", fence, re.IGNORECASE), (
        f"{path.name}: the md5 list survived the branch-diff replacement:\n\n{fence}"
    )
    assert "worktree <path>" in fence and "sha <sha>" in fence, (
        f"{path.name}: the validator is not handed the worktree and sha the "
        f"worker reported:\n\n{fence}"
    )


def test_the_clause_checks_reject_an_orchestrator_that_validates_inline():
    """Falsification guard: step 17 doing the work itself must be rejected.

    The mutation is the pre-US-PM-48 shape of the skill — the orchestrator runs
    the tests, md5s and diff in its own context — spliced into the real
    document so everything else about it stays valid.  If these checks passed on
    that, they would not be pinning the criterion at all.
    """
    text = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    _, step_17 = _line_starting(text, "17.")
    inline = (
        "17. **Validation**: run `git diff --stat` vs the step 14 snapshot, "
        "re-run `md5sum` over the files the task must not touch, and run the "
        "tests the DoD names with `pytest -q`; read the output and judge it."
    )
    mutated = text.replace(step_17, inline)
    assert mutated != text, "the mutation did not apply — guard is inconclusive"

    failed = [name for name, check in CLAUSES.items() if not check(mutated)]
    assert sorted(failed) == sorted(GUARD_MUST_BREAK), (
        "an orchestrator that validates inline was not rejected as expected; "
        f"failed={sorted(failed)} expected={sorted(GUARD_MUST_BREAK)}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
