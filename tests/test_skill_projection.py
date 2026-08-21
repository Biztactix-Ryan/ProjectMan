"""US-PM-10 — ``pm-orchestrate`` uses projection for its validation read.

Story US-PM-10's framing is that four telemetry studies all reached the *wrong*
conclusion.  They saw ``pm_done_next`` followed by ``pm_get(task_id)`` on 138 of
138 (Study C) and 140 of 150 (Study B) worker cycles, called it redundant, and
recommended deleting the read.  It is not redundant: step 16 of the orchestrator
skill re-reads the task to check the worker's self-report, and the skill's whole
premise is that a worker's self-report is not trusted.  The defect was the
price — ~3,870 chars to learn two fields.  So the fix delivered by US-PM-10-8
was to *keep the read and project it*, not to remove it.

That is a prose fix in a skill file, and prose fixes do not stay fixed: a later
edit that "simplifies" step 16 back to ``pm_get(task_id)`` restores the cost
silently, and one that deletes the step altogether restores the far worse bug
the studies recommended.  This module pins both directions, plus the two
properties that make the pin meaningful rather than cosmetic:

* **the projection matches the check** — the ``fields=`` literal names exactly
  the fields the step's prose goes on to check, so the read fetches what it
  checks and checks what it fetches;
* **the projection is real** — the literal lifted out of the skill file is fed
  to the actual server, which must accept it and return exactly those keys.
  A skill naming a field the server rejects would turn the verification read
  into an error at the worst possible moment;
* **the cost claim is honest** — "tens of chars instead of thousands" is
  measured against a realistic task, not asserted.

Server-side projection semantics (defaults, unknown names, ``id`` survival) are
owned by ``tests/test_field_projection.py`` and are not restated here; this
module only closes the loop between what the skill *says* and what the server
*does*.

Both the template (source of truth) and the tracked rendered ``SKILL.md`` are
checked via the shared ``DOCS`` parametrization.  Their byte-for-byte equality
is deliberately *not* re-asserted here — it is already owned by
``tests/test_skill_verdict_verbs.py::
test_rendered_orchestrate_skill_is_byte_identical_to_its_template``.
Helpers are imported rather than copied, for the same reason.
"""

import re

import pytest
import yaml

from tests.test_skill_guidance_tools import _step, _worker_fence
from tests.test_skill_release_instructions import ORCHESTRATE_SKILL
from tests.test_skill_verdict_verbs import DOCS, _step_19, _text

# ─── the step under test ─────────────────────────────────────────

#: the orchestrator's post-worker verification step
STATUS_STEP = "16."

#: the fields step 16 must project *and* check — the two the orchestrator
#: actually reads: did the worker mark it done, and is it still the worker's?
EXPECTED_FIELDS = {"status", "assignee"}

#: ``pm_get(`` with its argument list captured (arguments never contain a ``)``)
PM_GET_CALL = re.compile(r"\bpm_get\(([^)]*)\)")

#: a ``fields="a,b"`` keyword literal
FIELDS_LITERAL = re.compile(r'\bfields\s*=\s*"([^"]*)"')

#: the prose that marks the read as intentional rather than leftover
DELIBERATE = re.compile(r"deliberate|trust-but-verify", re.IGNORECASE)


def _step_16(text: str) -> str:
    return _step(text, STATUS_STEP)


def _projection(step: str) -> set[str]:
    """The set of field names the step's ``pm_get`` call projects."""
    literal = _fields_literal(step)
    return {name.strip() for name in literal.split(",") if name.strip()}


