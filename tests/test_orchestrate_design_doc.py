"""US-PM-25-2 — the rationale left the skill and landed in the reference doc.

Story US-PM-25 split one 31,731-byte skill in two: instruction stayed in
``src/projectman/templates/skill_pm_orchestrate.md.j2`` (US-PM-25-6 cut it to
under 9,000 characters), and the *why* — the design arguments, the resume
essay, and the incident log behind the worker safety rules — moved to
``docs/reference/orchestrate-design.md`` (US-PM-25-5).

A split like that has two failure modes, and neither is caught by a size check:

* **the rationale is lost**, because "move it to a doc" quietly became "delete
  it".  Every assertion below that names a phrase from the *pre-rewrite*
  template, read straight out of ``git show HEAD:``, is a guard against that:
  the fact has to be findable in the design doc today.
* **the rationale is duplicated**, because a copy was left behind or a second
  doc grew its own version.  The same assertions therefore also require the
  migrated phrase to be *absent* from the current template, and the resume
  essay is required to live in exactly one file under ``docs/``.

Sibling modules already pin the parts this one deliberately does not repeat:
``tests/test_orchestrate_skill_size.py`` owns the 9,000-character budget and
the link count, and ``tests/test_skill_resume_path.py`` and friends re-target
individual rationale assertions at the design doc.  What is only checked here
is the doc as a *whole*: that it has all eleven sections, that the resume
protocol and the failure-mode log say what they are supposed to say, that the
migration actually moved rather than deleted, and that the "Template sections
absorbed" map accounts for every ``## `` heading the old template had.
"""

import functools
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_orchestrate_skill_size import (
    DESIGN_DOC,
    DESIGN_DOC_LINK,
    REPO_ROOT,
    TEMPLATE_REPO_PATH,
    design_section,
)

CURRENT_TEMPLATE = REPO_ROOT / TEMPLATE_REPO_PATH

#: every ``## `` section US-PM-25-5 wrote, in document order.  The list is the
#: doc's table of contents, so a section quietly dropped in a later edit fails
#: here rather than being noticed by the next reader who cannot find it.
SECTIONS = [
    "Stage-only model",
    "Run identity",
    "Pre-flight and claim classification",
    "Dispatch and the worker prompt",
    "Validation and verdicts",
    "Health checks",
    "Resume protocol",
    "Final report from the activity log",
    "Known failure modes",
    "Sizes and numbers",
    "Template sections absorbed",
]


def _norm(text: str) -> str:
    """Collapse runs of whitespace so a phrase can span a wrapped line.

    Both documents are hard-wrapped at ~90 columns, so a literal ``in`` test
    against the raw text would fail on nothing more than where the paragraph
    happened to break.  Normalising is what makes the phrase — rather than its
    line breaks — the thing under test.
    """
    return re.sub(r"\s+", " ", text)


@functools.lru_cache(maxsize=1)
def head_template() -> str:
    """The pre-US-PM-25-6 template, read (read-only) out of git HEAD.

    This is the ground truth for "the rationale that used to be in the skill":
    a phrase is only evidence of a *migration* if it can be shown to have been
    in the template before the rewrite.
    """
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{TEMPLATE_REPO_PATH}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"git show HEAD:{TEMPLATE_REPO_PATH} unavailable: {exc}")
    return out.stdout


def _doc() -> str:
    return _norm(DESIGN_DOC.read_text(encoding="utf-8"))


def _template() -> str:
    return _norm(CURRENT_TEMPLATE.read_text(encoding="utf-8"))


# ─── 1. the doc exists, and has all eleven sections ──────────────


def test_design_doc_exists():
    assert DESIGN_DOC.is_file(), (
        f"{DESIGN_DOC} is missing — US-PM-25-6 shrank the skill on the promise "
        "that its rationale lives here"
    )
    assert DESIGN_DOC.stat().st_size > 10_000, (
        f"{DESIGN_DOC} is only {DESIGN_DOC.stat().st_size} bytes; roughly 13k "
        "of rationale was moved out of the template into it"
    )


