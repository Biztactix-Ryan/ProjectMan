"""US-PM-14-8 — pm-orchestrate documents a resume path, and it is executable.

US-PM-14-5/6/7 built the parts: ``claimed_at`` / ``claimed_by_run`` on the
task, ``run_id`` on every activity event and on every claim-taking verb,
``pm_activity(run_id=)`` as the per-run slice, and a Phase 1 step 3 that
classifies one in-progress claim at a time.  What was still missing is the
*procedure*: a run that dies mid-loop leaves claims behind, and until now the
skill's ``## Resume — Picking Up an Interrupted Run`` heading was a pointer at
step 3 plus the admission that "the end-to-end resume walkthrough belongs under
this heading".

This module pins the walkthrough, in the manner of
``tests/test_skill_claim_recovery.py`` — over the template (source of truth)
and the tracked rendered ``SKILL.md`` alike, with their byte-for-byte equality
owned by ``tests/test_skill_verdict_verbs.py``:

* **the flag exists** — ``--resume <run-id>`` in the Flags table and in the
  frontmatter ``args`` line, so the procedure has an entry point;
* **lineage, not reuse** — the resuming run mints a fresh id and writes
  ``recovered from run <old>`` on each adopted claim, so
  ``pm_activity(run_id=)`` slices stay one-per-process;
* **the sort is decided** — still-in-progress adopt, done leave, released or
  parked leave-and-report, and the source of those facts is a real
  ``pm_activity(run_id=<old>)`` query;
* **a resumed task is a retry** — the worker prompt carries an ``<on resume:``
  line warning about partial edits in the working tree, beside the existing
  ``<on retry:`` line;
* **there is a when-NOT-to-resume note** — a human claim, and a dead run whose
  last event is a verdict on a task that is now done;
* **the pin is not cosmetic** — every keyword argument the section names is
  checked against the real tool signature, and the whole procedure is then
  *executed* against a real store: run A grabs two tasks and accepts one, run B
  reconstructs the survivor from ``pm_activity(run_id=A)`` alone, adopts it and
  logs the lineage.  A documented resume path that the server refuses to
  perform would be a walkthrough of nothing.
"""

import inspect
import re

import pytest
import yaml

from tests.test_skill_guidance_tools import _worker_fence
from tests.test_skill_verdict_verbs import DOCS, _text

# ─── the section under test ──────────────────────────────────────

#: the heading this task filled in
RESUME_HEADING = "## Resume — Picking Up an Interrupted Run"

#: the flag that starts the procedure
RESUME_FLAG = "--resume"

#: the lineage note the procedure writes on every adopted claim
LINEAGE_NOTE = "recovered from run"

#: the worker-prompt line an adopted task is dispatched with
ON_RESUME = "<on resume"

#: the admission this task was meant to delete
BANNED_PHRASES = ("walkthrough belongs under this heading",)


