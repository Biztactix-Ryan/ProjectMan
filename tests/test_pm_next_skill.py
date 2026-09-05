"""US-PM-28-7 — ``/pm-next`` ships like every other pm skill.

The acceptance criterion is "``/pm-next`` skill is rendered by refresh-skills
and documented alongside the other pm skills", which is three separate things
that can each rot on their own:

1. **Rendered by refresh-skills.**  ``refresh-skills`` renders whatever is in
   ``cli.CLAUDE_SKILLS``, so registration *is* the wiring — a template that
   exists but is unregistered installs nowhere.  Asserted through the same
   ``_render_template`` the CLI calls, so a template that fails to load (which
   ``_render_template`` swallows into a ``# ... template not found`` stub) is
   caught rather than silently shipped.
2. **The tracked rendered copy matches.**  ``.claude/skills/pm-next/SKILL.md``
   is what a checkout of this repo actually loads; the templates carry no Jinja
   variables, so it must be a byte copy, and a one-sided edit would otherwise
   ship.
3. **The skill says what the tool does.**  ``pm_next`` has three modes and a
   modifier, and a skill that names only the read is a skill that never writes
   the note.  Each is pinned as the *call form* the agent would emit, not as
   prose about it.

The documentation half is pinned here too — the ``## /pm-next`` heading in the
skills reference and a user-guide section — while the count itself stays where
US-PM-25-4 put it, asserted against ``len(CLAUDE_SKILLS)`` in
``tests/test_skill_numbers_agree.py`` rather than duplicated here.

This module only reads the repository.
"""

import re
from pathlib import Path

from projectman.cli import CLAUDE_SKILLS, _render_template

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"

TEMPLATE_NAME = "skill_pm_next.md.j2"
TEMPLATE = TEMPLATES / TEMPLATE_NAME
RENDERED = REPO_ROOT / ".claude" / "skills" / "pm-next" / "SKILL.md"

SKILLS_DOC = REPO_ROOT / "docs" / "reference" / "skills.md"
USER_GUIDE = REPO_ROOT / "docs" / "user-guide" / "daily-workflow.md"

#: the three modes of ``pm_next``, plus the modifier, as the skill must spell
#: them — a call form, so prose mentioning the word does not satisfy the check
MODES = {
    "read": re.compile(r"`?pm_next\(\)"),
    "write": re.compile(r"`?pm_next\(text="),
    "clear": re.compile(r"`?pm_next\(clear=true\)"),
    "append": re.compile(r"\bappend=true\b"),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_skill_is_registered_so_refresh_skills_renders_it():
    """Registration is the wiring: refresh-skills iterates CLAUDE_SKILLS."""
    assert ("pm-next", TEMPLATE_NAME) in CLAUDE_SKILLS, (
        f"cli.CLAUDE_SKILLS does not map pm-next -> {TEMPLATE_NAME}; "
        "refresh-skills would install every skill but this one"
    )


def test_the_template_exists_and_renders():
    """`_render_template` swallows failures into a stub — make sure it did not."""
    assert TEMPLATE.is_file(), f"{TEMPLATE} is missing"
    rendered = _render_template(TEMPLATE_NAME)
    assert "template not found" not in rendered, (
        f"{TEMPLATE_NAME} failed to render; refresh-skills would install a stub"
    )
    assert rendered == _text(TEMPLATE), (
        f"{TEMPLATE_NAME} renders to something other than its own text — it has "
        "grown a Jinja variable, and the tracked rendered copy can no longer be "
        "a byte copy of it"
    )


def test_the_tracked_rendered_copy_is_byte_identical_to_the_template():
    """`.claude/skills/pm-next/SKILL.md` is what a checkout loads."""
    assert RENDERED.is_file(), f"{RENDERED} is missing — run `projectman setup-claude`"
    assert _text(RENDERED) == _render_template(TEMPLATE_NAME), (
        f"{RENDERED} has drifted from {TEMPLATE}"
    )


def test_the_skill_frontmatter_names_the_skill():
    for path in (TEMPLATE, RENDERED):
        text = _text(path)
        assert text.startswith("---\n"), f"{path.name}: no frontmatter block"
        block = text.split("---\n", 2)[1]
        assert re.search(r"^name:\s*pm-next\s*$", block, re.MULTILINE), (
            f"{path.name}: frontmatter does not declare `name: pm-next`"
        )
        assert re.search(r"^description:\s*\S", block, re.MULTILINE), (
            f"{path.name}: frontmatter carries no description, so the skill is "
            "undiscoverable from a natural-language request"
        )


def test_the_skill_instructs_every_mode_of_pm_next():
    """A skill that names only the read never writes or retires a note."""
    for path in (TEMPLATE, RENDERED):
        text = _text(path)
        missing = [name for name, pattern in MODES.items() if not pattern.search(text)]
        assert not missing, (
            f"{path.name}: names no call for {missing} — "
            f"pm_next has three modes ({sorted(MODES)}) and the skill must instruct each"
        )


def test_the_skill_offers_to_clear_a_finished_note():
    """The note has a short life; nothing else prompts its retirement."""
    for path in (TEMPLATE, RENDERED):
        text = _text(path)
        assert re.search(r"offer to clear", text, re.IGNORECASE), (
            f"{path.name}: never offers to clear the note once the work it "
            "describes is finished — stale notes are what the offer prevents"
        )


def test_the_skill_says_the_note_surfaces_without_being_asked_for():
    """`pm_context` returns it under `next_time`; the skill must say so."""
    for path in (TEMPLATE, RENDERED):
        text = _text(path)
        assert "pm_context" in text and "next_time" in text, (
            f"{path.name}: does not say pm_context returns the note under "
            "`next_time` — a user who has to remember the note exists does not "
            "need the note"
        )


def test_the_skills_reference_documents_pm_next():
    text = _text(SKILLS_DOC)
    headings = re.findall(r"^##\s+/([\w-]+)\s*$", text, re.MULTILINE)
    assert "pm-next" in headings, (
        f"{SKILLS_DOC} has no `## /pm-next` section; it documents {sorted(headings)}"
    )
    section = text.split("## /pm-next", 1)[1].split("\n## ", 1)[0]
    assert "pm_next" in section, f"{SKILLS_DOC}: the /pm-next section never names pm_next"
    assert ".project/NEXT.md" in section, (
        f"{SKILLS_DOC}: the /pm-next section does not say where the note is stored"
    )


def test_the_user_guide_has_a_section_on_the_note():
    text = _text(USER_GUIDE)
    assert re.search(r"^##\s+A Note to the Next Session\s*$", text, re.MULTILINE), (
        f"{USER_GUIDE} has no user-guide section for the next-session note"
    )
    section = text.split("## A Note to the Next Session", 1)[1].split("\n## ", 1)[0]
    for needle in ("/pm-next", ".project/NEXT.md", "pm_context"):
        assert needle in section, f"{USER_GUIDE}: the section never mentions {needle}"
