"""US-PM-51-1 — ADR-005 records the move to per-task worktrees with commit-on-branch.

US-PM-51's acceptance criterion: "DECISIONS.md carries ADR-005 revising the
stage-only model to per-task worktrees with commit-on-branch and no push".

ADR-005 was written by US-PM-51-6; this module is what keeps it written. The
isolation model is the one rule in the orchestration loop that a later edit
could quietly loosen — dropping "nothing is pushed", or letting a run commit
the ``.project`` store — and the cost of that regression is paid outside the
test suite, in someone's repository. So the checks are against the real
artefacts, in the shape ``test_docs_after_subtraction.py`` already uses for
ADR-003 and ADR-004:

1. **ADR-005 exists, is dated 2026-09-09, and sits above ADR-004**, keeping the
   file's stated newest-first order.
2. **Its Decision names all five moving parts** — the per-task branch
   ``orch/<run-id>/<task-id>``, the run branch ``orch/<run-id>``, the worker
   committing on its own branch, nothing being pushed, and the store never
   being committed by a run.
3. **Its Consequences record the four things that follow** — the run branch is
   the product to review and merge; a dependent task waits for that merge; the
   worktree has no ``.project`` so store access goes through the MCP tools
   against the primary checkout; a parked task leaves its branch behind.
4. **It says what it revises and what it does not** — the stage-only model in
   ``orchestrate-design.md`` is superseded, ADR-004 stays in force.
5. **``docs/reference/orchestrate-design.md`` has an "Isolation model" section
   pointing at ADR-005**, and no longer heads a section "Stage-only model".
6. **``docs/reference/skills.md`` describes the model to the reader who never
   opens the design doc** — the ``/pm-orchestrate`` section names the run
   branch, the worktree dispatch, the merge on accept and the branch listing in
   the final report, and no longer says changes are staged and never committed.

Assertions are on stable phrases — branch patterns, tool names, the nouns the
decision turns on — never whole sentences, so the record can be reworded
without the guard rotting.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS = REPO_ROOT / ".project" / "DECISIONS.md"
ORCHESTRATE_DESIGN = REPO_ROOT / "docs" / "reference" / "orchestrate-design.md"
SKILLS_DOC = REPO_ROOT / "docs" / "reference" / "skills.md"

#: The ADR-005 heading, pinned in full: ``orchestrate-design.md`` links into
#: this record, and the date is part of the criterion.
ADR5_HEADING = (
    "## ADR-005: Each orchestrated task runs in its own worktree and commits "
    "on its own branch (2026-09-09)"
)


def _decisions_text() -> str:
    assert DECISIONS.exists(), f"{DECISIONS} is missing"
    return DECISIONS.read_text(encoding="utf-8")


def _adr_section(text: str, heading: str) -> str:
    """The body of one ADR: everything from its heading to the next ``## ADR-``."""
    assert heading in text, (
        f"`.project/DECISIONS.md` has no heading reading exactly:\n  {heading}"
    )
    start = text.index(heading) + len(heading)
    following = re.search(r"^##\s+ADR-", text[start:], re.MULTILINE)
    return text[start : start + following.start()] if following else text[start:]


def _says(text: str, phrase: str) -> bool:
    """True if ``text`` contains ``phrase``, ignoring how the prose is wrapped.

    The record is hard-wrapped at 92 columns, so any phrase long enough to be
    worth asserting on will sooner or later straddle a line break. Matching
    word-by-word with ``\\s+`` between keeps a reflow of the paragraph from
    reading as a deletion of the sentence.
    """
    pattern = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.search(pattern, text) is not None


def _subsection(section: str, marker: str) -> str:
    """One bolded part of an ADR (``**Decision.**`` …) up to the next bold marker."""
    assert marker in section, f"ADR-005 is missing its {marker} section"
    start = section.index(marker) + len(marker)
    following = re.search(r"^\*\*[A-Z]", section[start:], re.MULTILINE)
    return section[start : start + following.start()] if following else section[start:]


# ─── 1. ADR-005 exists, is dated, and is newest ────────────────────────────


