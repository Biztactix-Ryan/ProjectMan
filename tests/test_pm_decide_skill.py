"""US-PM-65-9 — the ``/projectman:pm-decide`` skill.

Story US-PM-65's criteria, as this module pins them:

* **US-PM-65-4** — each question shows the decision's context, what it
  blocks, its options and the recommendation, and accepts a free-text answer.
  Pinned in the skill's Phase 2 (the brief and the question), and end to end:
  the call forms the skill names are run against a tmp_path store, so the row
  keys it reads exist and a free-text answer is really recorded.
* **US-PM-65-5** — the session ends with a summary of answered, skipped and
  withdrawn decisions and the points unblocked, then offers
  ``/projectman:pm-plan``.  Pinned in Phase 3.
* **US-PM-65-6** — the skill is rendered by build-plugin, passes the template
  reference scan and stays under the skill character cap.

Every check runs over the template, the tracked rendered copy and a live
render, so a one-sided edit fails here.  The only store this module writes is
the tmp_path one in ``server_store``, which asserts its root before use.
"""

import inspect
import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from projectman.cli import CLAUDE_SKILLS, _render_template, cli
from tests.test_plugin_references import plugin_provides, scan

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_NAME = "skill_pm_decide.md.j2"
TEMPLATE = REPO_ROOT / "src" / "projectman" / "templates" / TEMPLATE_NAME
RENDERED = REPO_ROOT / "skills" / "pm-decide" / "SKILL.md"
SKILLS_DOC = REPO_ROOT / "docs" / "reference" / "skills.md"

#: the skill character cap sibling skills are held to (US-PM-25)
MAX_CHARS = 9000

SOURCES = {
    "template": lambda: TEMPLATE.read_text(encoding="utf-8"),
    "rendered": lambda: RENDERED.read_text(encoding="utf-8"),
    "live-render": lambda: _render_template(TEMPLATE_NAME),
}


@pytest.fixture(params=sorted(SOURCES))
def text(request):
    return SOURCES[request.param]()


def _phase(text: str, number: int) -> str:
    m = re.search(rf"^## Phase {number}\b.*?(?=^## |\Z)", text, re.S | re.M)
    assert m, f"no '## Phase {number}' section"
    return m.group(0)


def _calls(text: str, tool: str) -> list[str]:
    """Argument lists of every ``tool(...)`` call form in *text*."""
    return re.findall(rf"\b{tool}\(([^)]*)\)", text)


def _kwargs(args: str) -> set[str]:
    return set(re.findall(r"\b([a-z_]+)\s*=", args))


# ─── registration, render and shape (US-PM-65-6) ─────────────────


def test_registered_so_setup_and_build_plugin_render_it():
    assert ("pm-decide", TEMPLATE_NAME) in CLAUDE_SKILLS


def test_template_renders_to_its_own_text():
    rendered = _render_template(TEMPLATE_NAME)
    assert "template not found" not in rendered
    assert rendered == TEMPLATE.read_text(encoding="utf-8")


def test_tracked_rendered_copy_is_byte_identical():
    assert RENDERED.read_bytes() == TEMPLATE.read_bytes()


def test_build_plugin_writes_the_skill(tmp_path):
    result = CliRunner().invoke(cli, ["build-plugin", str(tmp_path)])
    assert result.exit_code == 0, result.output
    built = tmp_path / "skills" / "pm-decide" / "SKILL.md"
    assert built.read_text(encoding="utf-8") == TEMPLATE.read_text(encoding="utf-8")


