"""US-PM-48-2 — the validator prompt must ask for one bounded JSON verdict.

Story US-PM-48 moves the status/diff/DoD checks out of the orchestrator's own
context and into a validator subagent.  That only saves context if the
validator's *answer* is bounded: an unbounded report would put the test output,
md5 listings and diff stats back into the orchestrator, which is the cost the
story exists to remove.  So the acceptance criterion is about the prompt the
orchestrator sends —

    "The validator prompt template asks for a single bounded JSON verdict with
    files, tests, dod_met, dod_unmet and a note under 200 characters"

— and this module pins it, clause by clause, on the ``Validator Prompt
Template`` fence of the pm-orchestrate skill.

Both documents are checked: the Jinja template (source of truth) and the
tracked rendered ``.claude/skills/pm-orchestrate/SKILL.md``, because the
rendered copy is what an orchestrating agent actually loads.  Their
byte-for-byte equality is already owned by
``test_orchestrate_skill_size.py::test_tracked_rendered_skill_matches_the_template``
and is not re-asserted here; what *is* asserted is that the render produced
from the template carries the block, so a template edit that never reaches the
renderer is caught too.

The last test is a falsification guard: a prompt that asks for a free-form
report is pushed through the same clause checks and must be rejected.  A
checklist that never fires is not evidence.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_skill_verdict_verbs import (
    ORCHESTRATE_TEMPLATE_NAME,
    DOCS,
    _fences,
    _text,
)

HEADING = "## Validator Prompt Template"

#: the keys the criterion names, plus ``verdict`` — the field the orchestrator
#: maps onto pm_accept / pm_retry / pm_park / pm_review (US-PM-48-3)
REQUIRED_KEYS = ["verdict", "files", "tests", "dod_met", "dod_unmet", "note"]

#: the four verdicts, exactly as step 19 spells them
VERDICTS = ["accept", "retry", "park", "review"]

#: the note's ceiling, in characters — the criterion's own number
NOTE_MAX_CHARS = 200

#: the whole answer's ceiling — "capped at about 1500 characters" (story design)
ANSWER_MAX_CHARS = 1500

#: the worker rules the validator is told to check, as substrings of the
#: lowercased fence.  ``checkout|restore|stash|reset`` may be written as a
#: slash-separated list, so each verb is looked for on its own.
SAFETY_VERBS = ["checkout", "restore", "stash", "reset"]


def _validator_fence(text: str) -> str:
    """The fenced block under ``## Validator Prompt Template``.

    Sliced to the section first, so a fence added elsewhere in the skill can
    never stand in for the one the criterion is about.
    """
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.strip() == HEADING]
    assert starts, f"no {HEADING!r} section — the validator prompt is missing"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    blocks = _fences(section)
    assert len(blocks) == 1, (
        f"expected exactly one fenced block under {HEADING!r}, found {len(blocks)}"
    )
    return blocks[0]


def _json_skeleton(fence: str) -> str:
    """The ``{...}`` object literal inside the fence, from first ``{`` to its close."""
    start = fence.find("{")
    assert start != -1, "the validator prompt shows no JSON object at all"
    depth = 0
    for n in range(start, len(fence)):
        if fence[n] == "{":
            depth += 1
        elif fence[n] == "}":
            depth -= 1
            if depth == 0:
                return fence[start : n + 1]
    raise AssertionError("the JSON object in the validator prompt is never closed")


def _asks_for_one_json_object(fence: str) -> bool:
    """One object requested in prose, and exactly one object literal shown."""
    prose = re.search(r"\bone JSON object\b", fence, re.IGNORECASE)
    try:
        skeleton = _json_skeleton(fence)
    except AssertionError:  # no object shown at all — the clause simply fails
        return False
    # nothing but whitespace/punctuation may follow the object — a second
    # top-level ``{`` would mean the validator was asked for several objects
    tail = fence[fence.find(skeleton) + len(skeleton) :]
    return bool(prose) and "{" not in tail


def _numbers(fence: str) -> list[int]:
    return [int(m) for m in re.findall(r"\d+", fence)]


def _bounds_the_note(fence: str) -> bool:
    """``note`` is capped, and the cap named next to it is 200 characters."""
    note = re.search(r'"note"\s*:\s*"([^"]*)"', fence)
    if not note:
        return False
    return NOTE_MAX_CHARS in _numbers(note.group(1))


def _bounds_the_answer(fence: str) -> bool:
    return ANSWER_MAX_CHARS in _numbers(fence)


def _names_every_key(fence: str) -> bool:
    return all(f'"{key}"' in fence for key in REQUIRED_KEYS)


def _lists_every_verdict(fence: str) -> bool:
    verdict = re.search(r'"verdict"\s*:\s*"([^"]*)"', fence)
    if not verdict:
        return False
    return all(v in verdict.group(1) for v in VERDICTS)


def _carries_the_safety_rules(fence: str) -> bool:
    low = fence.lower()
    return (
        all(verb in low for verb in SAFETY_VERBS)
        and "commit" in low
        and "store write" in low
    )


#: every clause of the criterion, as one table both the tests and the
#: falsification guard iterate — a clause cannot be checked in one and quietly
#: dropped from the other
CLAUSES = {
    "asks for exactly one JSON object": _asks_for_one_json_object,
    "names every required key": _names_every_key,
    "lists all four verdicts": _lists_every_verdict,
    f"bounds the note at {NOTE_MAX_CHARS} chars": _bounds_the_note,
    f"bounds the answer at {ANSWER_MAX_CHARS} chars": _bounds_the_answer,
    "carries the worker safety rules": _carries_the_safety_rules,
}


@pytest.mark.parametrize("path", DOCS)
def test_validator_prompt_fence_is_extractable(path):
    """Guard the slice: every assertion below is scoped to this text."""
    fence = _validator_fence(_text(path))
    assert "valid" in fence.lower(), "the fence under the heading is not the validator prompt"
    assert len(fence.splitlines()) >= 5, "the validator prompt lost its body"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_validator_prompt_satisfies_each_clause(path, clause):
    """The acceptance criterion, one clause per case, on template and render."""
    fence = _validator_fence(_text(path))
    assert CLAUSES[clause](fence), f"validator prompt fails: {clause}\n\n{fence}"


def test_rendered_template_carries_the_validator_prompt():
    """Rendering the template — not just reading the tracked copy — yields it.

    ``test_orchestrate_skill_size.py`` already pins that the tracked
    ``SKILL.md`` equals this render; asserting the clauses against the render
    itself means a template edit is caught even before that equality is.
    """
    fence = _validator_fence(_render_template(ORCHESTRATE_TEMPLATE_NAME))
    for name, check in CLAUSES.items():
        assert check(fence), f"rendered {ORCHESTRATE_TEMPLATE_NAME} fails: {name}"


def test_the_clause_checks_reject_an_unbounded_prompt():
    """Falsification guard: a free-form report must fail every clause.

    Without this, the checks above could be satisfied by prose that merely
    mentions the words and the module would pass on a prompt that lets the
    validator dump diff stats and test output into the orchestrator.
    """
    unbounded = (
        "Validate finished task <task-id>; run the tests the DoD names.\n"
        "Report back in whatever form is clearest: which files changed, what\n"
        "the tests printed, and whether the DoD is met.\n"
    )
    failed = [name for name, check in CLAUSES.items() if not check(unbounded)]
    assert failed == list(CLAUSES), (
        "an unbounded free-form prompt passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
