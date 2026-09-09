"""US-PM-49-2 — the worker prompt must carry no context excerpt and a capped report.

Story US-PM-49 is about the bytes the orchestrator itself spends.  Two of them
sit either side of one dispatch: the prompt it sends and the report it gets
back.  Measured across the Kura runs, worker prompts averaged 6.2 KB — mostly
the inline 2000-char project-context excerpt, re-pasted per dispatch even
though ``pm_grab`` already returns the task and story the worker acts on — and
worker reports averaged 5.6 KB of free-form prose, code and log tails.  So the
acceptance criterion pinned here is —

    "The worker prompt template carries no inline project context excerpt and
    caps the worker report at a fixed shape of about 1500 characters"

— and US-PM-49-7 made the change.  This module holds it, clause by clause, on
the ``Worker Prompt Template`` fence of the pm-orchestrate skill.

Three documents are checked for the fence: the Jinja template (source of
truth), the tracked rendered ``.claude/skills/pm-orchestrate/SKILL.md`` (what
an orchestrating agent actually loads) and a live render of the template (so a
template edit that never survives the renderer is caught even before the
byte-for-byte equality test in ``test_orchestrate_skill_size.py`` fires).

The report half of the criterion is checked on ``/pm-do`` as well.  The fence
tells the worker to run that skill, and step 10 of the skill is what the worker
is actually following when it writes its report; a cap named in only one of the
two documents is a cap the worker can be talked out of.

The last two tests are falsification guards — a fat prompt with a pasted
context excerpt, and a free-form "report however you like" instruction, are
pushed through the same clause tables and must fail every one.  A checklist
that never fires is not evidence.

Nothing here writes: the criterion is a property of templates this task must
not modify.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_skill_guidance_tools import PM_DO_DOCS, _worker_fence
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
)
from tests.test_skill_verdict_verbs import ORCHESTRATE_TEMPLATE_NAME, _text

PM_DO_TEMPLATE_NAME = "skill_pm_do.md.j2"

#: the report's ceiling, in characters — the criterion's own number
REPORT_MAX_CHARS = 1500

#: ``pm_context(...)`` — the call that fetches the project brief.  The worker
#: needs the docs sometimes; it is told so in /pm-do, not in every prompt.
PM_CONTEXT_CALL = re.compile(r"\bpm_context\(")

#: words that only appear in a prompt that pastes the project brief inline
EXCERPT_MARKERS = [
    "project context",
    "architecture",
    "tech stack",
    "vision",
    ".project/",
]

#: ``under 1500 chars`` and the ways of writing the same bound
CAP = re.compile(
    r"(?:under|below|within|at most|no more than|max(?:imum)?(?:\s+of)?|<=?)\s*"
    rf"{REPORT_MAX_CHARS}\s*(?:char|character)",
    re.IGNORECASE,
)

#: the fixed shape, in the order the criterion fixes it.  Each entry is
#: (name, pattern); the patterns are matched against the lowercased report
#: clause and their first offsets must come out strictly increasing.
SHAPE = [
    ("files changed, paths only", re.compile(r"files changed\s*\(paths only\)")),
    ("tests as `command -> pass|fail (n passed)`", re.compile(
        r"`command\s*->\s*pass\|fail\s*\(n passed\)`"
    )),
    ("dod met", re.compile(r"dod met")),
    ("dod unmet", re.compile(r"dod unmet")),
    ("blockers", re.compile(r"blockers")),
]


def _report_clause(text: str) -> str:
    """The ``Report back ...`` instruction, as one whitespace-normalised line.

    Runs from ``Report back`` to the end of its paragraph, so a clause that
    wraps over several lines (the fence) and one written on a single line
    (/pm-do step 10) normalise to the same string.
    """
    match = re.search(r"Report back\b", text)
    assert match, "no 'Report back' instruction — the report shape is missing"
    rest = text[match.start() :]
    paragraph = re.split(
        r"\n\s*\n|\n(?=\s*(?:\d+[a-z]?\.\s|#{1,6} |[-*] ))", rest
    )[0]
    return " ".join(paragraph.split())


# ─── clause tables ───────────────────────────────────────────────
#
# Split in two because the report clauses are asserted twice: on the worker
# prompt fence and on /pm-do.  Both tables are iterated by the tests *and* by
# the falsification guards, so a clause cannot be checked in one and quietly
# dropped from the other.


def _bounds_the_report(clause: str) -> bool:
    return bool(CAP.search(clause))


def _forbids_code_and_logs(clause: str) -> bool:
    low = clause.lower()
    return "no code or logs" in low or ("no code" in low and "log" in low)


def _names_the_shape(clause: str) -> bool:
    low = clause.lower()
    return all(pattern.search(low) for _, pattern in SHAPE)


def _orders_the_shape(clause: str) -> bool:
    low = clause.lower()
    offsets = []
    for _, pattern in SHAPE:
        found = pattern.search(low)
        if not found:
            return False
        offsets.append(found.start())
    return offsets == sorted(offsets) and len(set(offsets)) == len(offsets)


REPORT_CLAUSES = {
    f"caps the report at {REPORT_MAX_CHARS} chars": _bounds_the_report,
    "says no code or logs": _forbids_code_and_logs,
    "names every part of the fixed shape": _names_the_shape,
    "names them in the fixed order": _orders_the_shape,
}


def _carries_no_project_context_line(fence: str) -> bool:
    return not re.search(r"project context\s*:", fence, re.IGNORECASE)


def _pastes_no_excerpt(fence: str) -> bool:
    low = fence.lower()
    return not any(marker in low for marker in EXCERPT_MARKERS)


def _names_no_pm_context_call(fence: str) -> bool:
    return not PM_CONTEXT_CALL.search(fence)


FENCE_CLAUSES = {
    "carries no 'Project context:' line": _carries_no_project_context_line,
    "pastes no inline project brief excerpt": _pastes_no_excerpt,
    "names no pm_context() call": _names_no_pm_context_call,
}


# ─── the documents ───────────────────────────────────────────────

ORCHESTRATE_SOURCES = {
    "template": lambda: _text(ORCHESTRATE_TEMPLATE),
    "rendered": lambda: _text(ORCHESTRATE_SKILL),
    "live-render": lambda: _render_template(ORCHESTRATE_TEMPLATE_NAME),
}

PM_DO_SOURCES = {
    "template": lambda: _text(PM_DO_DOCS[0]),
    "rendered": lambda: _text(PM_DO_DOCS[1]),
    "live-render": lambda: _render_template(PM_DO_TEMPLATE_NAME),
}


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
def test_worker_prompt_fence_is_extractable(source):
    """Guard the slice: every assertion below is scoped to this text."""
    fence = _worker_fence(ORCHESTRATE_SOURCES[source]())
    assert "template not found" not in fence, "the template failed to render"
    assert "/pm-do" in fence, "the fence under the heading is not the worker prompt"
    assert len(fence.splitlines()) >= 10, "the worker prompt lost its body"


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
@pytest.mark.parametrize("clause", list(FENCE_CLAUSES), ids=list(FENCE_CLAUSES))
def test_worker_prompt_carries_no_inline_context(source, clause):
    """First half of the criterion, one clause per case, on all three documents."""
    fence = _worker_fence(ORCHESTRATE_SOURCES[source]())
    assert FENCE_CLAUSES[clause](fence), f"worker prompt fails: {clause}\n\n{fence}"


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
@pytest.mark.parametrize("clause", list(REPORT_CLAUSES), ids=list(REPORT_CLAUSES))
def test_worker_prompt_caps_the_report_at_a_fixed_shape(source, clause):
    """Second half of the criterion, on the prompt the orchestrator sends."""
    clause_text = _report_clause(_worker_fence(ORCHESTRATE_SOURCES[source]()))
    assert REPORT_CLAUSES[clause](clause_text), (
        f"worker prompt report clause fails: {clause}\n\n{clause_text}"
    )


@pytest.mark.parametrize("source", list(PM_DO_SOURCES), ids=list(PM_DO_SOURCES))
@pytest.mark.parametrize("clause", list(REPORT_CLAUSES), ids=list(REPORT_CLAUSES))
def test_pm_do_states_the_same_report_shape(source, clause):
    """The skill the worker actually runs must state the same cap and shape.

    The fence tells the worker to run ``/pm-do``; if only one of the two names
    the bound, the other is the one the worker follows.
    """
    clause_text = _report_clause(PM_DO_SOURCES[source]())
    assert REPORT_CLAUSES[clause](clause_text), (
        f"/pm-do report clause fails: {clause}\n\n{clause_text}"
    )


def test_the_two_documents_state_one_shape_not_two():
    """Same cap, same parts, same order — a drift between them is a second shape."""
    fence_clause = _report_clause(_worker_fence(_render_template(ORCHESTRATE_TEMPLATE_NAME)))
    do_clause = _report_clause(_render_template(PM_DO_TEMPLATE_NAME))

    def _shape(clause: str) -> list[str]:
        low = clause.lower()
        return [name for name, pattern in SHAPE if pattern.search(low)]

    assert _shape(fence_clause) == _shape(do_clause) == [name for name, _ in SHAPE]
    assert CAP.search(fence_clause).group().lower().split() == (
        CAP.search(do_clause).group().lower().split()
    ), f"different caps:\n{fence_clause}\n{do_clause}"


# ─── US-PM-51-7: the branch the worker commits ───────────────────
#
# ADR-005 ends the fence with a commit: the worker cuts its own branch inside
# the worktree it was dispatched into, stages code paths only — never the
# store — commits once under the task id, and reports the branch and sha the
# orchestrator merges on accept.  The rule the commit replaced ("No git
# commit/push") is retargeted here rather than deleted: pushing is still
# forbidden, committing is now the worker's last act.

#: the branch the worker cuts from the run branch, first thing
SWITCH_TO_TASK_BRANCH = re.compile(
    r"git switch -c orch/<this run>/<task-id> orch/<this run>"
)

#: code paths only — an ``-A`` over the whole tree would sweep in .project
STAGES_CODE_ONLY = re.compile(r"git add -A -- <code paths>")

#: and says so in as many words
NEVER_THE_STORE = re.compile(r"never \.project", re.IGNORECASE)

#: exactly one commit, titled with the task id
ONE_COMMIT = re.compile(r"one commit titled `<task-id>", re.IGNORECASE)

#: pushing stays forbidden on both spellings
NO_PUSH = re.compile(r"no git push[^\n]*pm_commit[^\n]*pm_push", re.IGNORECASE)

#: what the report gains, so the orchestrator can merge it and the validator
#: can find the code (US-PM-51-8 added the worktree path beside branch and sha)
BRANCH_AND_SHA = re.compile(r"branch, sha and worktree path", re.IGNORECASE)

#: the worktree outlives the worker: the validator runs the DoD tests in it
LEAVES_THE_WORKTREE = re.compile(r"worktree left in place", re.IGNORECASE)

#: a retry switches to the branch it already has rather than re-creating it
RETRY_SWITCH = re.compile(r"retry: plain\s*\n?`?git switch`?", re.IGNORECASE)

#: and clears a merge conflict by rebasing onto the run branch
REBASE_ON_CONFLICT = re.compile(r"git rebase orch/<this run>")

#: a retry works the branch it already has
SAME_BRANCH = re.compile(r"same branch", re.IGNORECASE)

BRANCH_CLAUSES = {
    "cuts the task branch off the run branch": lambda f: bool(
        SWITCH_TO_TASK_BRANCH.search(f)
    ),
    "stages code paths only": lambda f: bool(STAGES_CODE_ONLY.search(f)),
    "never stages the store": lambda f: bool(NEVER_THE_STORE.search(f)),
    "makes one commit titled with the task id": lambda f: bool(ONE_COMMIT.search(f)),
    "still forbids pushing": lambda f: bool(NO_PUSH.search(f)),
    "a retry stays on the same branch": lambda f: bool(SAME_BRANCH.search(f)),
    "a retry switches to it rather than re-creating it": lambda f: bool(
        RETRY_SWITCH.search(f)
    ),
    "a merge conflict is rebased onto the run branch": lambda f: bool(
        REBASE_ON_CONFLICT.search(f)
    ),
    "leaves its worktree in place": lambda f: bool(LEAVES_THE_WORKTREE.search(f)),
}


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
@pytest.mark.parametrize("clause", list(BRANCH_CLAUSES), ids=list(BRANCH_CLAUSES))
def test_worker_prompt_commits_its_own_branch(source, clause):
    """ADR-005's commit-on-branch half, one clause per case, on all three documents."""
    fence = _worker_fence(ORCHESTRATE_SOURCES[source]())
    assert BRANCH_CLAUSES[clause](fence), (
        f"worker prompt fails: {clause}\n\n{fence}"
    )


