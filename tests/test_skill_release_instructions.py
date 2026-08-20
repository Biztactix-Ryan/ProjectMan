"""US-PM-7-4 — the skills must never again instruct the unspellable release.

Story US-PM-7's whole diagnosis was that ``pm_update(<id>, status="todo",
assignee="")`` is a call the model cannot reliably emit: every parameter is
``Optional[str] = None``, so ``null`` already means "leave unchanged", the model
reaches for it, finds it taken, and emits a bare key instead.  US-PM-7-9
rewrote both instruction sites — step 13 and the stop-conditions block of
``pm-orchestrate`` — to say it with a verb: ``pm_release(<id>, note="...")``.

This regression was *already* fixed once, in commit ``2261a0d``, by adding a
docstring line — and came back three weeks later.  A prose fix does not stay
fixed on its own, so the absence is pinned here mechanically, over every skill
template and every rendered ``SKILL.md`` in the checkout.  ``assignee=""``
remains *accepted* by ``pm_update`` (see ``test_release_and_clear.py``); what
this file forbids is *instructing* it.
"""

import re
from pathlib import Path

import projectman

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(projectman.__file__).resolve().parent / "templates"
RENDERED_SKILLS = REPO_ROOT / ".claude" / "skills"

# `assignee=""`, `assignee = ''`, `assignee: ""` — every way the sentinel spells.
SENTINEL = re.compile(r"""assignee\s*[=:]\s*(""|'')""")

ORCHESTRATE_TEMPLATE = TEMPLATES / "skill_pm_orchestrate.md.j2"
ORCHESTRATE_SKILL = RENDERED_SKILLS / "pm-orchestrate" / "SKILL.md"


def _skill_templates() -> list[Path]:
    files = sorted(TEMPLATES.glob("skill_*.j2")) + sorted(TEMPLATES.glob("agent_*.j2"))
    assert files, f"no skill templates found under {TEMPLATES}"
    return files


def _rendered_skills() -> list[Path]:
    # Absent in a packaged install; present in the checkout this test runs from.
    return sorted(RENDERED_SKILLS.glob("*/SKILL.md"))


def _offending_lines(path: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if SENTINEL.search(line)
    ]


def test_no_skill_template_instructs_the_empty_assignee():
    """The sentinel is undocumented and uninstructed — release is said by verb."""
    offenders = [line for p in _skill_templates() for line in _offending_lines(p)]
    assert not offenders, "skill templates instruct the unspellable release:\n" + "\n".join(
        offenders
    )


def test_no_rendered_skill_instructs_the_empty_assignee():
    """A resync that reintroduces the sentinel downstream fails here too."""
    rendered = _rendered_skills()
    assert rendered, f"no rendered SKILL.md found under {RENDERED_SKILLS}"
    offenders = [line for p in rendered for line in _offending_lines(p)]
    assert not offenders, "rendered skills instruct the unspellable release:\n" + "\n".join(
        offenders
    )


def test_orchestrate_names_pm_release_at_both_release_sites():
    """Step 13 and the stop-conditions block — the two sites US-PM-7-9 rewrote.

    Asserting the *presence* of ``pm_release`` matters as much as the absence of
    the sentinel: deleting the instruction outright would satisfy the negative
    test while leaving the orchestrator holding a pre-claimed task forever.
    """
    for path in (ORCHESTRATE_TEMPLATE, ORCHESTRATE_SKILL):
        text = path.read_text(encoding="utf-8")
        assert text.count("pm_release(") >= 2, (
            f"{path} names pm_release fewer than twice — a release site was lost"
        )


def test_rendered_orchestrate_skill_matches_its_template_on_release():
    """The rendered copy is generated; a hand-edit that drifts is a bug."""
    template_lines = {
        line.strip()
        for line in ORCHESTRATE_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if "pm_release(" in line
    }
    skill_lines = {
        line.strip()
        for line in ORCHESTRATE_SKILL.read_text(encoding="utf-8").splitlines()
        if "pm_release(" in line
    }
    assert template_lines == skill_lines
