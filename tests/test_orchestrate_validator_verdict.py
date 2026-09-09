"""US-PM-48-3 — the validator's verdict must drive the orchestrator's verb.

Story US-PM-48's acceptance criterion:

    "The orchestrator maps the validator verdict onto pm_accept, pm_retry,
    pm_park or pm_review with the verdict object passed as evidence"

US-PM-48-1 pinned that a validator is *dispatched* and US-PM-48-2 that its
answer is *bounded*.  Neither is worth anything if the answer is then read as
prose and re-judged: the orchestrator would be back to reasoning over test
output, and the four verbs US-PM-8 introduced (``tests/test_verdict_verbs.py``,
``tests/test_skill_verdict_verbs.py``) would be picked by vibe rather than by
the field the validator was asked to fill.  So this module pins the *mapping*,
on the Validation steps of the pm-orchestrate skill:

* **step 19 (a)** — the validator's ``verdict`` field picks the verb, and each
  of the four values ``accept`` / ``retry`` / ``park`` / ``review`` is spelled
  out against ``pm_accept`` / ``pm_retry`` / ``pm_park`` / ``pm_review``;
* **step 19 (b)** — the verdict object *minus* ``verdict`` and ``note`` is
  handed straight to ``evidence``, and its ``note`` becomes the one-line note,
  so nothing is re-derived by the orchestrator;
* **step 18 (c)** — the failure mode is closed too: a missing or malformed
  verdict is *one* validation failure, the validator is re-run once, and then
  the task is parked with the fixed note ``"validator returned no verdict"``.

Both documents are checked, the Jinja template (source of truth) and the
tracked rendered ``.claude/skills/pm-orchestrate/SKILL.md`` an orchestrating
agent actually loads, plus the render produced by ``_render_template`` itself,
so a template edit that never reaches the renderer is caught as well.
Byte-for-byte equality of template and tracked copy is owned by
``test_orchestrate_skill_size.py::test_tracked_rendered_skill_matches_the_template``
and is not re-asserted here.

The last test is a falsification guard: steps 18-19 rewritten to have the
orchestrator read the validator's output and hand-roll a ``pm_update`` must
fail every clause.  A checklist that never fires is not evidence.
"""

import re

import pytest

from projectman.cli import _render_template
from tests.test_skill_verdict_verbs import (
    ORCHESTRATE_TEMPLATE_NAME,
    DOCS,
    _text,
)

#: the criterion's mapping: the ``verdict`` value the validator returns → the
#: verb the orchestrator must call for it.  ``review`` is spelled
#: "Accept-as-review" in the skill, which is why the label is matched by
#: *containment* rather than equality.
VERDICT_VERBS = {
    "accept": "pm_accept",
    "retry": "pm_retry",
    "park": "pm_park",
    "review": "pm_review",
}

#: the note's ceiling, in characters — the same number the validator prompt
#: bounds ``note`` with (US-PM-48-2)
NOTE_MAX_CHARS = 200

#: the note step 18 must park with, verbatim
NO_VERDICT_NOTE = "validator returned no verdict"

# ── step 19 (a): the ``verdict`` field, not the orchestrator, picks the verb ──
VERDICT_PICKS_VERB = re.compile(r"`verdict`[^\n]{0,60}\bverbs?\b", re.IGNORECASE)

# ── step 19 (b): the object minus verdict/note is evidence; note is the note ──
MINUS_IS_EVIDENCE = re.compile(
    r"(minus|without|excluding|less|other than)\b[^\n]{0,40}`verdict`"
    r"[^\n]{0,30}`note`[^\n]{0,40}`evidence`",
    re.IGNORECASE,
)
NOTE_IS_THE_NOTE = re.compile(r"`note`[^\n]{0,40}\bthe note\b", re.IGNORECASE)
ONE_LINE = re.compile(r"\bone[- ]line\b|\bone line\b", re.IGNORECASE)