def test_decisions_records_adr_005_dated_2026_09_09():
    """``.project/DECISIONS.md`` carries ADR-005 with its date and four sections.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the ADR exists at
    the heading ``docs/reference/orchestrate-design.md`` points at, dated
    2026-09-09, and carries the Status / Context / Decision / Consequences
    skeleton every ADR in this file uses.
    """
    text = _decisions_text()
    section = _adr_section(text, ADR5_HEADING)

    assert "2026-09-09" in ADR5_HEADING, "the pinned heading lost its date"

    for marker in ("**Status:**", "**Context.**", "**Decision.**", "**Consequences"):
        assert marker in section, f"ADR-005 is missing its {marker} section"

    assert re.search(r"\*\*Alternatives\b", section), (
        "ADR-005 has no **Alternatives** section — the designs that lost "
        "(the shared tree with snapshots, one branch for the whole run, pushing "
        "the task branches, committing the store) are the record's point."
    )


def test_adr_005_is_newest_first():
    """ADR-005 sits above ADR-004, keeping the file's stated newest-first order.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): a fifth ADR
    appended to the bottom of the file would contradict the header's "Newest
    first" the same way a fourth would have.
    """
    text = _decisions_text()
    positions = {}
    for number in ("005", "004", "003"):
        found = text.find(f"## ADR-{number}:")
        assert found != -1, f"DECISIONS.md is missing ADR-{number}"
        positions[number] = found

    assert positions["005"] < positions["004"] < positions["003"], (
        "DECISIONS.md says 'Newest first' but the ADRs are out of order: "
        f"{sorted(positions, key=positions.get)}"
    )


# ─── 2. The Decision names the whole isolation model ───────────────────────


def test_adr_005_decision_names_the_branch_pattern_and_run_branch():
    """ADR-005's Decision names ``orch/<run-id>/<task-id>`` and ``orch/<run-id>``.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the branch names
    are the contract between the skill's dispatch step and its merge step, and
    the run branch is what a task branch is cut from — a decision that named
    only "a branch per task" would leave the merge point unspecified.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    decision = _subsection(section, "**Decision.**")

    assert "orch/<run-id>/<task-id>" in decision, (
        "ADR-005's Decision does not name the per-task branch pattern "
        "`orch/<run-id>/<task-id>`"
    )
    assert "orch/<run-id>`" in decision, (
        "ADR-005's Decision does not name the run branch `orch/<run-id>` that "
        "task branches are cut from and merged back onto"
    )
    assert "worktree" in decision.lower(), (
        "ADR-005's Decision does not say each task runs in its own worktree"
    )


def test_adr_005_decision_has_the_worker_commit_and_forbids_pushing():
    """ADR-005's Decision has the worker commit its branch, and pushes nothing.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): commit-on-branch
    and no-push are the two halves the criterion names. The no-push half is
    what the stage-only model contributed and what this ADR explicitly keeps,
    so it must survive as a rule and not only as history.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    decision = _subsection(section, "**Decision.**")

    assert _says(decision, "The worker commits its own code, on its own branch"), (
        "ADR-005's Decision does not say the worker commits its own code on "
        "its own branch"
    )
    assert _says(decision, "Nothing is pushed"), (
        "ADR-005's Decision does not state that nothing is pushed"
    )
    for forbidden in ("git push", "pm_push"):
        assert forbidden in decision, (
            f"ADR-005's Decision does not name `{forbidden}` among what a run "
            "never does"
        )


def test_adr_005_decision_keeps_the_project_store_out_of_run_commits():
    """ADR-005's Decision says ``.project`` is never committed by a run.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the store is a
    worktree of the ``projectman`` branch (ADR-001) on its own cadence, so
    folding it into a code branch is the regression this line prevents.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    decision = _subsection(section, "**Decision.**")

    assert _says(decision, "store is never committed by a run"), (
        "ADR-005's Decision does not state that the `.project` store is never "
        "committed by a run"
    )
    assert "pm_commit" in decision, (
        "ADR-005's Decision does not name `pm_commit` among what a run never "
        "calls"
    )


# ─── 3. The Consequences record what the model costs ───────────────────────


def test_adr_005_consequences_make_the_run_branch_the_product():
    """ADR-005's Consequences say the run branch is what gets reviewed and merged.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): under the
    stage-only model the run's product was a working-tree diff. Recording the
    swap is the point of the ADR — a reader who misses it looks for the work in
    the wrong place.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    consequences = section[section.index("**Consequences") :]

    assert _says(consequences, "run's product is a run branch to review and merge"), (
        "ADR-005's Consequences do not say the run's product is a run branch "
        "to review and merge rather than a diff to read"
    )
    assert "orch/<run-id>" in consequences, (
        "ADR-005's Consequences do not name the branch `orch/<run-id>` the "
        "user reviews"
    )