@pytest.mark.parametrize("heading", SECTIONS)
def test_design_doc_has_section(heading):
    """``design_section`` asserts the heading exists; the body must be real."""
    body = design_section(f"## {heading}")
    assert len(_norm(body)) > 200, (
        f"section {heading!r} of {DESIGN_DOC} is a stub — the rationale it "
        "names has to be written down, not merely headed"
    )


def test_design_doc_sections_are_in_document_order():
    """Order is the doc's argument: model, then loop, then recovery, then map."""
    found = re.findall(r"^## (.+)$", DESIGN_DOC.read_text(encoding="utf-8"), re.M)
    assert found == SECTIONS


# ─── 2. the resume protocol, in substance ────────────────────────
#
# The five rules are pinned by what they *say*, not by their R1–R5 labels, so a
# renumbering does not fail and a deletion does.  R1's lineage note is stated
# under *Run identity* and cross-referenced from *Resume protocol* ("Covered
# under *Run identity*"), so the scope for these checks is both sections.

RESUME_RULES = [
    pytest.param(
        ["new id", "reuse would merge"],
        id="R1-mints-a-new-id-per-run",
    ),
    pytest.param(
        ["read the dead run's record", "pm_activity(run_id=<old>)", "has_more"],
        id="R2-reads-the-old-run's-activity-first",
    ),
    pytest.param(
        ["Still in-progress under the old id", "adopt"],
        id="R3-adopts-only-tasks-still-claimed-by-the-old-run",
    ),
    pytest.param(
        ["lineage", "recovered from run"],
        id="R4-writes-the-recovered-from-run-lineage-note",
    ),
    pytest.param(
        ["dispatched as a retry, never as fresh work", "<on resume:"],
        id="R5-dispatches-adopted-tasks-as-retries",
    ),
]

#: the states in which ``--resume`` is the wrong instruction
WHEN_NOT_TO_RESUME = [
    pytest.param("A human holds it", id="a-human-holds-the-claim"),
    pytest.param(
        "The old run is still emitting events", id="the-old-run-is-still-alive"
    ),
    pytest.param("The id matched no events", id="an-unknown-run-id"),
]


def _resume_scope() -> str:
    return _norm(design_section("## Resume protocol")) + " " + _norm(
        design_section("## Run identity")
    )


@pytest.mark.parametrize("phrases", RESUME_RULES)
def test_resume_protocol_states_the_rule(phrases):
    scope = _resume_scope()
    for phrase in phrases:
        assert phrase in scope, (
            f"the resume protocol in {DESIGN_DOC} never says {phrase!r} — the "
            "skill's short Resume section relies on this doc for the reason"
        )


def test_resume_protocol_section_owns_the_five_rules_itself():
    """The section is the essay; *Run identity* only holds R1's lineage note."""
    body = _norm(design_section("## Resume protocol"))
    for label in ("R1", "R2", "R3", "R4", "R5"):
        assert label in body, f"{label} is missing from the Resume protocol section"
    assert "lineage note" in body


@pytest.mark.parametrize("case", WHEN_NOT_TO_RESUME)
def test_resume_protocol_states_when_not_to_resume(case):
    body = _norm(design_section("## Resume protocol"))
    assert "When not to resume" in body, (
        "the Resume protocol section has no when-NOT-to-resume list; adopting a "
        "claim that is not the orchestrator's is the failure it prevents"
    )
    assert case in body, f"when-not-to-resume is missing the case {case!r}"


# ─── 3. the incident log, each incident with its rule ────────────
#
# Every worker safety rule was bought with a specific failure.  The doc says so
# in order that the rule is not read as ceremony and deleted; these checks are
# what keep the incident attached to the rule it produced.