def test_frontmatter_names_the_skill_and_takes_a_batch_size(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "no frontmatter"
    front = yaml.safe_load(m.group(1))
    assert front["name"] == "pm-decide"
    assert front.get("description", "").strip()
    assert "batch" in front.get("args", "")
    assert not front.get("disable-model-invocation", False)


def test_under_the_skill_character_cap(text):
    assert len(text) <= MAX_CHARS, f"{len(text)} chars, cap {MAX_CHARS}"


def test_passes_the_template_reference_scan(text):
    problems = scan(text, *plugin_provides())
    assert not problems, "\n".join(problems)


def test_reference_scan_would_catch_a_bare_name_in_it(text):
    """The scan is live on this text: a bare /pm-plan is reported."""
    problems = scan(text + "\nThen run /pm-plan.\n", *plugin_provides())
    assert len(problems) == 1 and "bare /pm-plan" in problems[0]


def test_skills_reference_documents_it():
    headings = re.findall(r"^##\s+/([\w-]+)\s*$", SKILLS_DOC.read_text(), re.M)
    assert "pm-decide" in headings


# ─── the batch (default 7, user-adjustable) ──────────────────────


def test_batch_is_listed_in_session_order_with_the_argument_as_limit(text):
    calls = _calls(_phase(text, 1), "pm_list_decisions")
    assert any('order="session"' in c and "limit=n" in c for c in calls), calls
    assert re.search(r"default 7\b", text)


def test_context_is_fetched_in_one_projected_read(text):
    calls = _calls(_phase(text, 1), "pm_get")
    assert any('fields="body"' in c for c in calls), calls


# ─── each question (US-PM-65-4) ──────────────────────────────────


@pytest.mark.parametrize(
    "label, pattern",
    [
        ("question", r"\*\*Question\*\*.*`title`"),
        ("context", r"\*\*Context\*\*.*\bbody\b"),
        ("blocks", r"\*\*Blocks\*\*.*`blocked`.*`blocked_points`"),
        ("options", r"\*\*Options\*\*.*`label`.*`summary`"),
        ("recommendation", r"\*\*Recommendation\*\*.*`recommendation`"),
    ],
)
def test_brief_shows(text, label, pattern):
    assert re.search(pattern, _phase(text, 2)), f"the brief does not show the {label}"


def test_docs_are_pulled_only_when_cited(text):
    phase = _phase(text, 2)
    assert _calls(phase, "pm_docs")
    assert re.search(r"only when the context cites", phase)


def test_question_puts_the_recommendation_first_and_marks_it(text):
    phase = _phase(text, 2)
    assert "AskUserQuestion" in phase
    assert re.search(r"recommended option first.*`\(Recommended\)`", phase)


def test_question_offers_skip_and_withdraw(text):
    phase = _phase(text, 2)
    assert "**Skip**" in phase and "**Withdraw**" in phase
    assert re.search(r"at most four options", phase), "overflow rule for the 4-option limit"


def test_question_accepts_a_free_text_answer_and_records_it(text):
    phase = _phase(text, 2)
    assert re.search(r"free-text answer is always open", phase)
    free = [c for c in _calls(phase, "pm_answer_decision") if "their words" in c]
    assert free and "answer=" in free[0]


def test_every_outcome_is_recorded_with_the_right_call(text):
    calls = _calls(_phase(text, 2), "pm_answer_decision")
    assert any("answer=" in c for c in calls)
    assert any("withdraw=true" in c and "reason=" in c for c in calls)
    assert re.search(r"Skip → write nothing", text)


@pytest.mark.parametrize(
    "tool", ["pm_list_decisions", "pm_answer_decision", "pm_get", "pm_docs"]
)
def test_call_forms_use_real_argument_names(text, tool):
    from projectman import server

    params = set(inspect.signature(getattr(server, tool)).parameters)
    calls = _calls(text, tool)
    assert calls, f"skill never calls {tool}"
    for args in calls:
        unknown = _kwargs(args) - params
        assert not unknown, f"{tool}({args}) names unknown arguments {unknown}"


# ─── the summary (US-PM-65-5) ────────────────────────────────────


@pytest.mark.parametrize("bucket", ["Answered", "Skipped", "Withdrawn", "Unblocked"])
def test_summary_lists(text, bucket):
    assert re.search(rf"\*\*{bucket}\*\*", _phase(text, 3)), bucket


def test_summary_totals_the_points_unblocked(text):
    phase = _phase(text, 3)
    assert any('fields="points"' in c for c in _calls(phase, "pm_get"))
    assert re.search(r"points unblocked", phase, re.I)


def test_session_ends_by_offering_pm_plan(text):
    phase = _phase(text, 3)
    offers = [m.start() for m in re.finditer(r"Offer `/projectman:pm-plan`", phase)]
    assert offers, "the summary never offers /projectman:pm-plan"
    summary = phase.index("Summarize the session")
    assert offers[-1] > summary, "pm-plan must be offered after the summary"


# ─── end to end against a tmp store (US-PM-65-4) ─────────────────


@pytest.fixture
def server_store(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    monkeypatch.setenv("PROJECTMAN_ACTOR", "test-actor")
    from projectman.server import _store, _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()
    assert _store().project_dir == tmp_project / ".project"
    assert str(_store().project_dir).startswith(str(tmp_project))
    yield Store(tmp_project)
    clear_all_caches()
    _store_cache.clear()


def test_the_skills_calls_brief_and_record_a_free_text_answer(server_store):
    from projectman.server import (
        pm_answer_decision,
        pm_create_decision,
        pm_get,
        pm_list_decisions,
    )

    story, _ = server_store.create_story("A story", "A description long enough to pass")
    task = server_store.create_task(story.id, "Wait on it", "Body", points=3)
    pm_create_decision(
        title="Which queue backend?",
        context="We need durable delivery.",
        options=[{"label": "Redis", "summary": "streams"}, "Postgres"],
        recommendation="Redis",
        blocks=[task.id],
    )

    rows = yaml.safe_load(pm_list_decisions(order="session", limit=7))["decisions"]
    row = rows[0]
    for key in ("id", "title", "options", "recommendation", "blocked", "blocked_points", "tier"):
        assert key in row, f"session row lacks `{key}`, which the brief reads"
    assert row["blocked"] == [{"id": task.id, "title": "Wait on it"}]
    assert row["blocked_points"] == 3
    assert [o["label"] for o in row["options"]] == ["Redis", "Postgres"]

    body = yaml.safe_load(pm_get(row["id"], fields="body"))
    assert "durable delivery" in body["body"]

    answered = yaml.safe_load(
        pm_answer_decision(row["id"], answer="Neither: use SQS", rationale="ops already run it")
    )["answered"]
    assert answered["answer"] == "Neither: use SQS"
    assert answered["unblocked"] == [task.id]

    points = yaml.safe_load(pm_get(task.id, fields="points"))
    assert points["points"] == 3