def test_adr_005_consequences_make_dependents_wait_for_the_merge():
    """ADR-005's Consequences say a dependent task waits for its dependency's merge.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): isolation cuts
    both ways — a worker cut from the run branch cannot see unmerged work — so
    accept-then-merge becomes ordering-critical rather than bookkeeping. This
    is the consequence most easily lost when the loop is later parallelised.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    consequences = section[section.index("**Consequences") :]

    assert _says(consequences, "Dependent tasks therefore wait for the merge"), (
        "ADR-005's Consequences do not say dependent tasks wait for the merge"
    )
    assert _says(consequences, "cannot see unmerged work"), (
        "ADR-005's Consequences do not say a worker starting from the run "
        "branch cannot see unmerged work"
    )


def test_adr_005_consequences_route_store_access_through_the_mcp_tools():
    """ADR-005's Consequences say a worktree has no ``.project``, so tools are the way in.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the store is
    gitignored on the code branch and therefore simply absent from a fresh
    worktree. A worker that opens ``.project`` by path would be reading nothing
    — the MCP tools act on the primary checkout instead.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    consequences = section[section.index("**Consequences") :]

    assert _says(consequences, "worktree carries no `.project`"), (
        "ADR-005's Consequences do not say the worktree carries no `.project`"
    )
    assert _says(consequences, "store access is via the MCP tools"), (
        "ADR-005's Consequences do not route store access through the MCP tools"
    )
    assert "primary checkout" in consequences, (
        "ADR-005's Consequences do not say the tools act on the primary "
        "checkout's store"
    )