def _fields_literal(step: str) -> str:
    """The raw ``fields="..."`` string from the step's ``pm_get`` call."""
    calls = PM_GET_CALL.findall(step)
    assert calls, f"step {STATUS_STEP} makes no pm_get call at all:\n{step}"
    args = [a for a in calls if "task_id" in a]
    assert len(args) == 1, (
        f"expected exactly one pm_get(task_id, ...) in step {STATUS_STEP}, "
        f"found {len(args)}: {args}"
    )
    match = FIELDS_LITERAL.search(args[0])
    assert match, (
        f"step {STATUS_STEP}'s verification read is unprojected: "
        f"pm_get({args[0]}) — the whole point of US-PM-10 is that this read "
        "is cheap, not that it is gone"
    )
    return match.group(1)


def _outside_worker_prompt(text: str) -> str:
    """The document minus the worker prompt fence.

    Only the fence is removed, not every fenced block: the rules below are about
    what the *orchestrator* does, and the worker prompt is instructions for
    somebody else — a worker's own ``pm_get`` is not a validation read.
    """
    fence = _worker_fence(text)
    assert fence in text
    return text.replace(fence, "\n")


# ═══ the projection matches the check ═══════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_step_16_block_is_extractable_and_is_the_status_check(path):
    """Guard the slice and the numbering: every assertion below is scoped here.

    Steps get inserted (US-PM-13 added a ``4b.``); if that ever pushed the
    status check off ``16.`` this module would silently test the wrong block.
    """
    text = _text(path)
    step = _step_16(text)
    assert "Status check" in step.splitlines()[0], step.splitlines()[0]
    # ... and it still precedes the verdict step it feeds.
    assert text.index(step) < text.index(_step_19(text)), (
        "step 16 no longer precedes step 19 — the verification read must "
        "happen before the verdict it informs"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_16_projects_exactly_the_fields_it_checks(path):
    """The read fetches what it checks — no more, and no less."""
    projected = _projection(_step_16(_text(path)))
    assert projected == EXPECTED_FIELDS, (
        f"step {STATUS_STEP} projects {sorted(projected)} but the check it "
        f"performs needs {sorted(EXPECTED_FIELDS)}"
    )


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS))
def test_step_16_prose_checks_every_field_it_projects(path, field):
    """...and checks what it fetches: a projected field nobody reads is waste."""
    step = _step_16(_text(path))
    prose = step[step.index(")") :]  # after the pm_get call itself
    assert re.search(rf"\b{field}\b", prose), (
        f"step {STATUS_STEP} projects {field!r} but its prose never says what "
        f"to do with it:\n{step}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_step_16_still_makes_the_read_and_says_it_is_deliberate(path):
    """The story's core point: make it cheap, do not delete it.

    Four studies recommended deleting this read.  The skill must keep it *and*
    say why, or the next reader reaches the same wrong conclusion.
    """
    step = _step_16(_text(path))
    assert "pm_get(" in step, (
        f"step {STATUS_STEP} no longer reads the task back — the orchestrator "
        "is trusting the worker's self-report, which the skill forbids"
    )
    assert DELIBERATE.search(step), (
        f"step {STATUS_STEP} does not say the read is deliberate, so the next "
        f"reader will delete it as redundant:\n{step}"
    )


# ═══ no unprojected validation read survives ════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_no_orchestrator_task_read_is_unprojected(path):
    """Every ``pm_get(task_id`` in the orchestrator's own flow carries fields=.

    Scoped to ``task_id`` on purpose rather than "all pm_get": step 5's
    ``pm_get(story_id)`` is *correctly* unprojected — see the test below — so a
    blanket rule would be wrong, not merely stricter.
    """
    for args in PM_GET_CALL.findall(_outside_worker_prompt(_text(path))):
        if "task_id" not in args:
            continue
        assert FIELDS_LITERAL.search(args), (
            f"unprojected validation read pm_get({args}) — every task read in "
            "the orchestrator flow must name the fields it needs"
        )


@pytest.mark.parametrize("path", DOCS)
def test_the_plan_building_story_read_is_deliberately_unprojected(path):
    """Step 5 reads whole stories, and should.

    Projection is not a blanket good.  Step 5 builds the run plan out of task
    bodies and DoD checklists, so it genuinely needs the full item; asserting it
    stays unprojected keeps the rule above honest (a rule that never spares
    anything is indistinguishable from "ban pm_get") and stops a later
    over-eager sweep from projecting away the plan's inputs.
    """
    story_reads = [
        args
        for args in PM_GET_CALL.findall(_outside_worker_prompt(_text(path)))
        if "story_id" in args
    ]
    assert story_reads, "step 5's pm_get(story_id) plan read has vanished"
    assert not any(FIELDS_LITERAL.search(args) for args in story_reads), (
        "the plan-building story read grew a fields= projection; it needs the "
        f"full item (bodies and DoD checklists): {story_reads}"
    )


# ═══ the projection is real, and it pays ════════════════════════

#: a task body of the size the orchestrator actually verifies
REALISTIC_BODY = (
    "## Implementation\n\n"
    "Wire the projection through the tool layer so the orchestrator's "
    "verification read stops paying for the whole item. Touch the server "
    "entry points only; the store keeps returning full objects.\n\n"
    "## Testing\n\n"
    "Cover the default path, the projected path, and the failure path where a "
    "field name does not exist on the item being read.\n\n"
    "## Definition of Done\n\n"
    "- [ ] Default response is byte-identical\n"
    "- [ ] Projection returns id plus the named fields\n"
    "- [ ] Unknown field names fail loudly\n"
    "- [ ] Measured saving is recorded in the run log\n"
)


@pytest.fixture
def verifiable_task(tmp_project, monkeypatch):
    """A task the orchestrator would plausibly verify, on a throwaway project.

    Long body and a parent story carrying acceptance criteria — the two things
    that make the unprojected read expensive in the first place.
    """
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    store = Store(tmp_project)
    story, _ = store.create_story(
        "Field projection on pm_get and pm_grab",
        "As an orchestrator verifying a worker's claim I want to fetch one "
        "field cheaply so that distrusting the worker does not cost thousands "
        "of tokens.",
        acceptance_criteria=["Projection returns only the named fields"],
    )
    task = store.create_task(
        story.id, "Use projection for the validation read", REALISTIC_BODY, points=2
    )
    store.update(task.id, status="done", assignee="claude")
    clear_all_caches()
    _store_cache.clear()
    return task.id


def test_the_literal_in_the_skill_is_a_projection_the_server_accepts(
    verifiable_task,
):
    """Feed the skill's own ``fields=`` string to the real tool.

    This is the loop the two halves of this module would otherwise leave open:
    the text can be internally consistent and still name a key the server has
    never heard of, which would turn every verification read into an error.
    """
    from projectman.server import pm_get

    literal = _fields_literal(_step_16(_text(ORCHESTRATE_SKILL)))
    data = yaml.safe_load(pm_get(verifiable_task, fields=literal))

    assert set(data) == {"id"} | EXPECTED_FIELDS, (
        f"pm_get(task, fields={literal!r}) returned {sorted(data)} — the skill "
        "instructs a projection the server does not serve as written"
    )
    assert data["id"] == verifiable_task
    assert data["status"] == "done"
    assert data["assignee"] == "claude"


def test_the_projection_the_skill_instructs_costs_a_tenth_of_the_full_read(
    verifiable_task,
):
    """"Tens of chars instead of thousands" — measured, not claimed."""
    from projectman.server import pm_get

    literal = _fields_literal(_step_16(_text(ORCHESTRATE_SKILL)))
    full = len(pm_get(verifiable_task))
    projected = len(pm_get(verifiable_task, fields=literal))
    ratio = projected / full

    assert full >= 500, (
        f"the fixture task's full read is only {full} chars — too small for "
        "the ratio below to mean anything; make the body realistic again"
    )
    assert ratio <= 0.10, (
        f"pm_get(task, fields={literal!r}) is {projected} of {full} chars = "
        f"{ratio:.1%} of the full item; step 16 promises nearly free, budget "
        "is 10%"
    )