@pytest.mark.parametrize("source", list(ORCHESTRATE_SOURCES), ids=list(ORCHESTRATE_SOURCES))
def test_worker_report_names_the_branch_and_the_sha(source):
    """The orchestrator merges what the worker names; an unnamed branch is lost."""
    clause = _report_clause(_worker_fence(ORCHESTRATE_SOURCES[source]()))
    assert BRANCH_AND_SHA.search(clause), (
        "the fixed report shape has no branch-and-sha item, so the accept path "
        f"has no branch to merge:\n\n{clause}"
    )


def test_the_branch_clauses_reject_the_stage_only_worker_prompt():
    """Falsification guard: the pre-ADR-005 fence must fail every branch clause."""
    stage_only = (
        "You are executing a single ProjectMan task, already claimed for you.\n"
        "Rules:\n"
        "- No git commit/push, pm_commit/pm_push.\n"
        "Report back under 1500 chars: files changed (paths only); blockers.\n"
    )
    failed = [name for name, check in BRANCH_CLAUSES.items() if not check(stage_only)]
    assert failed == list(BRANCH_CLAUSES), (
        "a stage-only worker prompt passed these clauses: "
        f"{[n for n in BRANCH_CLAUSES if n not in failed]}"
    )


# ─── US-PM-51-9: the rules the worker follows inside the worktree ───
#
# The fence is only half of what a dispatched worker reads: it is told to run
# ``/pm-do``, and that skill is the document open in front of it while it
# works.  ADR-005 put the worker in a git worktree on ``orch/<run>/<task-id>``
# with the ``.project`` store left behind in the primary checkout, so the
# skill has to say four things the stage-only version had no reason to say:
# where the worker is, that it still may not move (no checkout/restore/stash/
# reset/clean, no branch switching), that a commit happens only when the
# dispatch prompt asks for one and covers code paths only, and that the store
# is reached through the pm tools rather than through a ``.project`` directory
# that is not there.  A worker told none of this in the skill it is following
# would learn it only from the prompt, and a retry prompt is the shortest text
# in the run.
#
# Clauses are matched against the whole /pm-do document, on all three sources
# (template, tracked rendered copy, live render), same as the report shape.