def test_adr_005_consequences_leave_a_parked_task_its_branch():
    """ADR-005's Consequences say parking leaves the branch behind for a human.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): parking neither
    merges nor deletes, so the branch is the salvageable record of a failed
    attempt. Cleaning it up automatically would throw away the only artefact a
    parked task produces.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    consequences = section[section.index("**Consequences") :]

    assert _says(consequences, "parked task leaves its branch behind"), (
        "ADR-005's Consequences do not say a parked task leaves its branch "
        "behind for a human"
    )
    assert _says(consequences, "does not merge and does not delete"), (
        "ADR-005's Consequences do not say parking neither merges nor deletes "
        "the branch"
    )


# ─── 4. What it revises, and what it leaves alone ──────────────────────────


def test_adr_005_revises_the_stage_only_model_and_keeps_adr_004():
    """ADR-005's Status supersedes the stage-only model and keeps ADR-004 in force.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): an ADR that
    changes a rule has to say which rule and how far. This one revises the
    *stage-only model* in ``orchestrate-design.md`` on its isolation and commit
    halves only, and explicitly leaves ADR-004 — ProjectMan as a
    single-project tool — standing.
    """
    section = _adr_section(_decisions_text(), ADR5_HEADING)
    status = _subsection(section, "**Status:**")

    assert _says(status, "stage-only model"), (
        "ADR-005's Status does not name the *stage-only model* it revises"
    )
    assert "orchestrate-design.md" in status, (
        "ADR-005's Status does not point at `docs/reference/orchestrate-design.md`, "
        "where the stage-only model was recorded"
    )
    assert "supersedes" in status, (
        "ADR-005's Status does not say it supersedes the superseded halves of "
        "that model"
    )
    assert "ADR-004" in status and _says(status, "stays in force"), (
        "ADR-005's Status does not record that ADR-004 — ProjectMan as a "
        "single-project tool — stays in force"
    )


# ─── 5. The design doc points at the ADR instead of the old model ──────────


def test_orchestrate_design_has_an_isolation_model_section_citing_adr_005():
    """``orchestrate-design.md`` heads its constraints "Isolation model" and cites ADR-005.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the design doc is
    where an orchestrating agent goes to learn what a rule protects, so the
    section that used to argue for the stage-only model must now carry the
    revision and the link to the record.
    """
    assert ORCHESTRATE_DESIGN.exists(), f"{ORCHESTRATE_DESIGN} is missing"
    text = ORCHESTRATE_DESIGN.read_text(encoding="utf-8")

    heading = re.search(r"^##\s+Isolation model\s*$", text, re.MULTILINE)
    assert heading, (
        "docs/reference/orchestrate-design.md has no `## Isolation model` heading"
    )

    following = re.search(r"^##\s+", text[heading.end() :], re.MULTILINE)
    section = (
        text[heading.end() : heading.end() + following.start()]
        if following
        else text[heading.end() :]
    )

    assert "ADR-005" in section, (
        "the Isolation model section does not reference ADR-005, the record of "
        "the revision it describes"
    )
    assert "DECISIONS.md" in section, (
        "the Isolation model section names ADR-005 but does not link to "
        "`.project/DECISIONS.md`, where it lives"
    )
    for phrase in ("worktree", "orch/<run-id>/<task-id>"):
        assert phrase in section, (
            f"the Isolation model section does not mention {phrase!r} — it "
            "should describe the model ADR-005 records, in short form"
        )


def test_orchestrate_design_no_longer_heads_a_stage_only_model_section():
    """``orchestrate-design.md`` has no ``## Stage-only model`` heading left.

    Pins the criterion for story US-PM-51 (task US-PM-51-1): the stage-only
    model may be *named* in the prose — ADR-005's revision is unreadable
    otherwise — but it may no longer head a section as the design in force.
    """
    text = ORCHESTRATE_DESIGN.read_text(encoding="utf-8")

    stale = re.search(r"^#{1,6}\s+Stage[\s\-]?only\b.*$", text, re.MULTILINE | re.IGNORECASE)
    assert stale is None, (
        "docs/reference/orchestrate-design.md still heads a section "
        f"{stale.group(0)!r} — ADR-005 replaced the stage-only model with "
        "per-task worktrees; the heading should read `## Isolation model`."
    )


# ─── 6. The skills reference describes the model, not the old one ──────────
#
# ``docs/reference/skills.md`` is the user-facing catalogue: a reader deciding
# whether to run ``/pm-orchestrate`` meets the isolation model there long before
# ADR-005 or the design doc.  A catalogue still promising "changes are staged
# but never committed" would send that reader looking for a diff in a checkout
# the run never touched.

#: what the ``/pm-orchestrate`` section must name, in the reader's terms
SKILLS_DOC_CLAUSES = {
    "the run branch": "run branch `orch/<run-id>`",
    "the worktree dispatch": 'isolation: "worktree"',
    "the per-task branch": "`orch/<run-id>/<task-id>`",
    "the merge on accept": "git merge --ff-only",
    "branches merged, unmerged and abandoned": "**merged**",
}

#: and the stage-only wording it may no longer carry
SKILLS_DOC_GONE = [
    "changes are staged but never committed",
    "against the pre-flight snapshot",
    "md5 list",
]


def _skills_orchestrate_section() -> str:
    """The ``## /pm-orchestrate`` section of ``docs/reference/skills.md``."""
    assert SKILLS_DOC.exists(), f"{SKILLS_DOC} is missing"
    text = SKILLS_DOC.read_text(encoding="utf-8")
    heading = re.search(r"^##\s+/pm-orchestrate\s*$", text, re.MULTILINE)
    assert heading, "docs/reference/skills.md has no `## /pm-orchestrate` section"
    following = re.search(r"^##\s+", text[heading.end() :], re.MULTILINE)
    return (
        text[heading.end() : heading.end() + following.start()]
        if following
        else text[heading.end() :]
    )


@pytest.mark.parametrize("clause", list(SKILLS_DOC_CLAUSES), ids=list(SKILLS_DOC_CLAUSES))
def test_skills_doc_describes_the_isolation_model(clause):
    """The catalogue entry names each moving part ADR-005 introduced."""
    section = _skills_orchestrate_section()
    phrase = SKILLS_DOC_CLAUSES[clause]
    assert _says(section, phrase), (
        f"the /pm-orchestrate section of docs/reference/skills.md never names "
        f"{clause} ({phrase!r}) — a reader of the catalogue would not know the "
        "run produces branches"
    )


def test_skills_doc_lists_the_run_branches_in_the_final_report():
    """The report paragraph sorts the run's branches three ways."""
    section = _skills_orchestrate_section()
    for word in ("merged", "unmerged", "abandoned"):
        assert word in section, (
            "the /pm-orchestrate section does not say the final report lists "
            f"branches {word} — Phase 4's branch listing is how a run hands "
            "its work over"
        )


def test_skills_doc_no_longer_describes_the_stage_only_model():
    """No stage-only leftovers: no staged-not-committed, no snapshot, no md5 list."""
    section = _skills_orchestrate_section()
    stale = [phrase for phrase in SKILLS_DOC_GONE if _says(section, phrase)]
    assert not stale, (
        "the /pm-orchestrate section of docs/reference/skills.md still "
        f"describes the model ADR-005 replaced: {stale}"
    )