# ── step 18 (c): the missing-verdict path ────────────────────────────────────
MISSING_VERDICT = re.compile(
    r"(missing|malformed|absent|no)\b[^.\n]{0,60}\bverdict\b", re.IGNORECASE
)
ONE_FAILURE = re.compile(r"\bone\b[^.\n]{0,25}\bfailure\b", re.IGNORECASE)
RERUN_ONCE = re.compile(
    r"re-?run[^.\n]{0,40}\bvalidator\b[^.\n]{0,25}\bonce\b", re.IGNORECASE
)

#: a bullet's bold label: ``    - **Accept-as-review**: ...``
BULLET_LABEL = re.compile(r"^\s*[-*]\s*\*\*([^*]+)\*\*")


def _step(text: str, number: int) -> str:
    """The block of step ``number``: its line, up to the next step's line."""
    prefix, following = f"{number}.", f"{number + 1}."
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(prefix)]
    ends = [n for n, line in enumerate(lines) if line.startswith(following)]
    assert starts, f"no line starting with {prefix!r} — step {number} vanished"
    assert ends, f"no line starting with {following!r} — cannot bound step {number}"
    start = starts[0]
    end = next(n for n in ends if n > start)
    return "\n".join(lines[start:end])


def _head(block: str) -> str:
    """The step's own line, without the bullets hanging under it."""
    return block.splitlines()[0]


def _verb_bullets(block: str) -> dict[str, str]:
    """``{verb: the bullet line that calls it}`` for the verbs step 19 names."""
    found: dict[str, str] = {}
    for line in block.splitlines():
        for verb in VERDICT_VERBS.values():
            if f"{verb}(" in line and verb not in found:
                found[verb] = line
    return found


# ═══ the criterion, clause by clause ════════════════════════════
# Each clause takes the whole document, so the falsification guard can mutate
# a step and push the result through the very same checks.


def _verdict_field_picks_the_verb(text: str) -> bool:
    """Step 19 says the validator's ``verdict`` field chooses the verb."""
    return bool(VERDICT_PICKS_VERB.search(_head(_step(text, 19))))


def _every_verdict_maps_to_its_verb(text: str) -> bool:
    """All four values are mapped, each on the bullet that calls its verb."""
    bullets = _verb_bullets(_step(text, 19))
    if set(bullets) != set(VERDICT_VERBS.values()):
        return False
    for value, verb in VERDICT_VERBS.items():
        label = BULLET_LABEL.match(bullets[verb])
        if not label or value not in label.group(1).lower():
            return False
    return True


def _object_minus_verdict_and_note_is_evidence(text: str) -> bool:
    """The verdict object, less ``verdict``/``note``, is passed as ``evidence``."""
    return bool(MINUS_IS_EVIDENCE.search(_head(_step(text, 19))))


def _every_verb_call_passes_evidence(text: str) -> bool:
    """Each of the four calls actually shows an ``evidence=`` argument."""
    bullets = _verb_bullets(_step(text, 19))
    if set(bullets) != set(VERDICT_VERBS.values()):
        return False
    return all("evidence=" in line for line in bullets.values())


def _note_becomes_the_one_line_note(text: str) -> bool:
    """The verdict's ``note`` is the note, and it is one line, <= 200 chars."""
    head = _head(_step(text, 19))
    return bool(
        NOTE_IS_THE_NOTE.search(head)
        and ONE_LINE.search(head)
        and str(NOTE_MAX_CHARS) in head
    )


def _missing_verdict_is_one_validation_failure(text: str) -> bool:
    """Step 18 counts a missing or malformed verdict as a single failure."""
    head = _head(_step(text, 18))
    return bool(MISSING_VERDICT.search(head) and ONE_FAILURE.search(head))


def _re_runs_the_validator_once(text: str) -> bool:
    """...and re-runs the validator exactly once before giving up."""
    return bool(RERUN_ONCE.search(_head(_step(text, 18))))


