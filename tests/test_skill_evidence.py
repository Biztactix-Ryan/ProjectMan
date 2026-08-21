"""US-PM-9-4 — the orchestrator skill must record evidence structurally.

Story US-PM-9's diagnosis: ``pm-orchestrate`` steps 17–18 already make the
orchestrator produce exactly three lists — files changed, test commands with
their results, DoD criteria met vs unmet — and step 19 then told it to flatten
all three into the prose ``note``.  That is why note lengths clustered at the
1024-char ceiling (Study B p90 1,067; Study A median 925 / p95 1,349), and why
"done with no evidence" was silent rather than detectable.

US-PM-9-9 rewrote the template so the lists ride in ``evidence`` and the note
goes back to being one human-readable line.  This module pins that instruction
site, for the same reason ``test_skill_verdict_verbs.py`` and
``test_skill_release_instructions.py`` exist: the fix lives in prose, and a
prose fix does not stay fixed on its own.

What is asserted, per ``docs/reference/evidence-contract.md`` §6 and §8:

* step 19's Accept call passes ``evidence=``, and the fenced example's object
  carries ``files`` / ``tests`` / ``dod_met`` with ``command`` / ``passed`` on
  the test entries;
* all four verdict bullets carry ``evidence=``, with failing ``tests`` on
  Retry/Park and ``dod_unmet`` on Park/Accept-as-review;
* step 19 states the ONE line / 200-character note rule and names ``note_long``;
* **negatively**, nothing in step 19 or the orchestrator's own flow tells it to
  put the lists *inside* the note — every ``note="..."`` argument in step 19 is
  a short placeholder, not an evidence dump;
* steps 17–18 still say to collect the three lists (without them step 19 has
  nothing to transcribe);
* the Operating Model names ``has_evidence`` and ``done-without-evidence``.

Helpers are imported from ``test_skill_verdict_verbs`` rather than copied, so
the step-19 slice and the fence stripping stay defined in exactly one place.
As there, the fenced **Worker Prompt Template** is the deliberate exception to
the flow assertions — workers self-report via ``pm_update`` — so the flow checks
strip fences and ``test_worker_prompt_fence_still_self_reports_via_pm_update``
keeps that strip non-vacuous.

Render byte-identity is *not* re-asserted here: ``test_skill_verdict_verbs.py``
already owns ``test_rendered_orchestrate_skill_is_byte_identical_to_its_template``
over this same pair of paths, and a second copy would only duplicate it.  Both
documents are checked by every test below regardless, via the shared ``DOCS``
parametrization.
"""

import re

import pytest

from tests.test_skill_verdict_verbs import (
    DOCS,
    _fences,
    _outside_fences,
    _step_19,
    _text,
)

#: the note ceiling step 19 must state, and the cap its placeholders must obey
NOTE_LIMIT = 200

#: ``evidence={...}`` as written in the skill, on any verdict bullet
EVIDENCE_KWARG = re.compile(r"\bevidence\s*=")

#: every ``note="..."`` argument, non-greedy to the closing quote — so an
#: evidence dict following the note is never swallowed into the match
NOTE_ARG = re.compile(r'\bnote\s*=\s*"([^"]*)"')

#: "in the note" is legitimate when *negated* ("never in the note"); it is the
#: regression when it is an instruction.  Look back a short window for a negator.
IN_THE_NOTE = re.compile(r"\bin(?:to)? the note\b")
NEGATOR = re.compile(r"\b(never|not|no|instead of|rather than)\b", re.IGNORECASE)

#: the pre-US-PM-9-9 Accept placeholder — the exact phrasing that asked for a
#: flattened evidence dump in the note
EVIDENCE_IN_NOTE_PLACEHOLDER = re.compile(r"evidence\s+summary", re.IGNORECASE)

#: a note argument that has started listing: "; " followed by a path or a verdict
LIST_IN_NOTE = re.compile(r";\s+(?:[^;]*[/\\][^;]*|[^;]*\b(?:passed|failed)\b)")

VERDICT_LABELS = ["Accept", "Retry", "Park", "Accept-as-review"]


