"""US-PM-68-8 — every skill the worker prompt tells a worker to run is model-invocable.

Story US-PM-68's criterion: "A worker subagent can invoke /projectman:pm-do
through the Skill tool".  A skill whose frontmatter sets
``disable-model-invocation: true`` is refused by the Skill tool, so a worker
subagent told to run it could only follow its steps by hand.  pm-do carried the
flag until this task; pm-orchestrate keeps it, since only a human starts a run.

The skills are read off the ``Worker Prompt Template`` fence of pm-orchestrate
(template, tracked rendered copy and a live render), so a skill added to the
prompt later is held to the same rule without editing this module.  Each named
skill is then checked in its template and its tracked plugin-root copy.

The last test is a falsification guard: a frontmatter that sets the flag must
fail the same check.

Nothing here writes.
"""

import re

import pytest
import yaml

from projectman.cli import CLAUDE_SKILLS, _render_template
from tests.test_skill_guidance_tools import _worker_fence
from tests.test_skill_release_instructions import (
    ORCHESTRATE_SKILL,
    ORCHESTRATE_TEMPLATE,
    RENDERED_SKILLS,
    TEMPLATES,
)

FLAG = "disable-model-invocation"

#: ``/projectman:pm-do`` or a bare ``/pm-do`` — a skill invocation in the prompt
SKILL_REF = re.compile(r"(?<![\w/])/(?:projectman:)?(pm(?:-[a-z]+)*)\b")

TEMPLATE_FOR = dict(CLAUDE_SKILLS)

FENCE_SOURCES = {
    "template": lambda: ORCHESTRATE_TEMPLATE.read_text(encoding="utf-8"),
    "rendered": lambda: ORCHESTRATE_SKILL.read_text(encoding="utf-8"),
    "live-render": lambda: _render_template("skill_pm_orchestrate.md.j2"),
}


def _frontmatter(text: str) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "skill has no YAML frontmatter block"
    return yaml.safe_load(match.group(1)) or {}


def _model_invocable(text: str) -> bool:
    return not _frontmatter(text).get(FLAG, False)


def _worker_skills(text: str) -> list[str]:
    return sorted(set(SKILL_REF.findall(_worker_fence(text))))


@pytest.mark.parametrize("source", sorted(FENCE_SOURCES))
def test_worker_prompt_names_pm_do(source):
    assert "pm-do" in _worker_skills(FENCE_SOURCES[source]())


@pytest.mark.parametrize("source", sorted(FENCE_SOURCES))
def test_every_skill_the_worker_prompt_names_is_a_shipped_skill(source):
    unknown = [s for s in _worker_skills(FENCE_SOURCES[source]()) if s not in TEMPLATE_FOR]
    assert not unknown, f"worker prompt names skills not in CLAUDE_SKILLS: {unknown}"


def _worker_skill_docs():
    names = set()
    for read in FENCE_SOURCES.values():
        names.update(_worker_skills(read()))
    for name in sorted(names):
        yield pytest.param(TEMPLATES / TEMPLATE_FOR[name], id=f"{name}-template")
        yield pytest.param(RENDERED_SKILLS / name / "SKILL.md", id=f"{name}-rendered")


@pytest.mark.parametrize("path", list(_worker_skill_docs()))
def test_worker_skills_are_model_invocable(path):
    text = path.read_text(encoding="utf-8")
    assert _model_invocable(text), (
        f"{path} sets {FLAG}: the Skill tool refuses it, so a worker subagent "
        f"cannot run it"
    )


@pytest.mark.parametrize(
    "path",
    [ORCHESTRATE_TEMPLATE, RENDERED_SKILLS / "pm-orchestrate" / "SKILL.md"],
    ids=["template", "rendered"],
)
def test_pm_orchestrate_stays_user_only(path):
    assert _frontmatter(path.read_text(encoding="utf-8")).get(FLAG) is True


def test_a_flagged_skill_fails_the_check():
    flagged = "---\nname: pm-do\ndescription: x\n" + FLAG + ": true\n---\n\nbody\n"
    assert not _model_invocable(flagged)
    assert _model_invocable("---\nname: pm-do\ndescription: x\n---\n\nbody\n")