def _section(text: str, heading: str) -> str:
    """The block under ``heading``, up to the next ``## `` heading."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(heading)]
    assert starts, f"no {heading!r} heading — the resume path vanished"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _resume(text: str) -> str:
    return _section(text, RESUME_HEADING)


def _flags(text: str) -> str:
    return _section(text, "## Flags")


def _lower(text: str) -> str:
    return text.lower()


# ═══ the flag ════════════════════════════════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_resume_is_a_documented_flag(path):
    """``--resume <run-id>`` is in the Flags table, not only in prose."""
    flags = _flags(_text(path))
    assert RESUME_FLAG in flags, (
        "the Flags table has no --resume entry, so the resume procedure has "
        f"no entry point:\n{flags}"
    )
    line = next(
        line for line in flags.splitlines() if line.startswith(f"- `{RESUME_FLAG}")
    )
    assert "<run-id>" in line, f"--resume takes the dead run's id: {line}"


@pytest.mark.parametrize("path", DOCS)
def test_the_frontmatter_args_line_advertises_resume(path):
    """The ``args:`` usage string is what the CLI shows; it must list it too."""
    front = _text(path).split("---")[1]
    args = yaml.safe_load(front)["args"]
    assert RESUME_FLAG in args, f"args line omits --resume: {args}"


@pytest.mark.parametrize("path", DOCS)
def test_without_the_flag_step_3_still_owns_the_classification(path):
    """The procedure is opt-in — it must say what happens without it."""
    section = _lower(_resume(_text(path)))
    assert "without `--resume`" in section, (
        "the section never says what a run does when the flag is absent; "
        "step 3's per-claim classification has to keep applying"
    )
    assert "step 3" in section


# ═══ mint a new id, record the lineage ═══════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_the_resuming_run_mints_a_new_id_rather_than_reusing_the_old_one(path):
    """Reuse would merge two processes into one pm_activity(run_id=) slice."""
    section = _resume(_text(path))
    low = _lower(section)
    assert "mint" in low, f"the section never says which id the run runs under:\n{section}"
    assert re.search(r"does \*\*not\*\* reuse|not reuse the old id", low), (
        "the section must decide the reuse question outright, not leave it "
        f"to the reader:\n{section}"
    )
    assert "pm_activity(run_id=" in section, (
        "the reason to mint a new id is that the slices stay per-process — "
        "say it in terms of the query that reads them"
    )


@pytest.mark.parametrize("path", DOCS)
def test_every_adopted_claim_gets_the_lineage_note(path):
    """``recovered from run <old>``, tagged with the *new* run id."""
    section = _resume(_text(path))
    assert LINEAGE_NOTE in section, (
        f"no {LINEAGE_NOTE!r} note — an adopted claim would have no link back "
        "to the run it came from"
    )
    note_line = next(
        line for line in section.splitlines() if LINEAGE_NOTE in line and "pm_update" in line
    )
    assert "outcome=\"info\"" in note_line, note_line
    assert "run_id=<this run>" in note_line, (
        "the lineage note must be tagged with the *new* run id or step 22 "
        f"will not find it in this run's slice: {note_line}"
    )


# ═══ how the resuming run finds what the dead run did ════════════


@pytest.mark.parametrize("path", DOCS)
def test_the_dead_runs_record_is_read_from_the_activity_log(path):
    """One query, not an inference: ``pm_activity(run_id=<old-run-id>)``."""
    section = _resume(_text(path))
    assert re.search(r"pm_activity\(run_id=<old-run-id>", section), (
        "the section must name the query that returns the dead run's record:\n"
        f"{section}"
    )
    assert "has_more" in section and "offset" in section, (
        "the dead run's record can exceed one page; the section must say to "
        "page it"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_adopt_leave_split_is_decided_for_every_state(path):
    """in-progress → adopt; done → leave; released/parked → leave and report."""
    section = _resume(_text(path))
    low = _lower(section)

    adopt = next(line for line in section.splitlines() if "**adopt**" in line)
    assert "in-progress" in adopt and "claimed_by_run: <old-run-id>" in adopt, adopt
    assert "pm_grab(<task-id>, run_id=<this run>)" in adopt, (
        f"adoption must name the call that performs it: {adopt}"
    )

    done = next(
        line for line in section.splitlines() if "already `done`" in _lower(line)
    )
    assert "leave it" in _lower(done), done

    parked = next(
        line
        for line in section.splitlines()
        if "parked" in _lower(line) and "released" in _lower(line)
    )
    assert "leave the claim alone" in _lower(parked), parked
    assert "report" in _lower(parked), (
        f"a released or parked task is left, but it still belongs in the "
        f"report: {parked}"
    )

    assert "some other id" in low or "now held by someone else" in low, (
        "the section must cover a claim another run already recovered"
    )


# ═══ an adopted task is a retry, not fresh work ══════════════════


@pytest.mark.parametrize("path", DOCS)
def test_an_adopted_task_is_dispatched_as_a_retry(path):
    """A dead worker may have left partial edits; the tree is validated first."""
    section = _resume(_text(path))
    low = _lower(section)
    assert "retry" in low, f"the section never says an adopted task is retried:\n{section}"
    assert "git status --short" in section, (
        "validation can only separate this worker's edits from the dead "
        "worker's leftovers if the tree is snapshotted first"
    )
    assert "died mid-task" in low and "working tree" in low, (
        "the resume dispatch must warn the worker about the partial edits"
    )
    assert "--max" in section, "an adopted dispatch still spends the budget"


@pytest.mark.parametrize("path", DOCS)
def test_the_worker_prompt_has_an_on_resume_line_beside_on_retry(path):
    """The template line that carries the warning into the worker's context."""
    fence = _worker_fence(_text(path))
    assert "<on retry:" in fence, (
        "the <on retry: line is the model this test is built on; it is gone"
    )
    assert ON_RESUME in fence, (
        f"the worker prompt has no {ON_RESUME!r} line, so an adopted task is "
        f"dispatched indistinguishably from fresh work:\n{fence}"
    )
    resume_line = fence[fence.index(ON_RESUME) :]
    resume_line = resume_line[: resume_line.index(">\n") + 1]
    low = _lower(resume_line)
    assert "died mid-task" in low, resume_line
    assert "validate the working" in low and "tree state first" in low, resume_line
    assert "<old-run-id>" in resume_line, (
        f"the worker should be told *which* run died: {resume_line}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_section_points_at_the_on_resume_line_it_relies_on(path):
    """Procedure and template must agree, or one of them is dead text."""
    assert ON_RESUME in _resume(_text(path)), (
        "the resume procedure never mentions the worker-prompt line that "
        "carries its warning"
    )


# ═══ other runs' claims, and the report ══════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_claims_from_other_runs_stay_with_step_3(path):
    """``--resume`` narrows nothing: everything else is classified as before."""
    section = _resume(_text(path))
    low = _lower(section)
    assert "step 3" in low
    assert "stale" in low, (
        "the section must say stale claims from other runs are still "
        "recovered the ordinary way"
    )
    assert "never touched" in low or "never adopt" in low, (
        "human claims are untouchable, --resume or not"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_report_names_the_resumed_run_and_its_adopted_claims(path):
    """Phase 4 has to say where the adopted work came from."""
    section = _resume(_text(path))
    assert "step 22" in _lower(section), (
        "the section must hand the adopted claims to the Phase 4 report step"
    )
    assert "claimed_by_run: <old-run-id> → <this run>" in section, (
        "the adopted claims are exactly that transition in this run's slice; "
        "say so, so no separate bookkeeping is invented"
    )
    step_22 = _section(_text(path), "## Phase 4")
    assert RESUME_FLAG in step_22, (
        "Phase 4 never mentions --resume, so a resumed run's report would not "
        "name the run it resumed"
    )


# ═══ when NOT to resume ══════════════════════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_there_is_a_when_not_to_resume_note(path):
    """Four cases, each of which makes adoption the wrong move."""
    section = _resume(_text(path))
    low = _lower(section)
    assert "when not to resume" in low, (
        f"no when-NOT-to-resume note:\n{section}"
    )
    tail = low[low.index("when not to resume") :]
    assert "human" in tail, "a human-held claim is never adopted"
    assert "verdict" in tail and "done" in tail, (
        "the 'last event is a verdict on a task that is now done' case is missing"
    )
    assert "still emitting events" in tail, (
        "resuming a run that is merely slow races a live process"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_stop_conditions_agree_with_the_resume_section(path):
    """A live resumed run stops the run; ``--auto`` skips instead of racing."""
    stops = _section(_text(path), "## Stop Conditions")
    assert RESUME_FLAG in stops, (
        "the resume section can stop the run, but Stop Conditions never says "
        f"so:\n{stops}"
    )
    assert "--auto" in stops


@pytest.mark.parametrize("path", DOCS)
def test_the_placeholder_admission_is_gone(path):
    """The section is the procedure now, not a note about where one would go."""
    text = _text(path)
    for phrase in BANNED_PHRASES:
        assert phrase not in text, (
            f"{phrase!r} is still in the document — the resume path is still "
            "a placeholder"
        )


@pytest.mark.parametrize("path", DOCS)
def test_the_section_is_self_contained_and_substantial(path):
    """A one-line pointer at step 3 is what this task replaced."""
    section = _resume(_text(path))
    assert len(section.splitlines()) >= 15, (
        f"the resume section is {len(section.splitlines())} lines — that is a "
        "pointer, not a procedure"
    )


# ═══ the pin is not cosmetic — the calls it names are real ═══════


@pytest.mark.parametrize("path", DOCS)
def test_every_call_the_section_names_accepts_the_arguments_it_passes(path):
    """A procedure calling a parameter the server never had recovers nothing."""
    import projectman.server as server

    section = _resume(_text(path))
    calls = re.findall(r"\b(pm_[a-z_]+)\(([^)]*)\)", section)
    assert calls, f"the section names no tool calls at all:\n{section}"
    for name, arglist in calls:
        fn = getattr(server, name, None)
        assert fn is not None, f"the section calls {name}(), which is not a tool"
        params = inspect.signature(fn).parameters
        for kwarg in re.findall(r"(\w+)\s*=", arglist):
            assert kwarg in params, (
                f"the resume section passes {name}({kwarg}=...), but the real "
                f"signature is {sorted(params)}"
            )


# ═══ the procedure, executed against a real store ════════════════

RUN_A = "orch-2026-08-21-dead"
RUN_B = "orch-2026-08-22-live"

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture
def resumable(tmp_project, monkeypatch):
    """A project where run A claimed two tasks and finished one before dying."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in (1, 2):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=3)
    return store


def _yaml(text: str) -> dict:
    return yaml.safe_load(text)


def test_a_resuming_run_reconstructs_and_adopts_from_the_activity_log(resumable):
    """R2 end to end: run B learns run A's state from the log and adopts.

    Run A grabs both tasks and accepts one, then dies.  Run B is given nothing
    but run A's id — everything it does is derived from
    ``pm_activity(run_id=A)`` and the tasks' current status.
    """
    import projectman.server as server

    # ── run A: two claims, one verdict, then it dies ──────────────
    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    server.pm_grab("US-TST-1-2", run_id=RUN_A)
    server.pm_accept(
        "US-TST-1-1",
        note="all DoD met",
        next_task=False,
        run_id=RUN_A,
        evidence={"files": ["src/thing.py"], "dod_met": ["Done"]},
    )

    # ── run B: read the dead run's record, nothing else ───────────
    record = _yaml(server.pm_activity(run_id=RUN_A, limit=100))
    assert record["has_more"] is False, "paging cut the dead run's record short"
    assert all(f"run {RUN_A}" in e for e in record["entries"]), record["entries"]

    touched = sorted({m for e in record["entries"] for m in re.findall(r"US-TST-1-\d", e)})
    assert touched == ["US-TST-1-1", "US-TST-1-2"], touched

    # R2's sort, computed the way the section says to compute it.
    states = {
        tid: _yaml(server.pm_get(tid, fields="status,claimed_by_run"))
        for tid in touched
    }
    adopt = [
        tid
        for tid, s in states.items()
        if s["status"] == "in-progress" and s.get("claimed_by_run") == RUN_A
    ]
    leave = [tid for tid, s in states.items() if s["status"] == "done"]
    assert adopt == ["US-TST-1-2"], (
        f"the log identified the wrong survivor: adopt={adopt} states={states}"
    )
    assert leave == ["US-TST-1-1"], leave

    # ── R1 + R2: adopt under B's own id, then record the lineage ──
    grabbed = _yaml(server.pm_grab("US-TST-1-2", run_id=RUN_B))["grabbed"]["task"]
    assert grabbed["claimed_by_run"] == RUN_B, (
        "a cross-run re-claim did not change hands — the documented adoption "
        "step does not work against the real server"
    )
    server.pm_update(
        "US-TST-1-2",
        outcome="info",
        note=f"recovered from run {RUN_A}",
        run_id=RUN_B,
    )

    # ── the resulting state is what the report is built from ──────
    active = _yaml(server.pm_active())
    claims = {t["id"]: t.get("claimed_by_run") for t in active["active_tasks"]}
    assert claims == {"US-TST-1-2": RUN_B}, (
        f"pm_active should show exactly the adopted claim, held by B: {claims}"
    )

    b_slice = _yaml(server.pm_activity(run_id=RUN_B, limit=100))
    assert b_slice["total"] == 2, b_slice["entries"]
    assert any(
        f"claimed_by_run: {RUN_A} → {RUN_B}" in e for e in b_slice["entries"]
    ), (
        "step 22 finds recovered claims by that transition in this run's "
        f"slice; it is not there: {b_slice['entries']}"
    )

    # A's slice never grows: the two runs stay separable, which is the whole
    # reason R1 mints a new id instead of reusing A's.
    after = _yaml(server.pm_activity(run_id=RUN_A, limit=100))
    assert after["total"] == record["total"], (
        "run B's writes leaked into run A's slice"
    )

    # ...and the lineage is on the task's own run log, for a human reader.
    log = _yaml(server.pm_run_log("US-TST-1-2", limit=5))
    notes = [str(e.get("note", "")) for e in (log if isinstance(log, list) else log["entries"])]
    assert any(f"recovered from run {RUN_A}" in n for n in notes), notes


def test_the_accepted_task_is_not_re_adopted(resumable):
    """R2's 'already done → leave it': re-grabbing a done task must not work."""
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    server.pm_accept("US-TST-1-1", note="done", next_task=False, run_id=RUN_A)

    # The server refuses on its own — an expected negative, not an exception —
    # so "leave it" is what the store enforces and not merely skill prose.
    refusal = _yaml(server.pm_grab("US-TST-1-1", run_id=RUN_B))
    assert refusal["status"] == "not_ready", refusal
    assert any("'done'" in b for b in refusal["blockers"]), refusal

    state = _yaml(server.pm_get("US-TST-1-1", fields="status,claimed_by_run"))
    assert state["status"] == "done", state
    assert state.get("claimed_by_run") != RUN_B, (
        "a completed task was adopted by the resuming run"
    )


# ═══════════════════════════════════════════════════════════════════
# US-PM-14-4 — verification of the acceptance criterion
# "pm-orchestrate has a documented resume path".
#
# The module above pins the prose and the happy path.  What the
# verification task found missing, and what follows here:
#
#   (a) the calls are checked against ``inspect.signature`` on the
#       server module, not against the schemas the MCP client actually
#       sees — a tool could publish a different parameter set;
#   (b) two of R2's four branches are documented but never executed —
#       "released or parked → leave it" and "some other run already
#       recovered it";
#   (c) mint-versus-reuse and the human-claim rule are each pinned in
#       one place, so the *other* places could contradict them;
#   (d) nothing pins ``docs/reference/skills.md``, which describes the
#       same flag to a reader who never opens the skill.
# ═══════════════════════════════════════════════════════════════════

from tests.test_skill_claim_recovery import _run_id_section  # noqa: E402
from tests.test_skill_guidance_tools import _step  # noqa: E402
from tests.test_skill_release_instructions import REPO_ROOT  # noqa: E402
from tests.test_skill_verdict_verbs import _schemas  # noqa: E402

#: the reference page that describes the flag outside the skill itself
SKILLS_DOC = REPO_ROOT / "docs" / "reference" / "skills.md"

#: a third run, which recovered a claim before this one got to it
RUN_C = "orch-2026-08-22-othr"

#: the calls the criterion says the procedure must be able to make
REQUIRED_CALL_KWARGS = [
    ("pm_activity", "run_id"),
    ("pm_grab", "run_id"),
    ("pm_update", "run_id"),
    ("pm_update", "outcome"),
    ("pm_update", "note"),
]

#: the claim metadata the section's opening paragraph branches on
RESUME_CLAIM_KEYS = ("claimed_by_run", "claim_age", "stale")


def _sentence_windows(block: str, pattern: str) -> list[str]:
    """Each match of ``pattern`` with the sentence it sits in."""
    windows = []
    for m in re.finditer(pattern, block):
        start = max(block.rfind(".", 0, m.start()), block.rfind("\n", 0, m.start())) + 1
        ends = [n for n in (block.find(".", m.end()), block.find("\n", m.end())) if n != -1]
        windows.append(block[start : min(ends) if ends else len(block)].strip())
    return windows


# ═══ (a) the calls exist in the schemas a client is served ═══════


@pytest.mark.parametrize("path", DOCS)
def test_every_call_the_section_names_is_a_registered_tool_with_those_parameters(path):
    """Walk the section as a checklist against ``mcp.list_tools()``.

    ``test_every_call_the_section_names_accepts_the_arguments_it_passes``
    above reads ``inspect.signature`` off the server module.  That is the
    Python function; what a resuming orchestrator can actually call is the
    schema the MCP server publishes.  The two can diverge — a parameter can
    be excluded from a tool's schema while the function keeps it — and a
    documented step naming a parameter the client cannot pass is a step that
    cannot be executed without guessing.
    """
    schemas = _schemas()
    section = _resume(_text(path))
    calls = re.findall(r"\b(pm_[a-z_]+)\(([^)]*)\)", section)
    assert calls, f"the section names no tool calls at all:\n{section}"

    named = set()
    for name, arglist in calls:
        assert name in schemas, (
            f"the resume section calls {name}(), which the server does not "
            f"publish as a tool: {sorted(schemas)}"
        )
        props = set(schemas[name].inputSchema.get("properties", {}))
        assert props, f"{name} publishes no input schema at all"
        for kwarg in re.findall(r"(\w+)\s*=", arglist):
            assert kwarg in props, (
                f"the resume section passes {name}({kwarg}=...), but the "
                f"published schema accepts {sorted(props)}"
            )
            named.add((name, kwarg))

    for required in REQUIRED_CALL_KWARGS:
        assert required in named, (
            f"the resume procedure never names {required[0]}({required[1]}=...), "
            "which the criterion requires it to be executable without"
        )


@pytest.mark.parametrize("path", DOCS)
def test_the_claim_fields_the_section_branches_on_are_real_pm_active_keys(
    path, tmp_project, store, monkeypatch
):
    """The section's building blocks, read off a real ``pm_active`` payload."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache, pm_active
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    from tests.test_claim_ownership import _backdate_claim, _story_with_tasks

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id=RUN_A)
    _backdate_claim(store, "US-TST-1-1", minutes=600)

    section = _resume(_text(path))
    quoted = set(re.findall(r"`([a-z_]+)`", section))
    task = yaml.safe_load(pm_active())["active_tasks"][0]

    for key in RESUME_CLAIM_KEYS:
        assert key in quoted, (
            f"the resume section stopped naming `{key}`, which is one of the "
            "facts it says the procedure is built on"
        )
        assert key in task, (
            f"the section tells a resuming run to read `{key}`, but a real "
            f"in-progress task is {sorted(task)}"
        )


# ═══ (b) the branches R2 documents but never executed ════════════


def test_a_released_task_is_left_where_the_dead_run_put_it(resumable):
    """R2, third bullet: a release was a decision — do not adopt it back.

    Run A claims a task and releases it before dying.  Run B, given only A's
    id, must find the release in A's slice and *not* re-claim the task: the
    ordinary step 12 pick owns it now.
    """
    import projectman.server as server

    server.pm_grab("US-TST-1-1", run_id=RUN_A)
    server.pm_release("US-TST-1-1", note="budget reached", run_id=RUN_A)

    record = _yaml(server.pm_activity(run_id=RUN_A, limit=100))
    assert any(
        "US-TST-1-1" in e and f"claimed_by_run: {RUN_A} → None" in e
        for e in record["entries"]
    ), (
        "the release is not visible in the dead run's slice, so a resuming "
        f"run cannot tell it apart from a live claim: {record['entries']}"
    )

    # R2's sort over the ids the record names: nothing to adopt.
    touched = sorted({m for e in record["entries"] for m in re.findall(r"US-TST-1-\d", e)})
    states = {
        tid: _yaml(server.pm_get(tid, fields="status,assignee,claimed_by_run"))
        for tid in touched
    }
    adopt = [
        tid
        for tid, s in states.items()
        if s["status"] == "in-progress" and s.get("claimed_by_run") == RUN_A
    ]
    assert adopt == [], f"a released task was sorted into the adopt list: {states}"
    assert states["US-TST-1-1"]["status"] == "todo", states
    assert not states["US-TST-1-1"].get("assignee"), states

    # ...and run B, having left it alone, has written nothing at all.
    b_slice = _yaml(server.pm_activity(run_id=RUN_B, limit=100))
    assert b_slice["total"] == 0, (
        f"the resuming run touched a released claim: {b_slice['entries']}"
    )
    assert _yaml(server.pm_active())["active_tasks"] == [], (
        "a released task must stay in the pool, not come back as an adoption"
    )


def test_a_claim_a_third_run_already_recovered_is_left_and_reported(resumable):
    """R2, fourth bullet: ``claimed_by_run`` is now some other id.

    Run A dies holding a claim; run C recovers it first.  Run B resuming A
    must read the *current* owner rather than A's last event, and leave it.
    """
    import projectman.server as server

    server.pm_grab("US-TST-1-2", run_id=RUN_A)
    server.pm_grab("US-TST-1-2", run_id=RUN_C)  # a third run got there first

    record = _yaml(server.pm_activity(run_id=RUN_A, limit=100))
    assert any("US-TST-1-2" in e for e in record["entries"]), record["entries"]

    state = _yaml(server.pm_get("US-TST-1-2", fields="status,claimed_by_run"))
    assert state["status"] == "in-progress", state
    assert state["claimed_by_run"] == RUN_C, (
        "the third run's recovery did not take the claim, so this branch "
        f"cannot arise the way R2 describes it: {state}"
    )
    assert state["claimed_by_run"] not in (RUN_A, RUN_B), state

    # A's slice alone would have said "still claimed by A" — the branch only
    # works because R2 re-checks current state before adopting.
    assert _yaml(server.pm_activity(run_id=RUN_B, limit=100))["total"] == 0, (
        "the resuming run adopted a claim another run already recovered"
    )
    assert (
        _yaml(server.pm_get("US-TST-1-2", fields="claimed_by_run"))["claimed_by_run"]
        == RUN_C
    )


# ═══ (c) the document does not contradict itself ═════════════════


@pytest.mark.parametrize("path", DOCS)
def test_mint_versus_reuse_is_decided_the_same_way_in_every_place(path):
    """Flags, Phase 0's run-id section and the Resume section must agree."""
    text = _text(path)
    flag_line = next(
        line for line in _flags(text).splitlines() if line.startswith(f"- `{RESUME_FLAG}")
    )
    run_id = _run_id_section(text)
    section = _resume(text)

    assert re.search(r"mints? its own id", flag_line), (
        f"the Flags entry leaves the id question open: {flag_line}"
    )
    assert "lineage" in flag_line, flag_line
    assert RESUME_FLAG in run_id, (
        "Phase 0 mints the id but never says what --resume does to that, so a "
        f"resuming run has two plausible readings:\n{run_id}"
    )
    assert re.search(r"mints a fresh id", run_id) and "lineage" in run_id, run_id
    assert "lineage" in section, section

    # No place may say to reuse the resumed id: every mention is a refusal.
    for block, where in ((flag_line, "Flags"), (run_id, "Phase 0"), (section, "Resume")):
        for window in _sentence_windows(block, r"[Rr]eus\w*"):
            assert re.search(r"\bnot\b|rather than|would|never", window), (
                f"{where} appears to instruct reusing the resumed run id, "
                f"which contradicts R1: {window!r}"
            )


@pytest.mark.parametrize("path", DOCS)
def test_the_human_claim_rule_reads_the_same_in_all_three_places(path):
    """Step 3, the Resume section and Does-NOT-Do must not disagree."""
    text = _text(path)
    blocks = {
        "step 3": _step(text, "3."),
        "Resume": _resume(text),
        "Does NOT do": _section(text, "## What This Skill Does NOT Do"),
    }
    for where, block in blocks.items():
        assert "orch-" in block, (
            f"{where} states the human-claim rule without the `orch-` prefix "
            f"that decides it:\n{block}"
        )
        low = _lower(block)
        assert any(
            phrase in low
            for phrase in ("never touch", "never adopt", "left alone", "not own")
        ), f"{where} does not say a human claim is left alone:\n{block}"


@pytest.mark.parametrize("path", DOCS)
def test_the_live_run_rule_reads_the_same_in_resume_and_stop_conditions(path):
    """"Still emitting events" must resolve identically in both places."""
    text = _text(path)
    section = _lower(_resume(text))
    stops = _lower(_section(text, "## Stop Conditions"))
    for where, block in (("the Resume section", section), ("Stop Conditions", stops)):
        assert "still emitting events" in block, (
            f"{where} does not name the live-run case, so the two cannot be "
            f"checked against each other:\n{block}"
        )
        assert "--auto" in block and "skip" in block, (
            f"{where} does not say --auto skips the adoption rather than "
            f"stopping:\n{block}"
        )


@pytest.mark.parametrize("path", DOCS)
def test_the_flags_entry_points_at_a_heading_that_exists(path):
    """The Flags table's forward reference must resolve."""
    text = _text(path)
    flag_line = next(
        line for line in _flags(text).splitlines() if line.startswith(f"- `{RESUME_FLAG}")
    )
    title = RESUME_HEADING.removeprefix("## ")
    assert title in flag_line, (
        f"the Flags entry does not name the section holding the procedure: {flag_line}"
    )
    assert RESUME_HEADING in text


# ═══ (d) the reference page describes the same flag ══════════════


def test_the_reference_docs_describe_the_same_resume_flag():
    """``docs/reference/skills.md`` is where a reader meets the flag first."""
    text = SKILLS_DOC.read_text(encoding="utf-8")
    assert f"`{RESUME_FLAG} <run-id>`" in text, (
        f"{SKILLS_DOC} never documents {RESUME_FLAG}, so the flag exists only "
        "inside the skill it belongs to"
    )
    para = next(
        line for line in text.splitlines() if "Resume after a crash" in line
    )
    assert RESUME_HEADING.removeprefix("## ") in para, (
        "the reference page does not name the skill section it summarises: "
        f"{para}"
    )
    for fact in (
        "fresh id",
        LINEAGE_NOTE,
        "pm_activity(run_id=<old>)",
        "has_more",
        ON_RESUME,
        "orch-",
        "retry",
    ):
        assert fact in para, (
            f"the reference page's resume paragraph omits {fact!r}, so it and "
            "the skill describe different procedures"
        )
    for window in _sentence_windows(para, r"[Rr]eus\w*"):
        assert re.search(r"\bnot\b|rather than|would|never", window), window