def _bullet(text: str, label: str) -> str:
    """The single step-19 bullet whose bold label is ``label``."""
    bullets = [line for line in _step_19(text).splitlines() if f"**{label}**" in line]
    assert len(bullets) == 1, f"expected exactly one **{label}** bullet, got {len(bullets)}"
    return bullets[0]


def _steps_17_18(text: str) -> str:
    """The validation-gathering block: from the ``17.`` line up to ``19.``."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("17.")]
    ends = [n for n, line in enumerate(lines) if line.startswith("19.")]
    assert starts, "no line starting with '17.' — the diff-check step vanished"
    assert ends, "no line starting with '19.' — cannot bound steps 17–18"
    start = starts[0]
    end = next(n for n in ends if n > start)
    return "\n".join(lines[start:end])


# ═══ step 19 — the verdict carries structured evidence ══════════


@pytest.mark.parametrize("path", DOCS)
def test_accept_bullet_passes_evidence_to_pm_accept(path):
    """The headline change: Accept proves itself with a field, not a paragraph."""
    block = _step_19(_text(path))
    accept = _bullet(_text(path), "Accept")
    assert "pm_accept(" in accept, accept
    # the kwarg may sit on the bullet itself or in its fenced example directly
    # below it; either way it must be inside the step-19 slice.
    assert EVIDENCE_KWARG.search(block), (
        f"{path.name}: step 19 never passes evidence= — the verdict is still prose-only"
    )
    assert EVIDENCE_KWARG.search(
        block[block.index("pm_accept(") :]
    ), f"{path.name}: no evidence= at or after the pm_accept call"


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("key", ["files", "tests", "dod_met"])
def test_accept_example_names_each_evidence_list(path, key):
    """The worked example must show all three lists steps 17–18 produce."""
    block = _step_19(_text(path))
    assert f'"{key}"' in block, (
        f"{path.name}: step 19's evidence example has no {key!r} key — the "
        "orchestrator has no template for that list"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("key", ["command", "passed"])
def test_accept_example_test_entries_carry_command_and_passed(path, key):
    """A test entry without its command or its result proves nothing."""
    block = _step_19(_text(path))
    assert f'"{key}"' in block, (
        f"{path.name}: step 19's tests entries have no {key!r} field"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("label", VERDICT_LABELS)
def test_every_verdict_bullet_carries_evidence(path, label):
    """Not just the happy path — a failed attempt is exactly when evidence matters."""
    bullet = _bullet(_text(path), label)
    assert EVIDENCE_KWARG.search(bullet), (
        f"{path.name}: the **{label}** bullet passes no evidence=: {bullet.strip()!r}"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("label", ["Retry", "Park"])
def test_failing_verdicts_carry_the_failing_tests(path, label):
    """Retry and Park exist because tests failed; the failures must ride along."""
    bullet = _bullet(_text(path), label)
    assert '"tests"' in bullet, (
        f"{path.name}: the **{label}** bullet's evidence names no tests list"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("label", ["Park", "Accept-as-review"])
def test_unfinished_verdicts_record_the_unmet_criteria(path, label):
    """Park and Accept-as-review hand work to a human — say what is still open."""
    bullet = _bullet(_text(path), label)
    assert '"dod_unmet"' in bullet, (
        f"{path.name}: the **{label}** bullet's evidence names no dod_unmet list"
    )


# ═══ step 19 — the note shrinks back to one line ════════════════


@pytest.mark.parametrize("path", DOCS)
def test_step_19_states_the_one_line_note_rule(path):
    """The rule has to be *stated*, not merely implied by the example."""
    block = _step_19(_text(path))
    assert str(NOTE_LIMIT) in block, (
        f"{path.name}: step 19 never mentions the {NOTE_LIMIT}-character note cap"
    )
    assert re.search(r"\bone line\b", block, re.IGNORECASE), (
        f"{path.name}: step 19 never says the note is one line"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_19_names_note_long(path):
    """The over-write signal is useless if the orchestrator is never told it exists."""
    assert "note_long" in _step_19(_text(path)), (
        f"{path.name}: step 19 never names note_long, so an over-long note is "
        "silently truncated with nothing to react to"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_19_note_arguments_are_short_summaries_not_evidence_dumps(path):
    """The regression, stated negatively and precisely.

    Rather than guessing at every phrasing that could ask for a flattened note,
    look at what step 19 actually shows the model to type: every ``note="..."``
    argument must be a short placeholder or a short literal — within the stated
    cap, not describing itself as an evidence summary, and not already sliding
    into a semicolon-separated list of paths or pass/fail results.
    """
    notes = NOTE_ARG.findall(_step_19(_text(path)))
    assert notes, f"{path.name}: step 19 shows no note= argument at all"
    offenders = []
    for note in notes:
        if len(note) > NOTE_LIMIT:
            offenders.append(f"{len(note)} chars > {NOTE_LIMIT}: {note!r}")
        elif EVIDENCE_IN_NOTE_PLACEHOLDER.search(note):
            offenders.append(f"asks for evidence inside the note: {note!r}")
        elif LIST_IN_NOTE.search(note):
            offenders.append(f"lists paths or results inside the note: {note!r}")
    assert not offenders, f"{path.name} step 19 packs evidence into the note:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("path", DOCS)
def test_orchestrator_flow_never_instructs_putting_evidence_in_the_note(path):
    """Whole flow, fences stripped — no step may route the lists into the note.

    ``in the note`` is not forbidden outright: step 19 legitimately says the
    lists go in ``evidence``, *never* in the note.  What is forbidden is the
    un-negated instruction.
    """
    offenders = []
    for line in _outside_fences(_text(path)).splitlines():
        for match in IN_THE_NOTE.finditer(line):
            window = line[max(0, match.start() - 30) : match.start()]
            if not NEGATOR.search(window):
                offenders.append(line.strip())
    assert not offenders, (
        f"{path.name} instructs evidence into the note:\n" + "\n".join(offenders)
    )


# ═══ the surrounding contract ═══════════════════════════════════


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("term", ["files", "test", "DoD"])
def test_steps_17_18_say_to_collect_the_three_lists(path, term):
    """Step 19 is a transcription only if 17–18 produced something to transcribe."""
    block = _steps_17_18(_text(path))
    assert term.lower() in block.lower(), (
        f"{path.name}: steps 17–18 never mention {term!r}, so the {term} list "
        "step 19 records is never gathered"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("term", ["has_evidence", "done-without-evidence"])
def test_operating_model_names_the_evidence_query_and_finding(path, term):
    """Structured evidence earns its keep by being queryable and auditable."""
    assert term in _text(path), (
        f"{path.name}: the Operating Model never names {term!r}"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize(
    "pattern",
    [
        r"files changed",
        r"pass/fail|pass or fail|passed/failed",
        r"DoD items met (?:vs\.?|versus) unmet",
    ],
)
def test_worker_prompt_fence_asks_for_the_three_lists(path, pattern):
    """The orchestrator transcribes; the worker must be asked to produce.

    Whitespace is normalised first: the worker prompt is hard-wrapped inside its
    fence, so a required phrase may straddle a line break.
    """
    fenced = re.sub(r"\s+", " ", "\n".join(_fences(_text(path))))
    assert re.search(pattern, fenced, re.IGNORECASE), (
        f"{path.name}: the worker prompt never asks for {pattern!r}, so step 19 "
        "has nothing to transcribe"
    )


@pytest.mark.parametrize("path", DOCS)
def test_worker_prompt_fence_still_self_reports_via_pm_update(path):
    """Guard on the fence stripping used by the flow assertion above.

    Workers self-report with ``pm_update``; the orchestrator passes verdicts by
    verb.  If the fenced worker prompt ever stops mentioning ``pm_update``, the
    fence stripping has stopped excluding anything and the negative flow test
    would be passing for the wrong reason.
    """
    assert "pm_update" in "\n".join(_fences(_text(path))), (
        f"{path.name}: no fenced block mentions pm_update — the worker prompt "
        "changed, so the fence-stripping in this module needs re-checking"
    )
