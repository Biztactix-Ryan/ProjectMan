"""US-PM-25-4 — the numbers the skills quote must agree with each other and with the code.

Story US-PM-25's diagnosis listed four numeric contradictions across the skill
templates and the reference docs: task points given as ``1-3`` in one place and
``1-5`` in another; the audit check count given as 13 and as 16; the skill count
given as 5 and as 7; and both ``pm_done_next`` *and* ``pm_accept`` described as
"the call that closes a story" as though only one of them did.

US-PM-25-8 reconciled them.  This file is the regression fence, and it pins each
number to its *source in code* rather than to a second copy of the prose:

* **task points** — every point range quoted anywhere is ``1-5``, never ``1-3``,
  and ``5`` is a real point value on the fibonacci scale ``pm_estimate`` hands
  out (``projectman.models.FIBONACCI_POINTS``, reached through
  ``estimator.estimate``, which is the whole body of ``pm_estimate``).
* **audit checks** — no template states a count at all; the table in
  ``docs/reference/cli.md`` is the canonical list and must have exactly one row
  per check in ``audit.run_audit``.  ``audit.py``'s ``# Check N:`` comments
  duplicate the number 7 (two different checks are both "Check 7"), so the
  count taken from code here is the number of ``# Check N:`` *blocks*, never the
  largest N.  The finer-grained ``"check": "<slug>"`` vocabulary is asserted to
  be a refinement of that count, not a contradiction of it: several rows (docs,
  hub docs, criteria drift) legitimately emit more than one slug.
* **skill count** — ``docs/reference/skills.md`` is the single site allowed to
  state it, it must equal ``len(cli.CLAUDE_SKILLS)``, and the names it lists
  must be exactly the installed skill names.
* **story closing** — asserted structurally in ``server.py``: ``pm_accept`` and
  ``pm_done_next`` share one body (``_do_accept``) and that body is the only one
  of the three that closes the parent story; ``pm_update`` does not.  Every
  block of prose that claims something closes a story must name one of the two
  calls that actually do, and nothing may say ``pm_update`` closes it.

Finally, every tracked rendered copy under ``.claude/`` must be byte-identical
to the template it came from, so a reconciled template cannot ship with a stale
``SKILL.md`` beside it.
"""

import ast
import re
from pathlib import Path

import pytest

from projectman import audit as audit_mod
from projectman import cli as cli_mod
from projectman import estimator as estimator_mod
from projectman.cli import CLAUDE_SKILLS, _render_template
from projectman.models import FIBONACCI_POINTS

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"
DOCS = REPO_ROOT / "docs" / "reference"
RENDERED_SKILLS = REPO_ROOT / ".claude" / "skills"
RENDERED_AGENT = REPO_ROOT / ".claude" / "agents" / "pm.md"

SKILLS_DOC = DOCS / "skills.md"
AGENT_DOC = DOCS / "agent.md"
CLI_DOC = DOCS / "cli.md"

TEMPLATE_FILES = sorted(TEMPLATES.glob("*.j2"))
DOC_FILES = [SKILLS_DOC, AGENT_DOC, CLI_DOC]
ALL_FILES = TEMPLATE_FILES + DOC_FILES


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _numbered_lines(text: str):
    """(lineno, line) pairs, 1-based, so a failure can point at file:line."""
    return list(enumerate(text.splitlines(), start=1))


NEW_BLOCK = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s|\|)")


def _blocks(text: str):
    """Claim-sized chunks: (first_lineno, joined_text).

    A claim about story closing is routinely spread over a *wrapped* bullet
    (``agent_pm.md.j2`` names ``pm_done_next`` on one line and says "closes the
    parent story" on the next), so line-at-a-time matching would be wrong.  But
    a whole markdown paragraph is too coarse the other way: ``pm-status``'s
    dashboard list puts "suggest closing it via ``/pm-plan``" (a *sprint*) one
    bullet above "Story/task counts", and joining them invents a claim neither
    bullet makes.  So a block is one list item / heading / table row plus its
    indented continuation lines, and blank lines still separate.
    """
    out = []
    start = None
    buf: list[str] = []

    def flush():
        nonlocal start, buf
        if buf:
            out.append((start, " ".join(buf)))
        start, buf = None, []

    for lineno, line in _numbered_lines(text):
        if not line.strip():
            flush()
            continue
        if NEW_BLOCK.match(line):
            flush()
        if start is None:
            start = lineno
        buf.append(line.strip())
    flush()
    return out