#: the worker may be somewhere other than the primary checkout
CWD_MAY_BE_A_WORKTREE = re.compile(r"cwd[^.\n]{0,40}worktree", re.IGNORECASE)

#: and that somewhere is the task branch the orchestrator merges
NAMES_THE_TASK_BRANCH = re.compile(r"orch/<[^>\n]+>/<task-id>")

#: the five commands that move a tree under a worker's feet
FORBIDDEN_GIT = ("checkout", "restore", "stash", "reset", "clean")

#: "Never `git checkout`, `restore`, ... ; never switch branches"
NO_BRANCH_SWITCH = re.compile(
    r"(?:never|do not|don't|no)\s+switch(?:ing)?\s+branch", re.IGNORECASE
)

#: committing is not the worker's default: the dispatch prompt asks for it
COMMIT_ONLY_WHEN_TOLD = re.compile(
    r"commit only when[^.\n]{0,60}(?:dispatch|prompt)", re.IGNORECASE
)

#: and it never reaches the store, which is gitignored on main anyway
COMMIT_CODE_ONLY = re.compile(
    r"code paths?[^.\n]{0,40}never\s+`?\.project", re.IGNORECASE
)

#: the store lives in the primary checkout; the pm tools are the only route
STORE_VIA_PM_TOOLS = re.compile(
    r"store is reached through[^.\n]{0,40}`?pm_\*`?[^.\n]{0,60}"
    r"never\s+(?:a|through a)\s*`?\.project`?\s*directory",
    re.IGNORECASE,
)


