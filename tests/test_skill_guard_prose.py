"""US-PM-59-5 — the skills drop the prose the plugin guards now enforce.

Story US-PM-59 moved two worker rules out of skill prose and into the plugin's
``tool.call`` hooks: ``hooks/git-guard.ts`` refuses ``git checkout``,
``git restore`` and ``git stash`` in a subagent, and ``hooks/store-guard.ts``
refuses Write/Edit into the real ``.project`` store.  The point of the story
was the skill character budget — both skills are loaded on every dispatch — so
this pins the two halves of the acceptance criterion:

* neither ``/projectman:pm-orchestrate`` nor ``/projectman:pm-do`` restates a
  guard-enforced rule; each keeps only a one-line pointer at the guards
  (US-PM-59-9, decided 2026-10-20);
* each stays under a character budget smaller than its render at
  ``PRE_GUARD_COMMIT``, the last commit before the guards landed.

Every check runs on the template, the tracked plugin-root ``skills/`` copy and
a live render, so a template edit that skipped the rendered copy is caught too.
The falsification guards push the pre-guard templates, read from git, through
the production renderer and require both checks to reject them.
"""

import re
import subprocess
from pathlib import Path

import pytest

import projectman
from projectman.cli import _render_template
from tests.test_orchestrate_skill_size import MAX_CHARS as ORCHESTRATE_MAX_CHARS

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"

#: 0.11.0, the last commit before the plugin and its guards (848f45a).
PRE_GUARD_COMMIT = "b2d50ef"

#: skill -> template name, tracked rendered copy
SKILLS = {
    "pm-orchestrate": ("skill_pm_orchestrate.md.j2", REPO_ROOT / "skills" / "pm-orchestrate" / "SKILL.md"),
    "pm-do": ("skill_pm_do.md.j2", REPO_ROOT / "skills" / "pm-do" / "SKILL.md"),
}

#: the rendered length at PRE_GUARD_COMMIT, measured through _render_template
PRE_GUARD_CHARS = {"pm-orchestrate": 10199, "pm-do": 4421}

#: the budgets after the guards: the orchestrate one is the skill-size test's
#: own MAX_CHARS (lowered from 10200 by this task); pm-do had none before
BUDGETS = {"pm-orchestrate": ORCHESTRATE_MAX_CHARS, "pm-do": 4410}

#: the one-line pointers that replace the dropped prose
GIT_GUARD_POINTER = re.compile(r"guards? (?:block|refuse)s?\s+checkout/restore/stash", re.IGNORECASE)
STORE_GUARD_POINTER = re.compile(
    r"guards? (?:block|refuse)s?[^.\n]{0,60}`?\.project`? writes", re.IGNORECASE
)

#: a guard-enforced git subcommand named anywhere outside the pointer
GUARDED_GIT_WORD = re.compile(r"\b(?:checkout|restore|stash)\b", re.IGNORECASE)

#: the store-write rule as prose (the store guard's job since US-PM-59-8)
STORE_WRITE_PROSE = [
    re.compile(r"store is reached through", re.IGNORECASE),
    re.compile(r"never\s+(?:a|through a)\s*`?\.project`?\s*directory", re.IGNORECASE),
    re.compile(r"(?:never|do not|don't)\s+(?:write|edit)[^.\n]{0,40}\.project", re.IGNORECASE),
]


def _sources(skill: str) -> dict:
    template, rendered = SKILLS[skill]
    return {
        "template": lambda: (TEMPLATES / template).read_text(encoding="utf-8"),
        "rendered": lambda: rendered.read_text(encoding="utf-8"),
        "live-render": lambda: _render_template(template),
    }


CASES = [(skill, source) for skill in SKILLS for source in ("template", "rendered", "live-render")]
IDS = [f"{skill}-{source}" for skill, source in CASES]


def guard_enforced_prose(text: str) -> list:
    """Every passage restating a rule the guards enforce; empty when clean."""
    without_pointers = GIT_GUARD_POINTER.sub("", text)
    found = [m.group(0) for m in GUARDED_GIT_WORD.finditer(without_pointers)]
    found += [m.group(0) for p in STORE_WRITE_PROSE for m in p.finditer(text)]
    return found


def _render_at(commit: str, skill: str, tmp_path, monkeypatch) -> str:
    template = SKILLS[skill][0]
    try:
        source = subprocess.run(
            ["git", "show", f"{commit}:src/projectman/templates/{template}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no history
        pytest.skip(f"git history for {commit} unavailable")
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / template).write_text(source, encoding="utf-8")
    monkeypatch.setattr(projectman.cli, "_template_dir", lambda: tdir)
    text = _render_template(template)
    assert not text.endswith("template not found\n"), f"{commit}:{template} failed to render"
    return text


@pytest.mark.parametrize("skill,source", CASES, ids=IDS)
def test_skill_carries_no_guard_enforced_prose(skill, source):
    text = _sources(skill)[source]()
    found = guard_enforced_prose(text)
    assert not found, f"{skill} ({source}) restates guard-enforced rules: {found}"


@pytest.mark.parametrize("skill,source", CASES, ids=IDS)
def test_skill_points_at_the_guards(skill, source):
    """Dropped, not deleted: a pointer says the bans still hold and why a call is refused."""
    text = _sources(skill)[source]()
    assert GIT_GUARD_POINTER.search(text), f"{skill} ({source}) has no git-guard pointer"
    if skill == "pm-do":
        assert STORE_GUARD_POINTER.search(text), f"{skill} ({source}) has no store-guard pointer"


@pytest.mark.parametrize("skill", SKILLS)
def test_budget_is_smaller_than_before_the_guards(skill):
    assert BUDGETS[skill] < PRE_GUARD_CHARS[skill], (
        f"{skill}: budget {BUDGETS[skill]} is not below the pre-guard {PRE_GUARD_CHARS[skill]}"
    )


@pytest.mark.parametrize("skill,source", CASES, ids=IDS)
def test_skill_stays_within_the_shrunk_budget(skill, source):
    text = _sources(skill)[source]()
    assert len(text) <= BUDGETS[skill], (
        f"{skill} ({source}) is {len(text)} characters, "
        f"{len(text) - BUDGETS[skill]} over the {BUDGETS[skill]}-character budget"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_the_checks_reject_the_pre_guard_skill(skill, tmp_path, monkeypatch):
    """Falsification guard: the pre-guard render fails both checks.

    It also re-measures ``PRE_GUARD_CHARS``, so the "smaller than before"
    baseline is a fact about the history, not a number typed in.
    """
    old = _render_at(PRE_GUARD_COMMIT, skill, tmp_path, monkeypatch)
    assert len(old) == PRE_GUARD_CHARS[skill], (
        f"{skill} at {PRE_GUARD_COMMIT} renders to {len(old)} characters, "
        f"not the pinned {PRE_GUARD_CHARS[skill]}"
    )
    assert len(old) > BUDGETS[skill], f"the budget accepts the pre-guard {skill}"
    assert guard_enforced_prose(old), f"the prose check accepts the pre-guard {skill}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
