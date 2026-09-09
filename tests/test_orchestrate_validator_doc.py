"""US-PM-48-4 — the design doc must explain the validator, and the skill stay small.

Story US-PM-48's acceptance criterion has two halves:

    "orchestrate-design.md explains the validator subagent and why its report
    is bounded, and the skill template stays within the MAX_CHARS budget"

The two halves are one criterion on purpose.  US-PM-48 moves the status, diff
and DoD checks into a subagent precisely to stop validation output from
accumulating in the orchestrator's context; if the *explanation* of that move
were written into the skill instead of the reference doc, the story would have
bought context back with one hand and spent it with the other.  So the
rationale is required to be in ``docs/reference/orchestrate-design.md`` and the
rendered skill is required to still fit within the ``MAX_CHARS`` budget.

Sibling modules pin the mechanism: ``test_orchestrate_validator_dispatch.py``
that a validator is dispatched, ``_prompt.py`` that its answer is asked for in
bounded JSON, and ``_verdict.py`` that the orchestrator transcribes it.  What
is pinned *here* is that a reader can find out **why** — independence from the
worker, the discarded context, the cap on the report, and what happens when the
verdict never arrives.

The size half is owned by ``test_orchestrate_skill_size.py``: its ``MAX_CHARS``
and the production renderer are imported rather than re-implemented, so the
budget has exactly one definition and this module cannot drift from it.

Assertions are tolerant regexes over the section with its whitespace collapsed,
not literal prose: the doc is hard-wrapped, and a criterion about *meaning*
must not fail on a re-worded sentence or a moved line break.

The last test is a falsification guard: a section that names the validator but
explains nothing is pushed through the same clause table and must be rejected.
A checklist that never fires is not evidence.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_orchestrate_design_doc import SECTIONS, _norm
from tests.test_orchestrate_skill_size import (
    DESIGN_DOC,
    MAX_CHARS,
    TEMPLATE_NAME,
    design_section,
)

HEADING = "## The validator subagent"

#: the fixed note the skill parks with when the validator never answers — the
#: same literal ``test_orchestrate_validator_verdict.py`` pins in step 18, so
#: doc and instruction cannot drift into two different wordings
NO_VERDICT_NOTE = "validator returned no verdict"

#: the keys of the bounded verdict object, as the prompt template asks for them
VERDICT_KEYS = ["verdict", "files", "tests", "dod_met", "dod_unmet", "note"]

#: the cap the story names, in characters
ANSWER_MAX_CHARS = 1500

TRUST_BUT_VERIFY = re.compile(r"trust[-\s]?but[-\s]?verify", re.I)
INDEPENDENCE = re.compile(r"\bindependen(?:ce|t|tly)\b", re.I)
#: "the validator is not the worker", however it happens to be phrased
NOT_THE_WORKER = re.compile(
    r"\b(?:validator|agent)\b[^.]{0,160}?\b(?:is|are|was)\b[^.]{0,60}?"
    r"\b(?:not|never)\b[^.]{0,160}?\bworker\b",
    re.I,
)
#: a context that does not survive the answer
DISCARDED_CONTEXT = re.compile(
    r"context[^.]{0,80}discard|discard\w*[^.]{0,80}context|thrown away|"
    r"window[^.]{0,80}(?:discard|thrown)",
    re.I,
)
CAP_WORD = re.compile(r"\bbound(?:ed|s)?\b|\bcap(?:ped|s)?\b|\bat most\b", re.I)
#: "about 1,500 characters", with or without the thousands separator
CAP_NUMBER = re.compile(r"\b1[,\s]?500\b")
#: *why* the cap exists — an unbounded report would re-import what was moved out
WHY_BOUNDED = re.compile(
    r"unbounded|re-?import|undo(?:es)? the saving|proportional|paste its evidence",
    re.I,
)
MALFORMED_VERDICT = re.compile(
    r"(?:missing|malformed|no usable|returns nothing|returns prose)[^.]{0,120}verdict|"
    r"verdict[^.]{0,120}(?:missing|malformed)",
    re.I,
)
RERUN_ONCE = re.compile(
    r"re-?run\w*\b[^.]{0,80}\bonce\b|\bonce\b[^.]{0,60}re-?run", re.I
)


def _section() -> str:
    """The ``The validator subagent`` block, whitespace-collapsed."""
    return _norm(design_section(HEADING))


def _sentences(section: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", section)


# ─── the clauses of the criterion ────────────────────────────────


def _stays_independent_of_the_worker(section: str) -> bool:
    """Trust-but-verify is named, and the validator is said not to be the worker."""
    return bool(
        TRUST_BUT_VERIFY.search(section)
        and INDEPENDENCE.search(section)
        and NOT_THE_WORKER.search(section)
    )


def _runs_in_a_discarded_context(section: str) -> bool:
    """A subagent, whose context is thrown away once it has answered."""
    return bool(
        re.search(r"\bsub-?agent\b", section, re.I) and DISCARDED_CONTEXT.search(section)
    )


def _bounds_the_report(section: str) -> bool:
    """The report is capped, and the cap named is ~1500 characters."""
    return bool(CAP_WORD.search(section) and CAP_NUMBER.search(section))


def _explains_why_it_is_bounded(section: str) -> bool:
    """The *why*: an unbounded answer re-imports the cost the split removed."""
    return bool(WHY_BOUNDED.search(section))


def _report_is_json_shaped(section: str) -> bool:
    """JSON is named, and every field of the verdict object is listed."""
    if not re.search(r"\bJSON\b", section):
        return False
    return all(re.search(rf"\b{key}\b", section) for key in VERDICT_KEYS)


def _names_the_malformed_verdict_case(section: str) -> bool:
    """A missing or malformed verdict is an explicit case, not a silent accept."""
    return bool(MALFORMED_VERDICT.search(section))


def _re_runs_the_validator_once(section: str) -> bool:
    """...answered by re-running the validator exactly once."""
    return bool(RERUN_ONCE.search(section))


def _then_parks_with_the_fixed_note(section: str) -> bool:
    """...and then parking, with the verbatim ``validator returned no verdict``."""
    return any(
        NO_VERDICT_NOTE in sentence.lower() and re.search(r"\bpark", sentence, re.I)
        for sentence in _sentences(section.lower())
    )


#: every clause of the criterion, as one table both the tests and the
#: falsification guard iterate — a clause cannot be checked in one and quietly
#: dropped from the other
CLAUSES = {
    "validation stays independent of the worker (trust-but-verify)": _stays_independent_of_the_worker,
    "the validator runs in a discarded context": _runs_in_a_discarded_context,
    f"the report is bounded at ~{ANSWER_MAX_CHARS} characters": _bounds_the_report,
    "it says why the report is bounded": _explains_why_it_is_bounded,
    "the report is JSON-shaped, with every field named": _report_is_json_shaped,
    "a missing or malformed verdict is an explicit case": _names_the_malformed_verdict_case,
    "the validator is re-run once": _re_runs_the_validator_once,
    f"then parked with {NO_VERDICT_NOTE!r}": _then_parks_with_the_fixed_note,
}


# ─── 1. the section exists, and is the one under test ────────────


def test_the_design_doc_has_the_validator_section():
    """Guard the slice: every clause below is scoped to this block."""
    assert HEADING in DESIGN_DOC.read_text(encoding="utf-8"), (
        f"{DESIGN_DOC} has no {HEADING!r} section — US-PM-48's rationale has "
        "nowhere to live but the skill, which the size budget forbids"
    )
    section = _section()
    assert len(section) > 500, "the validator section is too short to explain anything"
    assert "validator" in section.lower()


def test_the_section_is_listed_in_the_documents_table_of_contents():
    """The doc-wide section list must know about it, or a drop goes unnoticed."""
    assert HEADING.removeprefix("## ") in SECTIONS, (
        "tests/test_orchestrate_design_doc.py::SECTIONS does not list the "
        "validator section, so deleting it would not fail that module"
    )


# ─── 2. the criterion, clause by clause ──────────────────────────


@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_the_validator_section_satisfies_each_clause(clause):
    """The acceptance criterion, one clause per case, on the doc as shipped."""
    section = _section()
    assert CLAUSES[clause](section), (
        f"{DESIGN_DOC.name} {HEADING!r} fails: {clause}\n\n{section}"
    )


# ─── 3. ...and the skill did not grow to say it ──────────────────


def test_the_rendered_skill_still_fits_the_budget():
    """The other half of the criterion: within the MAX_CHARS budget, still.

    ``test_orchestrate_skill_size.py`` owns this budget — its ``MAX_CHARS`` and
    the production renderer are imported here rather than re-implemented — but
    the criterion pairs the two halves, so it is asserted once more: rationale
    written into the skill instead of the design doc must fail *this* module
    too, not only the sibling one.
    """
    rendered = _render_template(TEMPLATE_NAME)
    assert len(rendered) <= MAX_CHARS, (
        f"rendered {TEMPLATE_NAME} is {len(rendered)} characters, over the "
        f"{MAX_CHARS}-character budget"
    )


# ─── 4. the guard ────────────────────────────────────────────────


def test_the_clause_checks_reject_an_unexplained_section():
    """Falsification guard: naming the validator without explaining it must fail.

    Without this, the tolerant regexes above could be satisfied by any section
    that happened to use the word "validator", and the module would pass on a
    doc that leaves the next reader to guess why the report is capped.
    """
    unexplained = _norm(
        "## The validator subagent\n\n"
        "After the worker returns, the orchestrator spawns a validator to look "
        "over the task.\n"
        "It reports back on what it found, and the orchestrator then decides "
        "what to do next.\n"
    )
    failed = [name for name, check in CLAUSES.items() if not check(unexplained)]
    assert failed == list(CLAUSES), (
        "an unexplained section passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