def _bans_every_forbidden_git_command(text: str) -> bool:
    low = text.lower()
    return all(f"`{command}`" in low or f"git {command}" in low for command in FORBIDDEN_GIT)


WORKTREE_CLAUSES = {
    "says the worker's cwd may be a worktree": lambda t: bool(
        CWD_MAY_BE_A_WORKTREE.search(t)
    ),
    "names the per-task branch it sits on": lambda t: bool(
        NAMES_THE_TASK_BRANCH.search(t)
    ),
    "keeps the checkout/restore/stash/reset/clean bans": _bans_every_forbidden_git_command,
    "forbids switching branches": lambda t: bool(NO_BRANCH_SWITCH.search(t)),
    "commits only when the dispatch prompt says so": lambda t: bool(
        COMMIT_ONLY_WHEN_TOLD.search(t)
    ),
    "commits code paths only, never the store": lambda t: bool(
        COMMIT_CODE_ONLY.search(t)
    ),
    "reaches the store through the pm tools, not a .project directory": lambda t: bool(
        STORE_VIA_PM_TOOLS.search(t)
    ),
}


@pytest.mark.parametrize("source", list(PM_DO_SOURCES), ids=list(PM_DO_SOURCES))
@pytest.mark.parametrize("clause", list(WORKTREE_CLAUSES), ids=list(WORKTREE_CLAUSES))
def test_pm_do_states_the_worktree_rules(source, clause):
    """ADR-005's worker rules, one clause per case, on the skill the worker runs."""
    text = PM_DO_SOURCES[source]()
    assert WORKTREE_CLAUSES[clause](text), (
        f"/pm-do worker rules fail: {clause}\n\n{text}"
    )