def _then_parks_with_the_fixed_note(text: str) -> bool:
    """...then parks the task with the verbatim no-verdict note."""
    head = _head(_step(text, 18))
    return "pm_park(" in head and NO_VERDICT_NOTE in head


CLAUSES = {
    "the verdict field picks the verb": _verdict_field_picks_the_verb,
    "every verdict value maps to its verb": _every_verdict_maps_to_its_verb,
    "the object minus verdict/note is evidence": _object_minus_verdict_and_note_is_evidence,
    "every verb call passes evidence": _every_verb_call_passes_evidence,
    "the note becomes the one-line note": _note_becomes_the_one_line_note,
    "a missing verdict is one validation failure": _missing_verdict_is_one_validation_failure,
    "the validator is re-run once": _re_runs_the_validator_once,
    f"then pm_park with {NO_VERDICT_NOTE!r}": _then_parks_with_the_fixed_note,
}


@pytest.mark.parametrize("path", DOCS)
def test_verdict_steps_are_extractable(path):
    """Guard the slice: every assertion below is scoped to these two steps."""
    text = _text(path)
    assert "verdict" in _step(text, 18).lower(), "step 18 is not the no-verdict path"
    step_19 = _step(text, 19)
    assert "Verdict" in step_19, "step 19 is not the verdict step"
    assert len(step_19.splitlines()) >= 5, "step 19 lost its verdict bullets"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_verdict_mapping_satisfies_each_clause(path, clause):
    """The acceptance criterion, one clause per case, on template and render."""
    text = _text(path)
    assert CLAUSES[clause](text), (
        f"{path.name} fails: {clause}\n\n{_step(text, 18)}\n{_step(text, 19)}"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("value,verb", sorted(VERDICT_VERBS.items()))
def test_each_verdict_value_names_its_own_verb(path, value, verb):
    """Named per pair so a broken mapping says *which* verdict lost its verb."""
    block = _step(_text(path), 19)
    bullets = _verb_bullets(block)
    assert verb in bullets, f"{path.name} step 19 never calls {verb}\n\n{block}"
    label = BULLET_LABEL.match(bullets[verb])
    assert label, f"{path.name}: the {verb} bullet has no bold verdict label"
    assert value in label.group(1).lower(), (
        f"{path.name}: verdict {value!r} is not what {verb} is labelled — "
        f"found {label.group(1)!r}"
    )


def test_rendered_template_maps_the_verdict_onto_the_verbs():
    """Rendering the template — not just reading the tracked copy — yields it."""
    rendered = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    for name, check in CLAUSES.items():
        assert check(rendered), f"rendered {ORCHESTRATE_TEMPLATE_NAME} fails: {name}"


def test_the_clause_checks_reject_a_hand_rolled_verdict():
    """Falsification guard: re-judging the validator's report must be rejected.

    The mutation is the shape US-PM-48 exists to remove — the orchestrator
    reads the validator's output, decides for itself and writes a generic
    ``pm_update`` — spliced into the real document so everything else about it
    stays valid.  Every clause must fail on it; if any survived, that clause
    would be matching something other than the mapping.
    """
    text = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    mutated = text.replace(
        _step(text, 18),
        "18. If the validator says nothing useful, read its output and judge "
        "the task yourself.",
    )
    assert mutated != text, "the step 18 mutation did not apply — guard inconclusive"
    step_19 = _step(mutated, 19)
    mutated = mutated.replace(
        step_19,
        "19. **Verdict**: summarise what the validator reported and write it "
        "with `pm_update(task_id, status=..., outcome=..., note=...)`.",
    )
    assert _step(mutated, 19) != step_19, (
        "the step 19 mutation did not apply — guard inconclusive"
    )

    failed = [name for name, check in CLAUSES.items() if not check(mutated)]
    assert failed == list(CLAUSES), (
        "a hand-rolled verdict passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
