"""US-PM-49-3 — Phase 1 must warn about a very dirty working tree.

Story US-PM-49 is about the bytes the orchestrator itself spends, and the whole
modified list is walked more than once in a run: every dispatch reads it and
step 23 walks it again for the store side of the report.  (Until ADR-005 the
per-dispatch walk was step 14's ``git status --short`` plus a ``tar`` with
md5s; the branch diff replaced that pair, so the report walk is what is left.)
On a tree with a thousand dirty entries
that list alone measured 55 KB per dispatch on the Kura runs — a per-dispatch
cost the orchestrator pays silently, over and over, for a condition a single
commit would clear.  So the acceptance criterion pinned here is —

    "The orchestrate skill Phase 1 warns when the working tree has more than
    200 dirty entries and names commit or clean as the fix"

— and US-PM-49-8 made the change, in Phase 1 step 4.  This module holds it,
clause by clause, on that step.

Three documents are checked: the Jinja template (source of truth), the tracked
rendered ``.claude/skills/pm-orchestrate/SKILL.md`` (what an orchestrating
agent actually loads) and a live render of the template, so a template edit
that never survives the renderer is caught even before the byte-for-byte
equality test in ``test_orchestrate_skill_size.py`` fires.

One test looks past step 4: the warning earns its threshold only if the steps
it names really are the walks it prices, so those step numbers are resolved and
checked for the commands they are said to walk.  A second looks for the
snapshot model ADR-005 removed and requires it to be gone.

The last two tests are falsification guards — the pre-US-PM-49-8 step 4, which
said nothing at all, and a vague "the tree looks dirty, be careful" note — are
pushed through the same clause table and must fail every one.  A checklist
that never fires is not evidence.

Nothing here writes: the criterion is a property of templates this task must
not modify.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
)
from tests.test_skill_verdict_verbs import ORCHESTRATE_TEMPLATE_NAME, _text

#: the criterion's own number — entries in ``git status --short``
DIRTY_MAX_ENTRIES = 200

#: ``Over **200** entries`` and the ways of writing the same bound.  Markdown
#: emphasis around the number is allowed; a bare "200" is not a threshold.
THRESHOLD = re.compile(
    r"(?:over|above|beyond|more than|greater than|exceed(?:s|ing)?|past|>\s*=?)\s*"
    rf"[*_`]*{DIRTY_MAX_ENTRIES}\b",
    re.IGNORECASE,
)

#: the unit the threshold counts — entries of the dirty list, not seconds or KB
ENTRIES = re.compile(
    rf"[*_`]*{DIRTY_MAX_ENTRIES}[*_`]*\s*(?:dirty\s+|changed\s+|modified\s+)?"
    r"(?:entries|entry|lines|files|paths)",
    re.IGNORECASE,
)

#: the warning itself
WARN = re.compile(r"\bwarn(?:s|ing|ed)?\b|\bcaution\b", re.IGNORECASE)

#: what the warning is *about*: the list gets walked again and again
WALKS = re.compile(
    r"\bwalks?\b|\bwalking\b|\btraverses?\b|\bre-?reads?\b|\bre-?scans?\b|\bscans?\b",
    re.IGNORECASE,
)
EACH_DISPATCH = re.compile(r"\b(?:each|every|per)\s+dispatch\b", re.IGNORECASE)

#: the fix the criterion names
COMMIT = re.compile(r"\bcommit(?:s|ted|ting)?\b", re.IGNORECASE)
CLEAN = re.compile(r"\bclean(?:s|ed|ing|up)?\b|\bstash\b", re.IGNORECASE)

#: ``--auto`` does not turn the warning into a stop
AUTO = re.compile(r"`?--auto`?", re.IGNORECASE)
CONTINUES = re.compile(
    r"\bcontinues?\b|\bproceeds?\b|\bcarries on\b|\bruns? on\b|\bdoes not stop\b"
    r"|\bnever stops\b|\bno stop\b",
    re.IGNORECASE,
)

#: and it is carried into the Phase 4 report
REPORTS_IN_PHASE_4 = re.compile(
    r"\breports?(?:ed|s|\sit)?\b[^.;]{0,40}\bphase\s*4\b"
    r"|\bphase\s*4\b[^.;]{0,40}\breports?\b",
    re.IGNORECASE,
)

#: the commands the step named by the warning must actually run.  Until
#: US-PM-51-8 the warning also named step 14's ``tar`` + md5 snapshot; ADR-005
#: replaced that with the branch diff, so the report walk is what is left.
DIFF_COMMANDS = [re.compile(r"git diff --stat"), re.compile(r"git status --short")]

#: what no step may do any more — the snapshot model the branch diff replaced
GONE_COMMANDS = [re.compile(r"\btar\b"), re.compile(r"\bmd5")]


# ─── the slice ───────────────────────────────────────────────────


def _phase_1(text: str) -> str:
    """The ``## Phase 1`` section, up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("## Phase 1")]
    assert starts, "no '## Phase 1' section — the pre-flight vanished"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _step(text: str, number: int) -> str:
    """Numbered step ``number``, from its own line to the next numbered line.

    Continuation lines (sub-bullets, wrapped prose) are kept; the next step's
    line and any later heading end the slice.
    """
    lines = text.splitlines()
    starts = [
        n
        for n, line in enumerate(lines)
        if re.match(rf"^{number}(?:-\d+)?\.\s", line)
    ]
    assert starts, f"no line starting with '{number}.' — step {number} vanished"
    start = starts[0]
    end = next(
        (
            n
            for n in range(start + 1, len(lines))
            if re.match(r"^\d+(?:-\d+)?\.\s", lines[n]) or lines[n].startswith("## ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _dirty_tree_step(text: str) -> str:
    """Phase 1's ``git status --short`` step — the one the criterion is about."""
    section = _phase_1(text)
    step = _step(section, 4)
    assert "git status --short" in step, (
        "Phase 1 step 4 no longer runs `git status --short` — "
        f"the dirty-tree slice is wrong:\n\n{step}"
    )
    return step


def _named_steps(step: str) -> list[int]:
    """The step numbers the warning points at, e.g. ``steps 14 and 23``."""
    match = re.search(r"steps?\s+([\d,\sand]+)", step, re.IGNORECASE)
    if not match:
        return []
    return [int(n) for n in re.findall(r"\d+", match.group(1))]


# ─── clause table ────────────────────────────────────────────────
#
# Iterated by the tests *and* by the falsification guards, so a clause cannot
# be checked in one place and quietly dropped from the other.


def _names_the_threshold(step: str) -> bool:
    return bool(THRESHOLD.search(step) and ENTRIES.search(step))


def _warns_about_the_repeated_walk(step: str) -> bool:
    return bool(WARN.search(step) and WALKS.search(step) and EACH_DISPATCH.search(step))


def _names_commit_or_clean_as_the_fix(step: str) -> bool:
    return bool(COMMIT.search(step) and CLEAN.search(step))


def _auto_continues_and_reports(step: str) -> bool:
    return bool(
        AUTO.search(step) and CONTINUES.search(step) and REPORTS_IN_PHASE_4.search(step)
    )


CLAUSES = {
    f"names the {DIRTY_MAX_ENTRIES}-entry threshold": _names_the_threshold,
    "warns the list is walked on every dispatch": _warns_about_the_repeated_walk,
    "names committing or cleaning as the fix": _names_commit_or_clean_as_the_fix,
    "under --auto continues and reports it in Phase 4": _auto_continues_and_reports,
}


# ─── the documents ───────────────────────────────────────────────

SOURCES = {
    "template": lambda: _text(ORCHESTRATE_TEMPLATE),
    "rendered": lambda: _text(ORCHESTRATE_SKILL),
    "live-render": lambda: _render_template(ORCHESTRATE_TEMPLATE_NAME),
}


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_dirty_tree_step_is_extractable(source):
    """Guard the slice: every assertion below is scoped to this text."""
    text = SOURCES[source]()
    assert "template not found" not in text, "the template failed to render"
    step = _dirty_tree_step(text)
    assert step.startswith("4."), "the slice is not Phase 1 step 4"
    assert len(step) > 60, "step 4 lost its body — a bare command carries no warning"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_phase_1_warns_on_a_very_dirty_tree(source, clause):
    """The acceptance criterion, one clause per case, on all three documents."""
    step = _dirty_tree_step(SOURCES[source]())
    assert CLAUSES[clause](step), f"Phase 1 step 4 fails: {clause}\n\n{step}"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_the_step_the_warning_names_is_the_one_that_walks_the_list(source):
    """The warning's cost claim must point at the step that pays it.

    ``step 23`` is only a reason to commit if step 23 really is the report walk
    of the modified list; a renumber that leaves the warning pointing elsewhere
    makes it noise.  Before US-PM-51-8 the warning also named step 14, whose
    ``tar`` + md5 snapshot ADR-005 replaced with the branch diff.
    """
    text = SOURCES[source]()
    step = _dirty_tree_step(text)
    numbers = _named_steps(step)
    assert numbers, f"the warning names no walking step:\n\n{step}"

    bodies = [_step(text, number) for number in numbers]
    joined = "\n".join(bodies)
    for pattern in DIFF_COMMANDS:
        assert pattern.search(joined), (
            f"no step named by the warning runs {pattern.pattern!r}:\n\n{joined}"
        )
    assert any(
        all(pattern.search(body) for pattern in DIFF_COMMANDS) for body in bodies
    ), f"none of the named steps is the report walk:\n\n{joined}"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_no_step_snapshots_the_tree_any_more(source):
    """ADR-005: the branch diff replaced the tar snapshot and the md5 list.

    Kept next to the warning because the two are one story — the per-dispatch
    walk the warning was priced on is exactly what the branch model removed.
    """
    text = SOURCES[source]()
    dispatch_steps = "\n".join(_step(text, number) for number in (14, 17, 23))
    for pattern in GONE_COMMANDS:
        assert not pattern.search(dispatch_steps), (
            f"the snapshot model survived in steps 14/17/23: "
            f"{pattern.pattern!r}\n\n{dispatch_steps}"
        )


# ─── US-PM-51-7: Phase 0 cuts the run branch ─────────────────────
#
# ADR-005 took the run off the shared checkout: ``orch/<run-id>`` is cut from
# ``HEAD`` before any dispatch, and every task branch starts from it.  That is
# only a known starting point if the tree is clean outside the store, so unlike
# step 4's warning this gate *stops* the run and reports what is dirty.

#: the branch the run's task branches are cut from
RUN_BRANCH = re.compile(r"git branch\s+`?orch/<this run>`?\s+HEAD")

#: an outright stop, not a warning
STOPS_THE_RUN = re.compile(r"stops? the run", re.IGNORECASE)

#: and it says which paths it is dirty *outside*
STORE_PATH = re.compile(r"`?\.project/?`?")

#: the list the operator needs to clean it
DIRTY_LIST = re.compile(r"dirty list", re.IGNORECASE)


def _phase_0(text: str) -> str:
    """The ``## Phase 0`` section, up to ``## Phase 1``."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("## Phase 0")]
    assert starts, "no '## Phase 0' section — the run branch has nowhere to be cut"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_phase_0_cuts_the_run_branch_from_head(source):
    """Without ``orch/<run-id>`` there is nothing for a task branch to start from."""
    phase_0 = _phase_0(SOURCES[source]())
    assert RUN_BRANCH.search(phase_0), (
        "Phase 0 does not create the run branch from HEAD, so ADR-005's trunk "
        f"never exists:\n\n{phase_0}"
    )


#: the worktree the run branch is checked out in, so merges never move the
#: primary checkout off the branch the user left it on (US-PM-51-8)
RUN_WORKTREE = re.compile(r"git worktree add\s+\S*orch-<this run>")


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_phase_0_adds_the_run_worktree_the_merges_happen_in(source):
    """A merge needs the run branch checked out somewhere that is not the user's tree."""
    phase_0 = _phase_0(SOURCES[source]())
    assert RUN_WORKTREE.search(phase_0), (
        "Phase 0 adds no run worktree, so the accept path has nowhere to merge "
        f"the task branch:\n\n{phase_0}"
    )
    assert "merge" in phase_0, (
        f"Phase 0 does not say what the run worktree is for:\n\n{phase_0}"
    )


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_phase_0_stops_the_run_when_the_tree_is_dirty_outside_the_store(source):
    """A branch cut from a dirty HEAD carries edits nobody attributed to a task."""
    phase_0 = _phase_0(SOURCES[source]())
    assert "git status --short" in phase_0, (
        f"Phase 0 never looks at the working tree:\n\n{phase_0}"
    )
    assert STORE_PATH.search(phase_0), (
        f"Phase 0's dirty gate does not exempt the store:\n\n{phase_0}"
    )
    assert STOPS_THE_RUN.search(phase_0), (
        "a dirty tree outside the store must stop the run, not warn like step 4:"
        f"\n\n{phase_0}"
    )
    assert DIRTY_LIST.search(phase_0), (
        f"the stop does not report what is dirty, so it cannot be fixed:\n\n{phase_0}"
    )


def test_the_clause_checks_reject_the_step_before_the_warning():
    """Falsification guard: the pre-US-PM-49-8 step 4 must fail every clause."""
    before = "4. `git status --short` — keep the pre-existing modified list."
    failed = [name for name, check in CLAUSES.items() if not check(before)]
    assert failed == list(CLAUSES), (
        "the un-warned step 4 passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


def test_the_clause_checks_reject_a_vague_dirty_tree_note():
    """Falsification guard: a warning with no number, no cost and no fix fails.

    Without this, the clauses could be satisfied by prose that merely sounds
    careful, and the criterion — a *threshold*, a *reason* and a *fix* — would
    go unpinned.
    """
    vague = (
        "4. `git status --short` — keep the pre-existing modified list.  A large\n"
        "   dirty tree makes the run noisier, so keep an eye on it.\n"
    )
    failed = [name for name, check in CLAUSES.items() if not check(vague)]
    assert failed == list(CLAUSES), (
        "a vague dirty-tree note passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