INCIDENTS = [
    pytest.param(
        "`git checkout` erased three tasks' work",
        "never runs `git checkout`, `git restore`, `git stash`, `git reset`, or "
        "`git clean`",
        id="sprint-5-git-checkout",
    ),
    pytest.param(
        "left a stray story in the repository's real `.project/`",
        "never call `pm_create_*`, or any Store write, outside a "
        "`tmp_path`-isolated fixture",
        id="sprint-6-stray-story",
    ),
    pytest.param(
        "scratchpad staging pulled in a stale copy",
        "edit tracked files directly with the Edit tool",
        id="sprint-6-scratchpad-staging",
    ),
    pytest.param(
        "already_done",
        "a worker leaves its task `in-progress` and lets `pm_accept` close it",
        id="2026-09-05-already_done-evidence-loss",
    ),
]


@pytest.mark.parametrize("incident,rule", INCIDENTS)
def test_known_failure_mode_names_the_incident_and_its_rule(incident, rule):
    blocks = [
        _norm(block).strip()
        for block in design_section("## Known failure modes").split("\n\n")
        if block.strip()
    ]
    matching = [b for b in blocks if incident in b]
    assert matching, (
        f"{DESIGN_DOC} has no Known-failure-modes entry for {incident!r}; the "
        "worker prompt still carries the rule it produced"
    )
    assert any(rule in b for b in matching), (
        f"the entry for {incident!r} does not state the rule it produced "
        f"({rule!r}) — an incident with no rule is an anecdote"
    )


def test_every_failure_mode_entry_states_a_rule():
    blocks = [
        _norm(block).strip()
        for block in design_section("## Known failure modes").split("\n\n")
        if block.strip()
    ]
    incidents = [b for b in blocks if re.match(r"\*\*20\d\d-\d\d-\d\d", b)]
    assert len(incidents) >= len(INCIDENTS)
    for block in incidents:
        assert "→ **Rule" in block, f"incident with no rule: {block[:80]!r}"


# ─── 4. the migration: present in the doc, gone from the skill ───
#
# Each pair is (a phrase from the *pre-rewrite* template, the phrase that now
# carries the same fact in the design doc).  The first half proves the fact was
# in the skill; the second proves it survived the move; and both halves must be
# absent from the template as it stands, which is what makes this a migration
# rather than a copy.

MIGRATED = [
    pytest.param(
        "48,588",
        "48,588",
        id="the-48588-char-unbounded-pm_context-measurement",
    ),
    pytest.param(
        "Parallel workers require atomic task claiming",
        "Parallel workers would need atomic task claiming",
        id="why-the-loop-is-sequential",
    ),
    pytest.param(
        "2,000 chars each holds the whole return near 10k",
        "five docs at 2,000 chars each holds the return near 10k",
        id="why-pm_context-is-bounded-to-5-docs-of-2000-chars",
    ),
    pytest.param(
        "byte-identical repeats",
        "byte-identical repeats",
        id="the-repeated-audits-are-not-waste",
    ),
    pytest.param(
        "Caching `pm_audit` per session would disable it",
        "caching `pm_audit` per session would disable it silently",
        id="caching-the-health-check-would-disable-it",
    ),
    pytest.param(
        "A stale or unknown `since` is never an error",
        "A stale or unknown `since` is never an error",
        id="a-missed-audit-digest-is-never-an-error",
    ),
    pytest.param(
        "tens of chars instead of thousands",
        "tens of characters rather than thousands",
        id="why-validation-reads-status-with-fields=",
    ),
    pytest.param(
        "an unexpected assignee means someone else touched the task",
        "an unexpected assignee means something else touched the task",
        id="why-the-status-read-also-projects-assignee",
    ),
    pytest.param(
        "read the diff, don't just count files",
        "Why the diff is read, not counted",
        id="why-the-diff-is-read-not-counted",
    ),
    pytest.param(
        "step 19 is a transcription, not a recollection",
        "so the verdict is a transcription rather than a recollection",
        id="why-the-three-lists-are-collected-while-validating",
    ),
    pytest.param(
        "prose is not the container for a list",
        "Prose is not the container for a list",
        id="why-the-note-is-one-line-and-lists-go-in-evidence",
    ),
    pytest.param(
        "an unattributable non-`orch-` id",
        "an unattributable non-`orch-` id",
        id="the-one-claim-still-worth-a-question",
    ),
    pytest.param(
        "so a restart never collides",
        "so a restart never collides with the run it is recovering from",
        id="why-the-random-tail-of-the-run-id-must-differ",
    ),
]