def _server_source() -> str:
    return _read(REPO_ROOT / "src" / "projectman" / "server.py")


def _func_source(source: str, name: str) -> str:
    """Source of a top-level ``def name`` in ``source`` (decorators stripped)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None, f"could not slice source of {name}"
            return segment
    raise AssertionError(f"server.py defines no function named {name!r}")


# --------------------------------------------------------------------------
# 1. Task point range
# --------------------------------------------------------------------------

# "1-5 points", "1 – 5 points", "1-5 point".  The unit word is required so that
# ids like `US-PRJ-1-3` and prose like "every 3 accepted tasks" cannot match.
POINT_RANGE = re.compile(r"\b(\d+)\s*[-–]\s*(\d+)\s*points?\b")
# The specific falsified claim, matched on its own so its absence is explicit.
ONE_TO_THREE = re.compile(r"\b1\s*[-–]\s*3\s*points?\b")


def test_pm_estimate_hands_out_the_fibonacci_scale_containing_five():
    """The 5 in "1-5 points" has to be a point value the server accepts."""
    server = _server_source()
    estimate_body = _func_source(server, "pm_estimate")
    assert "estimator" in estimate_body and "estimate(store, id)" in estimate_body, (
        "pm_estimate no longer delegates to estimator.estimate — the scale this "
        "test reads is no longer the scale the tool documents"
    )
    estimator_src = _read(Path(estimator_mod.__file__))
    assert "FIBONACCI_POINTS" in estimator_src, (
        "estimator.estimate no longer sources its scale from models.FIBONACCI_POINTS"
    )
    assert 5 in FIBONACCI_POINTS, f"5 is not on the fibonacci scale {sorted(FIBONACCI_POINTS)}"
    assert 1 in FIBONACCI_POINTS

    # The docstrings that spell the scale inline must spell the same one.
    spelled = set(re.findall(r"fibonacci:\s*([0-9,\s]+?)\)", server))
    assert spelled, "server.py no longer spells the fibonacci scale in any docstring"
    for literal in spelled:
        values = {int(v) for v in re.findall(r"\d+", literal)}
        assert values == set(FIBONACCI_POINTS), (
            f"server.py docstring spells fibonacci as {sorted(values)}, "
            f"models.FIBONACCI_POINTS is {sorted(FIBONACCI_POINTS)}"
        )


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_point_range_is_one_to_five(path):
    text = _read(path)
    for lineno, line in _numbered_lines(text):
        assert not ONE_TO_THREE.search(line), (
            f"{path}:{lineno} still quotes the falsified task range 1-3 points: {line.strip()}"
        )
        for match in POINT_RANGE.finditer(line):
            low, high = int(match.group(1)), int(match.group(2))
            if low != 1:
                # Story-sized ranges (e.g. 5-13) are a different scale; only
                # assert they stay on the fibonacci ladder.
                assert low in FIBONACCI_POINTS and high in FIBONACCI_POINTS, (
                    f"{path}:{lineno} quotes {match.group(0)!r}, off the fibonacci scale"
                )
                continue
            assert high == 5, (
                f"{path}:{lineno} quotes the task point range as {match.group(0)!r}; "
                "every other site says 1-5 points"
            )


def test_the_one_to_five_range_is_actually_stated_somewhere():
    """Guard against the point assertions passing because nothing mentions points."""
    hits = [
        f"{path}:{lineno}"
        for path in ALL_FILES
        for lineno, line in _numbered_lines(_read(path))
        if POINT_RANGE.search(line)
    ]
    assert hits, "no file states a point range at all — the range assertions are vacuous"


def test_scoper_guidance_agrees_with_the_templates():
    """The code path that generates task guidance says 1-5 too."""
    scoper_src = _read(REPO_ROOT / "src" / "projectman" / "scoper.py")
    assert not ONE_TO_THREE.search(scoper_src), "scoper.py still emits a 1-3 point range"
    assert "1-5 points" in scoper_src, "scoper.py no longer emits the 1-5 task point range"


# --------------------------------------------------------------------------
# 2. Audit check count
# --------------------------------------------------------------------------

CHECK_COMMENT = re.compile(r"^\s*#\s*Check\s+(\d+)\s*:", re.MULTILINE)
# "13 checks", "all 16 audit checks", "sixteen checks".  Plural only: the
# orchestrate skill's "**Health check** every 3 accepted tasks" is not a count.
CHECK_COUNT_CLAIM = re.compile(
    r"\b(?:\d{1,2}|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s+(?:[\w-]+\s+){0,2}checks\b",
    re.IGNORECASE,
)


def audit_check_count_from_code() -> int:
    """How many checks ``run_audit`` performs, taken from the code.

    ``audit.py`` numbers its checks in comments and the numbering is wrong —
    two distinct checks are both labelled ``# Check 7`` — so ``max(N)`` is off
    by one and must not be used.  The reliable count is the number of
    ``# Check N:`` blocks.
    """
    source = _read(Path(audit_mod.__file__))
    return len(CHECK_COMMENT.findall(source))


def test_audit_check_numbering_is_known_to_be_duplicated():
    """Pin the reason we count blocks, not numbers — so this stays honest."""
    source = _read(Path(audit_mod.__file__))
    numbers = [int(n) for n in CHECK_COMMENT.findall(source)]
    assert numbers, "audit.py no longer marks its checks with `# Check N:` comments"
    if len(set(numbers)) == len(numbers):
        # The duplicate was fixed; then max(N) and the block count must agree.
        assert max(numbers) == len(numbers), (
            f"audit.py check comments are now unique but not contiguous: {numbers}"
        )
    else:
        duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
        assert max(numbers) < len(numbers), (
            f"audit.py duplicates check numbers {duplicated} yet max(N) still equals "
            "the block count — recheck how the count is derived"
        )


def test_cli_doc_check_table_has_one_row_per_check_in_the_code():
    code_count = audit_check_count_from_code()
    text = _read(CLI_DOC)
    marker = text.index("**Checks performed**")
    section = text[marker:]
    rows = [
        (lineno, line)
        for lineno, line in enumerate(section.splitlines(), start=text[:marker].count("\n") + 1)
        if re.match(r"^\|\s*\d+\s*\|", line)
    ]
    numbers = [int(re.match(r"^\|\s*(\d+)\s*\|", line).group(1)) for _, line in rows]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"{CLI_DOC} check table is not numbered 1..N: {numbers}"
    )
    assert len(rows) == code_count, (
        f"{CLI_DOC} check table has {len(rows)} rows but audit.run_audit performs "
        f"{code_count} checks"
    )


def test_check_slugs_are_a_refinement_of_the_table_not_a_contradiction():
    """Several rows fan out into more than one finding slug; none fans out to zero."""
    source = _read(Path(audit_mod.__file__))
    slugs = set(re.findall(r'"check":\s*"([a-z0-9-]+)"', source))
    code_count = audit_check_count_from_code()
    assert len(slugs) >= code_count, (
        f"audit.py emits {len(slugs)} distinct check slugs for {code_count} checks — "
        "at least one check emits no finding"
    )


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.name)
def test_no_template_states_an_audit_check_count(path):
    for lineno, line in _numbered_lines(_read(path)):
        match = CHECK_COUNT_CLAIM.search(line)
        assert match is None, (
            f"{path}:{lineno} states an audit check count ({match.group(0)!r}); "
            f"{CLI_DOC.name}'s table is the canonical list and the only place it is counted"
        )


def test_the_canonical_check_table_says_it_is_canonical():
    text = _read(CLI_DOC)
    assert "canonical list" in text, (
        f"{CLI_DOC} no longer declares its check table the canonical list, so nothing "
        "tells the other docs to link here instead of repeating a count"
    )


# --------------------------------------------------------------------------
# 3. Skill count
# --------------------------------------------------------------------------

SKILL_COUNT_CLAIM = re.compile(
    r"\b(\d{1,2}|four|five|six|seven|eight|nine|ten)\s+(?:[\w-]+\s+){0,3}skills\b",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _skill_count_claims(text: str):
    for lineno, line in _numbered_lines(text):
        for match in SKILL_COUNT_CLAIM.finditer(line):
            token = match.group(1).lower()
            value = int(token) if token.isdigit() else _WORD_NUMBERS[token]
            yield lineno, value, match.group(0)


def test_skills_doc_states_the_installed_skill_count():
    claims = list(_skill_count_claims(_read(SKILLS_DOC)))
    assert claims, f"{SKILLS_DOC} no longer states the skill count"
    for lineno, value, snippet in claims:
        assert value == len(CLAUDE_SKILLS), (
            f"{SKILLS_DOC}:{lineno} says {snippet!r}; cli.CLAUDE_SKILLS installs "
            f"{len(CLAUDE_SKILLS)}"
        )


def test_skills_doc_lists_exactly_the_installed_skills():
    text = _read(SKILLS_DOC)
    installed = [name for name, _ in CLAUDE_SKILLS]
    headings = re.findall(r"^##\s+/([\w-]+)\s*$", text, re.MULTILINE)
    assert len(headings) == len(set(headings)), (
        f"{SKILLS_DOC} documents a skill twice: {headings}"
    )
    # Order is presentation, not a claim; membership is the claim.
    assert set(headings) == set(installed), (
        f"{SKILLS_DOC} documents {sorted(headings)}; cli.CLAUDE_SKILLS installs "
        f"{sorted(installed)}"
    )
    # The counting sentence must also name them all, so the count and the list
    # cannot drift apart within the one paragraph that owns both.
    sentence = next(line for line in text.splitlines() if SKILL_COUNT_CLAIM.search(line))
    for name in installed:
        assert f"/{name}`" in sentence or f"/{name} " in sentence or f"/{name}," in sentence, (
            f"{SKILLS_DOC}'s counting sentence does not name /{name}"
        )


@pytest.mark.parametrize(
    "path", TEMPLATE_FILES + [AGENT_DOC, CLI_DOC], ids=lambda p: p.name
)
def test_only_the_skills_doc_states_the_skill_count(path):
    claims = list(_skill_count_claims(_read(path)))
    assert not claims, "; ".join(
        f"{path}:{lineno} states a skill count ({snippet!r}) — "
        f"{SKILLS_DOC.name} is the single site for it"
        for lineno, _value, snippet in claims
    )


def test_installed_skill_templates_all_exist():
    for name, template_name in CLAUDE_SKILLS:
        assert (TEMPLATES / template_name).is_file(), (
            f"CLAUDE_SKILLS lists {name} -> {template_name}, which does not exist"
        )


# --------------------------------------------------------------------------
# 4. Which call closes a story
# --------------------------------------------------------------------------

CLOSE_CLAIM = re.compile(
    r"\bclos(?:e|es|ed|ing)\b[^.]{0,80}\bstory\b|\bstory\b[^.]{0,80}\bclos(?:e|es|ed|ing)\b",
    re.IGNORECASE,
)
# "pm_update ... closes": the active claim only.  "the story must then be
# closed explicitly" (passive, and true) is a different sentence shape.
PM_UPDATE_CLOSES = re.compile(
    r"pm_update[^.]{0,80}\b(?:closes|auto-closes|will close)\b"
    r"|\b(?:closes|auto-closes)\b[^.]{0,80}pm_update",
    re.IGNORECASE,
)


def test_pm_accept_and_pm_done_next_share_the_body_that_closes_the_story():
    server = _server_source()
    shared = _func_source(server, "_do_accept")
    assert "story_closed" in shared, (
        "_do_accept no longer records story_closed — it is not the call that closes a story"
    )
    assert re.search(r'store\.update\(\s*story_id', shared), (
        "_do_accept no longer writes the parent story"
    )
    for name in ("pm_accept", "pm_done_next"):
        body = _func_source(server, name)
        assert "_do_accept(" in body, f"{name} no longer delegates to _do_accept"


def test_pm_update_does_not_close_the_story():
    server = _server_source()
    body = _func_source(server, "pm_update")
    assert "_do_accept" not in body, "pm_update now routes through the story-closing body"
    assert "story_closed" not in body, "pm_update now reports story_closed"


def test_worker_set_done_is_the_documented_already_done_path():
    server = _server_source()
    shared = _func_source(server, "_do_accept")
    assert "already_done" in shared, (
        "_do_accept no longer answers already_done for a task already marked done — "
        "the orchestrate skill's warning to workers would be false"
    )


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_story_closing_prose_names_a_call_that_actually_closes(path):
    text = _read(path)
    for lineno, block in _blocks(text):
        if not CLOSE_CLAIM.search(block):
            continue
        assert "pm_accept" in block or "pm_done_next" in block, (
            f"{path}:{lineno} talks about closing a story without naming pm_accept "
            f"or pm_done_next, the only calls that do: {block[:160]!r}"
        )


def test_story_closing_is_actually_discussed_somewhere():
    """Keep the positive assertion above from passing because nothing matches."""
    hits = [
        f"{path.name}:{lineno}"
        for path in ALL_FILES
        for lineno, block in _blocks(_read(path))
        if CLOSE_CLAIM.search(block)
    ]
    assert len(hits) >= 4, (
        f"only {hits} discuss closing a story — the block splitting has gone "
        "vacuous and the assertions above no longer check anything"
    )


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_nothing_says_pm_update_closes_a_story(path):
    for lineno, block in _blocks(_read(path)):
        match = PM_UPDATE_CLOSES.search(block)
        assert match is None, (
            f"{path}:{lineno} claims pm_update closes the story ({match.group(0)!r}); "
            "only pm_accept / pm_done_next do"
        )


def test_orchestrate_template_forbids_workers_marking_done():
    template = TEMPLATES / "skill_pm_orchestrate.md.j2"
    text = _read(template)
    lowered = text.lower()
    assert re.search(r"do not mark the task done|never mark the task done", lowered), (
        f"{template} no longer tells workers not to mark the task done"
    )
    assert "already_done" in text, (
        f"{template} no longer says a worker-set done makes pm_accept answer already_done"
    )
    assert re.search(r"worker-set done[^.]{0,80}already_done", text), (
        f"{template} mentions already_done but no longer ties it to a worker-set done"
    )


# --------------------------------------------------------------------------
# 5. Rendered copies under .claude/ match their templates
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name,template_name", CLAUDE_SKILLS, ids=[n for n, _ in CLAUDE_SKILLS])
def test_rendered_skill_is_byte_identical_to_its_template(name, template_name):
    rendered = RENDERED_SKILLS / name / "SKILL.md"
    assert rendered.is_file(), f"{rendered} is missing — run `projectman setup-claude`"
    assert rendered.read_text(encoding="utf-8") == _render_template(template_name), (
        f"{rendered} has drifted from {TEMPLATES / template_name}"
    )


def test_rendered_agent_is_byte_identical_to_its_template():
    assert RENDERED_AGENT.is_file(), f"{RENDERED_AGENT} is missing"
    assert RENDERED_AGENT.read_text(encoding="utf-8") == _render_template("agent_pm.md.j2"), (
        f"{RENDERED_AGENT} has drifted from {TEMPLATES / 'agent_pm.md.j2'}"
    )


def test_render_template_is_not_silently_swallowing_a_missing_template():
    """`_render_template` returns a stub on any failure — make sure it did not."""
    for _, template_name in CLAUDE_SKILLS:
        rendered = _render_template(template_name)
        assert "template not found" not in rendered, (
            f"{template_name} failed to render; the equality assertions above would "
            "compare two stubs"
        )
        assert len(rendered) > 200, f"{template_name} rendered suspiciously short"
    assert cli_mod.CLAUDE_SKILLS is CLAUDE_SKILLS
