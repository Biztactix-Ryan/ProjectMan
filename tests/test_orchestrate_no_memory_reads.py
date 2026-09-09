"""US-PM-49-4 — the orchestrate skill must forbid memory and transcript reads.

Story US-PM-49 is about the bytes the orchestrator itself spends.  Two of the
fattest reads measured on the Kura runs were not store traffic at all: the
orchestrator ``cat``-ed its own memory files, 15 KB and 7 KB, before the first
dispatch — context spent on prose that no verdict depends on, since every fact
a verdict needs is either in the store or in the repo.  Session transcripts are
the same failure one order of magnitude worse.  So the acceptance criterion
pinned here is —

    "The orchestrate skill forbids reading memory files or session transcripts
    during a run"

— and US-PM-49-8 made the change, as the ``**Reads**:`` rule that closes the
operating-model paragraph.  This module holds it, clause by clause, on that
rule.

Three documents are checked: the Jinja template (source of truth), the tracked
rendered ``.claude/skills/pm-orchestrate/SKILL.md`` (what an orchestrating
agent actually loads) and a live render of the template, so a template edit
that never survives the renderer is caught even before the byte-for-byte
equality test in ``test_orchestrate_skill_size.py`` fires.

One test looks past the rule: a prohibition stated once in the header is worth
nothing if a numbered step further down still tells the orchestrator to ``cat``
a memory file or tail a ``.jsonl`` transcript, so the rest of the skill is
swept for exactly that, and the sweep is itself falsified against a planted
step.

The remaining tests are falsification guards — the pre-US-PM-49-8 paragraph,
which said nothing about reads at all; a vague "reading costs context, go easy"
note; and a hedged near-miss that names memory files and transcripts but only
*recommends* avoiding them — are pushed through the same clause table and must
fail.  A checklist that never fires is not evidence.

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

#: the label that opens the rule inside the operating-model paragraph
READS_LABEL = re.compile(r"\*\*Reads\*\*", re.IGNORECASE)

# ─── what the rule must allow ────────────────────────────────────

#: the store is the sanctioned source — named as tools, not as files
STORE_TOOLS = re.compile(r"\bstore\s+tools?\b|\bpm_[a-z_]+\(", re.IGNORECASE)

#: and the repo files a verdict actually turns on
VERDICT_FILES = re.compile(
    r"\bfiles?\b[^.;]{0,40}\bverdicts?\b|\bverdicts?\b[^.;]{0,40}\bfiles?\b",
    re.IGNORECASE,
)

# ─── what it must forbid ─────────────────────────────────────────

#: an absolute negation — "avoid", "prefer not to" and friends are *not* here
FORBID = r"(?:never|must\s+not|do\s+not|don't|no|not)"

#: one sentence's worth of filler — dots inside paths like ``~/.claude`` are
#: kept, a full stop followed by space or end is not, so a negation in one
#: sentence cannot be paired with a noun in the next.
SAME_SENTENCE = r"(?:(?!\.(?:\s|$))[^;\n])"

#: ``never memory files under `~/.claude``` and the ways of writing it
NEVER_MEMORY = re.compile(
    rf"\b{FORBID}\b{SAME_SENTENCE}{{0,90}}\bmemor(?:y|ies)\b"
    rf"{SAME_SENTENCE}{{0,60}}~/\.claude",
    re.IGNORECASE,
)

#: ``… or transcripts`` under the same negation
NEVER_TRANSCRIPT = re.compile(
    rf"\b{FORBID}\b{SAME_SENTENCE}{{0,140}}\b(?:session\s+)?transcripts?\b",
    re.IGNORECASE,
)

#: qualifiers that turn a rule back into advice
HEDGE = re.compile(
    r"\bprefer(?:ably|red)?\b|\btry\s+to\b|\bavoid\b|\bideally\b|\bconsider\b"
    r"|\bshould\b|\bgenerally\b|\busually\b|\bmostly\b|\bif\s+you\s+can\b"
    r"|\b(?:where|when|if)\s+possible\b|\bunless\b|\bexcept\b|\bgo\s+easy\b",
    re.IGNORECASE,
)

# ─── reads planted elsewhere in the skill ────────────────────────

#: anything that fetches a file's bytes, shell or tool
READ_INSTRUCTION = (
    r"(?:\b(?:cat|head|tail|less|more|grep|sed|awk|open|opens|read|reads"
    r"|load|loads|inspect|dump|review)\b|\bRead\()"
)

#: the two targets the criterion names
FORBIDDEN_TARGET = r"(?:~/\.claude|\.jsonl\b)"

READ_OF_FORBIDDEN = re.compile(
    rf"(?:{READ_INSTRUCTION}[^\n]{{0,80}}{FORBIDDEN_TARGET}"
    rf"|{FORBIDDEN_TARGET}[^\n]{{0,80}}{READ_INSTRUCTION})",
    re.IGNORECASE,
)

#: a step that so much as names them is already too close
NAMES_FORBIDDEN = re.compile(FORBIDDEN_TARGET, re.IGNORECASE)


# ─── the slice ───────────────────────────────────────────────────


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def _operating_model(text: str) -> str:
    """The operating-model paragraph — the bold run of standing rules."""
    blocks = [block for block in _paragraphs(text) if READS_LABEL.search(block)]
    assert blocks, (
        "no paragraph carries a '**Reads**' rule — the read prohibition vanished"
    )
    assert len(blocks) == 1, f"'**Reads**' appears in {len(blocks)} paragraphs"
    block = blocks[0]
    head = text.split("## Phase 0")[0]
    assert block in head, (
        "the '**Reads**' rule is buried inside a phase, not in the standing "
        f"operating model every step is read under:\n\n{block}"
    )
    return block


def _reads_rule(text: str) -> str:
    """The ``**Reads**:`` clause itself, to the end of its paragraph."""
    block = _operating_model(text)
    return block[READS_LABEL.search(block).start() :].strip()


def _outside_the_rule(text: str) -> list[tuple[int, str]]:
    """Every numbered line of the skill that is not the operating model."""
    rule_lines = set(_operating_model(text).splitlines())
    return [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line not in rule_lines
    ]


# ─── clause table ────────────────────────────────────────────────
#
# Iterated by the tests *and* by the falsification guards, so a clause cannot
# be checked in one place and quietly dropped from the other.


def _restricts_reads_to_the_store_and_verdict_files(rule: str) -> bool:
    return bool(STORE_TOOLS.search(rule) and VERDICT_FILES.search(rule))


def _forbids_memory_files_under_claude(rule: str) -> bool:
    return bool(NEVER_MEMORY.search(rule))


def _forbids_session_transcripts(rule: str) -> bool:
    return bool(NEVER_TRANSCRIPT.search(rule))


def _is_a_rule_not_advice(rule: str) -> bool:
    forbids = NEVER_MEMORY.search(rule) or NEVER_TRANSCRIPT.search(rule)
    return bool(forbids) and not HEDGE.search(rule)


CLAUSES = {
    "restricts reads to store tools and the files a verdict needs": (
        _restricts_reads_to_the_store_and_verdict_files
    ),
    "forbids memory files under ~/.claude": _forbids_memory_files_under_claude,
    "forbids session transcripts": _forbids_session_transcripts,
    "phrases the prohibition as a rule, not advice": _is_a_rule_not_advice,
}


# ─── the documents ───────────────────────────────────────────────

SOURCES = {
    "template": lambda: _text(ORCHESTRATE_TEMPLATE),
    "rendered": lambda: _text(ORCHESTRATE_SKILL),
    "live-render": lambda: _render_template(ORCHESTRATE_TEMPLATE_NAME),
}


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_reads_rule_is_extractable(source):
    """Guard the slice: every assertion below is scoped to this text."""
    text = SOURCES[source]()
    assert "template not found" not in text, "the template failed to render"
    rule = _reads_rule(text)
    assert READS_LABEL.match(rule), "the slice does not start at the '**Reads**' label"
    assert len(rule) > 40, "the '**Reads**' rule lost its body — a label forbids nothing"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_the_skill_forbids_memory_and_transcript_reads(source, clause):
    """The acceptance criterion, one clause per case, on all three documents."""
    rule = _reads_rule(SOURCES[source]())
    assert CLAUSES[clause](rule), f"the '**Reads**' rule fails: {clause}\n\n{rule}"


@pytest.mark.parametrize("source", list(SOURCES), ids=list(SOURCES))
def test_no_step_elsewhere_instructs_a_memory_or_transcript_read(source):
    """A rule in the header is void if a step below still orders the read."""
    text = SOURCES[source]()
    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in _outside_the_rule(text)
        if READ_OF_FORBIDDEN.search(line)
    ]
    assert not offenders, (
        "steps outside the '**Reads**' rule instruct a read of a memory file "
        "or a transcript:\n\n" + "\n".join(offenders)
    )
    named = [
        f"line {number}: {line.strip()}"
        for number, line in _outside_the_rule(text)
        if NAMES_FORBIDDEN.search(line)
    ]
    assert not named, (
        "`~/.claude` or a `.jsonl` transcript is named outside the rule that "
        "forbids reading them:\n\n" + "\n".join(named)
    )


def test_the_sweep_catches_a_planted_memory_read():
    """Falsification guard: the sweep must fire on the read it is looking for."""
    planted = [
        "5. `cat ~/.claude/projects/-repo/memory/MEMORY.md` — recall the last run.",
        "6. Read the run's `~/.claude/history.jsonl` for what the worker did.",
        "7. `tail -n 200 sessions/abc.jsonl` — the worker's transcript.",
    ]
    missed = [line for line in planted if not READ_OF_FORBIDDEN.search(line)]
    assert not missed, f"the sweep missed planted memory/transcript reads: {missed}"


def test_the_clause_checks_reject_the_paragraph_before_the_rule():
    """Falsification guard: the pre-US-PM-49-8 paragraph must fail every clause."""
    before = (
        "**Sequential**. **Stage-only**: no `git commit`, `git push`, `pm_commit`, "
        "`pm_push`. **Park, don't halt**: a twice-failed task is parked, the loop "
        "goes on. **Every verdict is logged**: verbs need a note and append a "
        "run-log entry (`pm_run_log(id, has_evidence=true)`)."
    )
    failed = [name for name, check in CLAUSES.items() if not check(before)]
    assert failed == list(CLAUSES), (
        "the paragraph without a reads rule passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


def test_the_clause_checks_reject_a_vague_note_about_reading_less():
    """Falsification guard: prose that merely sounds frugal fails every clause."""
    vague = (
        "**Reads**: reading costs context — big memory files and long transcripts "
        "add up over a run, so go easy on them."
    )
    failed = [name for name, check in CLAUSES.items() if not check(vague)]
    assert failed == list(CLAUSES), (
        "a vague note about reading less passed these clauses: "
        f"{[n for n in CLAUSES if n not in failed]}"
    )


def test_the_clause_checks_reject_a_hedged_recommendation():
    """Falsification guard: naming the files is not forbidding them.

    Without this, a rule that lists memory files and transcripts and then only
    *prefers* skipping them would pass — and a preference is exactly what the
    orchestrator talked itself out of on the runs that motivated the criterion.
    """
    hedged = (
        "**Reads**: prefer store tools and the files a verdict needs, and try to "
        "avoid memory files under `~/.claude` or transcripts where possible."
    )
    must_fail = [
        "forbids memory files under ~/.claude",
        "forbids session transcripts",
        "phrases the prohibition as a rule, not advice",
    ]
    passed = [name for name in must_fail if CLAUSES[name](hedged)]
    assert not passed, f"a hedged recommendation passed these clauses: {passed}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
