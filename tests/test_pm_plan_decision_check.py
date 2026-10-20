"""US-PM-67-6 — open decisions in ``/projectman:pm-plan`` and the ``/projectman:pm`` routes.

Story US-PM-67's criteria, as this module pins them:

* **US-PM-67-2** — "/pm-plan lists open decisions that block candidate stories
  and suggests /pm-decide before sizing".  Pinned on the pm-plan skill: a
  decision-check step calls ``pm_list_decisions`` with the real ``status`` and
  ``blocks`` filters, lists each hit, suggests ``/projectman:pm-decide``, and
  sits *before* the sizing step (Phase 3's "summed points fit the velocity")
  by character position, so moving it after sizing fails here.
* **US-PM-67-3** — "The /pm skill routes decide and decisions to /pm-decide and
  pm_list_decisions".  Pinned on the /pm skill's routing table.

Every check runs over the template, the tracked rendered copy and a live
render, so a one-sided edit fails.  Nothing here writes to any store.
"""

import inspect
import re
from pathlib import Path

import pytest

from projectman import server
from projectman.cli import _render_template
from tests.test_plugin_references import plugin_provides, scan

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"

#: the skill character cap sibling skills are held to (US-PM-25)
MAX_CHARS = 9000

SKILLS = {
    "pm-plan": "skill_pm_plan.md.j2",
    "pm": "skill_pm.md.j2",
}


def _sources(skill: str) -> dict:
    name = SKILLS[skill]
    return {
        "template": lambda: (TEMPLATES / name).read_text(encoding="utf-8"),
        "rendered": lambda: (REPO_ROOT / "skills" / skill / "SKILL.md").read_text(
            encoding="utf-8"
        ),
        "live-render": lambda: _render_template(name),
    }


@pytest.fixture(params=["template", "rendered", "live-render"])
def plan(request):
    return _sources("pm-plan")[request.param]()


@pytest.fixture(params=["template", "rendered", "live-render"])
def pm(request):
    return _sources("pm")[request.param]()


def _calls(text: str, tool: str) -> list[str]:
    return re.findall(rf"\b{tool}\(([^)]*)\)", text)


def _kwargs(args: str) -> set[str]:
    return set(re.findall(r"\b([a-z_]+)\s*=", args))


#: the decision-check step: a numbered item naming the check
DECISION_STEP = re.compile(r"^\d+\. Decision check\b.*?(?=^\d+\. |^## |\Z)", re.S | re.M)
#: the sizing step the check must precede
SIZING = re.compile(r"summed points fit the velocity")


def _decision_step(text: str) -> str:
    m = DECISION_STEP.search(text)
    assert m, "pm-plan has no 'Decision check' step"
    return m.group(0)


# ─── shared guards ───────────────────────────────────────────────


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_tracked_rendered_copy_is_byte_identical(skill):
    rendered = REPO_ROOT / "skills" / skill / "SKILL.md"
    assert rendered.read_bytes() == (TEMPLATES / SKILLS[skill]).read_bytes()


@pytest.mark.parametrize("skill", sorted(SKILLS))
@pytest.mark.parametrize("source", ["template", "rendered", "live-render"])
def test_under_cap_and_passes_reference_scan(skill, source):
    text = _sources(skill)[source]()
    assert len(text) <= MAX_CHARS, f"{skill}: {len(text)} chars, cap {MAX_CHARS}"
    problems = scan(text, *plugin_provides())
    assert not problems, "\n".join(problems)


# ─── US-PM-67-2: /pm-plan checks decisions before sizing ─────────


def test_plan_lists_open_decisions_blocking_candidates(plan):
    step = _decision_step(plan)
    calls = _calls(step, "pm_list_decisions")
    assert any('status="open"' in c and "blocks=" in c for c in calls), calls
    assert re.search(r"\bcandidate stor", step), "the filter is not the candidate stories"
    assert re.search(r"\bList each hit\b", step)
    for key in ("`id`", "`title`", "`blocks`", "`blocked_points`"):
        assert key in step, f"the listing does not show {key}"


def test_plan_suggests_pm_decide_before_sizing(plan):
    step = _decision_step(plan)
    assert re.search(r"[Ss]uggest\b[^\n]*`/projectman:pm-decide`", step)
    assert re.search(r"before sizing", step)
    sizing = SIZING.search(plan)
    assert sizing, "the sizing step vanished"
    start = plan.index(step)
    assert start < sizing.start(), "the decision check must come before sizing"
    assert start < plan.index("## Phase 3"), "the decision check belongs before selection"


def test_plan_empty_case_moves_on(plan):
    assert re.search(r"Empty list → .*move on", _decision_step(plan))


def test_plan_ordering_guard_fires_when_the_step_moves_after_sizing(plan):
    """Falsification: the same step moved to the end fails the ordering check."""
    step = _decision_step(plan)
    moved = plan.replace(step, "") + "\n" + step
    assert moved.index(step) > SIZING.search(moved).start()


# ─── US-PM-67-3: /pm routes decide and decisions ─────────────────


def _route(text: str, word: str) -> str:
    m = re.search(rf"^- `{word}\b[^\n]*", text, re.M)
    assert m, f"/pm has no `{word}` route"
    return m.group(0)


def test_pm_routes_decisions_to_pm_list_decisions(pm):
    route = _route(pm, "decisions")
    assert re.search(r"→ `pm_list_decisions\(", route), route


def test_pm_routes_decide_to_pm_decide(pm):
    route = _route(pm, "decide")
    assert re.search(r"→ redirect to `/projectman:pm-decide`", route), route


# ─── call forms use real argument names ──────────────────────────


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_pm_list_decisions_call_forms_use_real_arguments(skill):
    params = set(inspect.signature(server.pm_list_decisions).parameters)
    text = _sources(skill)["template"]()
    calls = _calls(text, "pm_list_decisions")
    assert calls, f"{skill} never calls pm_list_decisions"
    for args in calls:
        unknown = _kwargs(args) - params
        assert not unknown, f"pm_list_decisions({args}) names unknown arguments {unknown}"