def test_at_least_eight_rationale_phrases_are_pinned():
    """The story's criterion is a body of rationale, not a single sentence."""
    assert len(MIGRATED) >= 8


@pytest.mark.parametrize("was_in_skill,now_in_doc", MIGRATED)
def test_rationale_moved_from_the_skill_to_the_design_doc(was_in_skill, now_in_doc):
    assert was_in_skill in _norm(head_template()), (
        f"{was_in_skill!r} is not in the pre-rewrite template — this case no "
        "longer demonstrates a migration and needs re-picking"
    )
    assert now_in_doc in _doc(), (
        f"rationale lost in the move: {now_in_doc!r} is nowhere in "
        f"{DESIGN_DOC}, though the skill used to carry it"
    )
    template = _template()
    assert was_in_skill not in template and now_in_doc not in template, (
        f"{CURRENT_TEMPLATE} still carries the rationale {was_in_skill!r}; the "
        "split puts instruction in the skill and the reasoning in the doc, and "
        "two copies drift"
    )


# ─── 5. one link out, one copy of the essay ──────────────────────

#: sentences unique to the resume essay.  ``docs/reference/skills.md`` keeps a
#: condensed user-facing summary of the same protocol on purpose (the design
#: doc links it as such); what must not exist is a second copy of the argument.
RESUME_ESSAY_SENTENCES = [
    "Two recoveries of one claim is the race the whole scheme exists to prevent",
    "an adopted task is dispatched as a retry, never as fresh work",
    "it is slow, not dead, and adopting races a live process",
    "Falling back to ordinary classification is better than guessing",
]


def test_template_links_the_design_doc():
    assert DESIGN_DOC_LINK in _template(), (
        f"{CURRENT_TEMPLATE} does not name {DESIGN_DOC_LINK}; a reader of the "
        "shortened skill would have no way to reach the reasoning"
    )


@pytest.mark.parametrize("sentence", RESUME_ESSAY_SENTENCES)
def test_the_resume_essay_lives_in_exactly_one_doc(sentence):
    owners = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "docs").rglob("*.md")
        if sentence in _norm(path.read_text(encoding="utf-8"))
    )
    assert owners == ["docs/reference/orchestrate-design.md"], (
        f"{sentence!r} appears in {owners or 'no file'} — the resume essay must "
        "have exactly one home, or the copies disagree after the first edit"
    )


# ─── 6. the absorbed map accounts for the whole old template ─────


def test_absorbed_map_lists_every_section_of_the_head_template():
    """Nothing is dropped silently: every old ``## `` heading has a row.

    A heading whose title carries a parenthetical (``## Stop Conditions
    (systemic — …)``) is allowed to appear under the short title the table
    uses; what may not happen is a section vanishing from the map entirely.
    """
    table = _norm(design_section("## Template sections absorbed"))
    headings = re.findall(r"^## (.+)$", head_template(), re.M)
    assert len(headings) == 11, (
        f"the pre-rewrite template had {len(headings)} '## ' sections, not 11 — "
        "re-check the map against HEAD"
    )
    missing = [
        heading
        for heading in headings
        if heading not in table and heading.split(" (")[0].strip() not in table
    ]
    assert not missing, (
        f"'Template sections absorbed' does not account for {missing} — every "
        "section of the 31,731-byte template must be marked absorbed or kept"
    )