def test_pm_do_git_bans_cover_the_worker_prompt_fence():
    """The two documents may not disagree about what a worker must not run.

    The fence lists its bans in one line and ``/pm-do`` in another; a command
    forbidden by the prompt but not by the skill is one the worker can talk
    itself into once the prompt has scrolled away.
    """
    fence = _worker_fence(_render_template(ORCHESTRATE_TEMPLATE_NAME)).lower()
    do_text = _render_template(PM_DO_TEMPLATE_NAME).lower()
    banned_in_fence = {c for c in FORBIDDEN_GIT if f"git {c}" in fence}
    assert banned_in_fence, "the worker prompt lists no forbidden git commands"
    missing = {
        c for c in banned_in_fence if not (f"`{c}`" in do_text or f"git {c}" in do_text)
    }
    assert not missing, (
        f"the worker prompt forbids {sorted(missing)} but /pm-do does not"
    )


def test_the_worktree_clauses_reject_the_stage_only_pm_do():
    """Falsification guard: the pre-ADR-005 skill must fail every worktree clause."""
    stage_only = (
        "# /pm-do — Execute Task\n\n"
        "1. Call `pm_grab(task_id)` to claim the task.\n"
        "5. Verify with evidence, not assertion.\n"
        "10. Report back under 1500 chars, no code or logs.\n"
    )
    failed = [name for name, check in WORKTREE_CLAUSES.items() if not check(stage_only)]
    assert failed == list(WORKTREE_CLAUSES), (
        "a stage-only /pm-do passed these clauses: "
        f"{[n for n in WORKTREE_CLAUSES if n not in failed]}"
    )


def test_the_fence_checks_reject_a_prompt_that_pastes_the_project_brief():
    """Falsification guard: the pre-US-PM-49-7 prompt must fail every fence clause."""
    fat = (
        "You are executing a single ProjectMan task, already claimed for you.\n"
        "Project context: ProjectMan is a Python package exposing an MCP server.\n"
        "Architecture: skills live as Jinja templates rendered into .project/ ...\n"
        "Tech stack: Python 3.11, FastMCP. Vision: keep agents on the rails.\n"
        "Widen it yourself with pm_context(max_doc_chars=2000) if you need more.\n"
    )
    failed = [name for name, check in FENCE_CLAUSES.items() if not check(fat)]
    assert failed == list(FENCE_CLAUSES), (
        "a prompt pasting the project brief passed these clauses: "
        f"{[n for n in FENCE_CLAUSES if n not in failed]}"
    )


def test_the_report_checks_reject_a_free_form_report_instruction():
    """Falsification guard: an unbounded, shapeless report must fail every clause."""
    free_form = (
        "Report back in whatever form is clearest: what you changed, the test\n"
        "output, and anything else worth knowing.\n"
    )
    clause = _report_clause(free_form)
    failed = [name for name, check in REPORT_CLAUSES.items() if not check(clause)]
    assert failed == list(REPORT_CLAUSES), (
        "a free-form report instruction passed these clauses: "
        f"{[n for n in REPORT_CLAUSES if n not in failed]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
