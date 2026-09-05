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

from tests.test_orchestrate_skill_size import design_section
from tests.test_skill_guidance_tools import _worker_fence
from tests.test_skill_verdict_verbs import DOCS, _text

# ─── the section under test ──────────────────────────────────────
#
# US-PM-25-6 split this material in two: the *instruction* stayed in the skill,
# shortened to the calls and the decisions a resuming orchestrator has to make,
# while the reasoning behind each rule (R1–R5, the four-way sort, the
# when-NOT-to-resume list) moved to ``docs/reference/orchestrate-design.md``.
# Assertions below therefore run against whichever of the two documents now
# owns the fact — never dropped, because a rule with no recorded reason is the
# next reader's candidate for deletion.

#: the heading this task filled in, as US-PM-25-6 shortened it
RESUME_HEADING = "## Resume"

#: where the resume rationale now lives
DESIGN_RESUME_HEADING = "## Resume protocol"

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


def _design_resume() -> str:
    """The rationale half of the procedure, in the doc the skill links."""
    return design_section(DESIGN_RESUME_HEADING)


def _flat(text: str) -> str:
    """Lowercased, whitespace collapsed — both documents are hard-wrapped."""
    return re.sub(r"\s+", " ", text.lower())


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
def test_the_procedure_is_opt_in_on_the_flag(path):
    """The skill half: the section applies under ``--resume`` and nowhere else.

    What a run does *without* the flag is step 3's business, and step 3 is
    pinned by ``tests/test_skill_claim_recovery.py``; the reasoning for the
    split is asserted against the design doc below.
    """
    section = _lower(_resume(_text(path)))
    assert f"`{RESUME_FLAG}` only" in section or f"{RESUME_FLAG} only" in section, (
        "the section never says it is entered by the flag alone, so a run "
        f"without {RESUME_FLAG} might adopt claims wholesale:\n{section}"
    )


def test_the_design_doc_says_what_a_run_without_the_flag_does():
    """Ordinary per-claim classification keeps applying — say so somewhere."""
    section = _flat(_design_resume())
    assert "without the flag" in section, (
        f"the design doc never covers the no-flag case:\n{section}"
    )
    assert "classification runs as written" in section, (
        "the design doc no longer says the ordinary classification is what "
        f"runs without the flag:\n{section}"
    )


# ═══ mint a new id, record the lineage ═══════════════════════════


@pytest.mark.parametrize("path", DOCS)
def test_the_resuming_run_mints_a_new_id_rather_than_reusing_the_old_one(path):
    """Reuse would merge two processes into one pm_activity(run_id=) slice."""
    section = _resume(_text(path))
    low = _lower(section)
    assert "mint" in low, f"the section never says which id the run runs under:\n{section}"
    assert re.search(r"does \*\*not\*\* reuse|ne(?:ver|ither) reuse|not reuse the old", low), (
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
def test_the_skill_states_the_adopt_criterion_and_leaves_the_rest(path):
    """The executable half of the sort: what is adopted, and by which call.

    A task is adopted only when it is *still* in-progress *and* still held by
    the dead run — the two conditions that make the claim an orphan rather
    than someone else's live work.  Everything else is left, in one clause, so
    the skill cannot be read as adopting a released or re-claimed task.
    """
    section = _resume(_text(path))
    low = _lower(section)

    assert "adopt only" in low, (
        f"the section no longer restricts what may be adopted:\n{section}"
    )
    assert "in-progress" in low and "claimed_by_run: <old-run-id>" in section, (
        f"the adopt criterion no longer names both conditions:\n{section}"
    )
    assert "pm_grab(<task-id>, run_id=<this run>)" in section, (
        f"adoption must name the call that performs it:\n{section}"
    )
    assert "leave the rest" in low, (
        "the section must dispose of every non-adopted state in so many words, "
        f"or a done/released/re-claimed task reads as adoptable:\n{section}"
    )


def test_the_design_doc_decides_the_split_for_every_state():
    """in-progress → adopt; done → leave; released/parked → leave and report.

    Four branches with four reasons; the skill carries only the first.  Each
    of the other three is executed against a real store further down this
    module, so this pins the written decision they implement.
    """
    section = _flat(_design_resume())

    assert "still in-progress under the old id" in section and "adopt" in section, section
    assert "already done" in section and "leave it" in section, section
    assert "released, parked, or back in todo" in section, section
    assert "leave it and report it" in section, (
        "a released or parked task is left, but it still belongs in the report"
    )
    assert "claimed under a different id" in section, (
        "the doc must cover a claim another run already recovered"
    )


# ═══ an adopted task is a retry, not fresh work ══════════════════


@pytest.mark.parametrize("path", DOCS)
def test_an_adopted_task_is_dispatched_as_a_retry(path):
    """A dead worker may have left partial edits; the tree is validated first.

    The snapshot itself is step 14's ``git status --short``, which runs before
    *each* dispatch and so covers an adopted one — pinned in
    ``tests/test_skill_activity_report.py`` and not restated here.  What this
    checks is that the adopted dispatch is a retry carrying the warning.
    """
    text = _text(path)
    section = _resume(text)
    low = _lower(section)
    assert re.search(r"retr(?:y|ies|ied)", low), (
        f"the section never says an adopted task is retried:\n{section}"
    )
    assert ON_RESUME in section, (
        f"the adopted dispatch carries no {ON_RESUME!r} warning:\n{section}"
    )
    assert "died mid-task" in _lower(_worker_fence(text)), (
        "the resume dispatch must warn the worker about the partial edits"
    )


def test_the_design_doc_explains_why_an_adopted_task_is_a_retry():
    """Partial edits, an unvalidated attempt, and a snapshot before dispatch."""
    section = _flat(_design_resume())
    assert "retry" in section and "never as fresh work" in section, section
    assert "snapshotted first" in section, (
        "validation can only separate this worker's edits from the dead "
        f"worker's leftovers if the tree is snapshotted first:\n{section}"
    )
    assert "first* failure" in section or "first failure" in section, (
        "the doc no longer says a failure on an adopted task is a first "
        f"failure — the dead run's attempt was never validated:\n{section}"
    )


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
    assert re.search(r"validate the working[- ]tree", low), (
        "the worker is not told to validate the tree it inherited: "
        f"{resume_line}"
    )
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
    """``--resume`` narrows nothing: everything else is classified as before.

    The skill says it by scope — the section adopts only the named run's
    claims and refuses the rest — while step 3 keeps recovering other runs'
    stale claims the ordinary way.  Both halves are asserted, so a skill that
    let ``--resume`` swallow every stale claim would fail here.
    """
    text = _text(path)
    section = _resume(text)
    low = _lower(section)
    assert "<old-run-id>" in section, (
        f"the section no longer scopes adoption to the named run:\n{section}"
    )
    assert "never adopt" in low, "human claims are untouchable, --resume or not"

    step_3 = _step(text, "3.")
    assert "stale" in _lower(step_3), (
        "step 3 no longer recovers a stale claim from another run, so nothing "
        f"handles the claims --resume does not name:\n{step_3}"
    )


def test_the_design_doc_says_the_flag_narrows_nothing():
    """R4, in the doc that now carries the reasoning."""
    section = _flat(_design_resume())
    assert "narrows nothing" in section, section
    assert "ordinary classification" in section, (
        "the doc no longer says other runs' claims stay with the ordinary "
        f"classification:\n{section}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_report_derives_the_adopted_claims_from_the_log(path):
    """Phase 4 has to say where the adopted work came from.

    No separate bookkeeping: an adopted claim is a ``claimed_by_run`` change
    into this run, and Phase 4 reads exactly that out of this run's slice.
    """
    phase_4 = _section(_text(path), "## Phase 4")
    low = _lower(phase_4)
    assert "recovered claims" in low, (
        "Phase 4 no longer reports the claims this run recovered, so a "
        f"resumed run's report would not name the adopted work:\n{phase_4}"
    )
    assert "claimed_by_run" in phase_4 and "<this run>" in phase_4, (
        "the recovered-claims list must be derived from the run-id transition "
        f"in the log, not from memory:\n{phase_4}"
    )


def test_the_design_doc_says_the_report_needs_no_extra_bookkeeping():
    """R5: the adopted claims are already in this run's slice, with lineage."""
    section = _flat(_design_resume())
    assert "no extra bookkeeping" in section, section
    assert "claimed_by_run: <old> → <this run>" in section, (
        "the doc no longer identifies the adopted claims with the transition "
        f"the report reads:\n{section}"
    )
    assert "lineage note" in section, section


# ═══ when NOT to resume ══════════════════════════════════════════


def test_there_is_a_when_not_to_resume_note():
    """Four cases, each of which makes adoption the wrong move.

    The skill keeps the two that are executable refusals — never a claim
    without the ``orch-`` prefix, never a live run
    (``test_the_live_run_rule_reads_the_same_in_resume_and_stop_conditions``).
    The enumeration with its reasons lives in the design doc.
    """
    section = _flat(_design_resume())
    assert "when not to resume" in section, (
        f"no when-NOT-to-resume note:\n{section}"
    )
    tail = section[section.index("when not to resume") :]
    assert "a human holds it" in tail, "a human-held claim is never adopted"
    assert "verdict on a task now done" in tail, (
        "the 'last event is a verdict on a task that is now done' case is missing"
    )
    assert "still emitting events" in tail, (
        "resuming a run that is merely slow races a live process"
    )
    assert "matched no events" in tail, (
        "the typo/other-project case is missing, so a resume against an "
        "unknown id has no documented outcome"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_stop_conditions_agree_with_the_resume_section(path):
    """A live resumed run stops the run, and both places say so.

    The ``--auto`` half — a live claim is skipped rather than raced — belongs
    to step 3, which is where claims are classified; asserting it in both
    places is what produced two wordings of one rule.
    """
    text = _text(path)
    stops = _section(text, "## Stop Conditions")
    assert RESUME_FLAG in stops, (
        "the resume section can stop the run, but Stop Conditions never says "
        f"so:\n{stops}"
    )
    assert "live run" in _lower(stops), (
        f"Stop Conditions no longer names the live-run case:\n{stops}"
    )
    assert "--auto" in _step(text, "3."), (
        "step 3 no longer says what --auto does with a live claim, so nothing "
        "in the skill decides between skipping and racing it"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_placeholder_admission_is_gone(path):
    """The section is the procedure now, not a note about where one would go."""
    text = _text(path)
    for phrase in BANNED_PHRASES:
        assert phrase not in text, (
            f"{phrase!r} is still in the document — the resume path is still "
            "a placeholder"
        )


def test_the_written_procedure_is_self_contained_and_substantial():
    """A one-line pointer at step 3 is what US-PM-14-8 replaced.

    The procedure moved into the design doc rather than shrinking away: the
    skill's section is now the callable subset, and the full walkthrough — the
    one a human reads after a crash — has to still be somewhere.
    """
    section = _design_resume()
    assert len(section.splitlines()) >= 15, (
        f"the design doc's resume protocol is {len(section.splitlines())} "
        "lines — that is a pointer, not a procedure"
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

    # Since US-PM-25-6 the claim metadata is named once, at step 3, and the
    # resume section spends it; both are read here so the fact stays pinned
    # wherever it is written.  A key may be quoted with the value or the call
    # it appears in — ``stale: true``, ``pm_active(stale_after=<hours>)``.
    text = _text(path)
    where = _resume(text) + "\n" + _step(text, "3.")
    quoted = set(re.findall(r"`([a-z_]+)(?:[:(][^`]*)?`", where))
    task = yaml.safe_load(pm_active())["active_tasks"][0]

    for key in RESUME_CLAIM_KEYS:
        assert key in quoted, (
            f"the procedure stopped naming `{key}`, which is one of the "
            "facts it says the classification is built on"
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
def test_mint_versus_reuse_is_decided_once_and_contradicted_nowhere(path):
    """The id question is answered in the Resume section, and only there.

    It used to be answered three times — Flags, Phase 0 and the section — which
    is three chances to disagree.  US-PM-25-6 left one statement of the rule;
    what still has to hold is that no *other* mention of reuse anywhere in the
    skill reads as an instruction to do it.
    """
    text = _text(path)
    section = _resume(text)
    low = _lower(section)

    assert "mint" in low, f"the section does not decide the id question:\n{section}"
    assert LINEAGE_NOTE in section, (
        f"the old id survives as lineage or not at all:\n{section}"
    )

    # No place may say to reuse the resumed *id*: every such mention is a
    # refusal.  Reuse of anything else — the pre-flight context excerpt, say —
    # is not this rule's business, so windows without an id are skipped.
    for window in _sentence_windows(text, r"[Rr]eus\w*"):
        if not re.search(r"\bid\b|run id", window):
            continue
        assert re.search(r"\bnot\b|rather than|would|never", window), (
            "the skill appears to instruct reusing the resumed run id, "
            f"which contradicts R1: {window!r}"
        )


def test_the_design_doc_gives_the_reason_for_minting_a_fresh_id():
    """R1's reasoning, in its new home: two runs must stay separable."""
    section = _flat(_design_resume())
    assert "new id, old id as lineage" in section, section
    assert "merge two processes into one activity slice" in section, (
        "the doc no longer says why reuse is wrong, so the rule reads as "
        f"arbitrary:\n{section}"
    )
    for window in _sentence_windows(_design_resume(), r"[Rr]eus\w*"):
        assert re.search(r"\bnot\b|rather than|would|never", window), window


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
        low = _lower(block)
        assert any(
            phrase in low
            for phrase in ("never touch", "never adopt", "left alone", "not own")
        ), f"{where} does not say a human claim is left alone:\n{block}"

    # The two places that *act* on the rule must say what decides it; the
    # Does-NOT-Do line is a summary and needs no second copy of the test.
    for where in ("step 3", "Resume"):
        assert "orch-" in blocks[where], (
            f"{where} states the human-claim rule without the `orch-` prefix "
            f"that decides it:\n{blocks[where]}"
        )


@pytest.mark.parametrize("path", DOCS)
def test_the_live_run_rule_reads_the_same_everywhere_it_appears(path):
    """A live run is never adopted — and the three places must not disagree.

    Step 3 decides it (still emitting → skip under ``--auto``), the Resume
    section refuses adoption outright, and Stop Conditions stops a ``--resume``
    aimed at one.  None of the three may read as "adopt anyway".
    """
    text = _text(path)
    step_3 = _lower(_step(text, "3."))
    section = _lower(_resume(text))
    stops = _lower(_section(text, "## Stop Conditions"))

    assert "still emitting" in step_3 and "live" in step_3, (
        f"step 3 no longer names the live-run case:\n{step_3}"
    )
    assert "--auto" in step_3 and "skip" in step_3, (
        f"step 3 no longer says --auto skips a live claim rather than racing "
        f"it:\n{step_3}"
    )
    assert "live run" in section and "never adopt" in section, (
        f"the Resume section no longer refuses a live run's claims:\n{section}"
    )
    assert "live run" in stops and RESUME_FLAG in stops, (
        f"Stop Conditions no longer stops a --resume aimed at a live run:\n{stops}"
    )


def test_the_design_doc_explains_the_live_run_refusal():
    """Racing is the harm; under ``--auto`` skipping avoids it without stopping."""
    section = _flat(_design_resume())
    assert "still emitting events" in section, section
    assert "racing is the harm" in section, (
        f"the doc no longer says why --auto skips rather than stops:\n{section}"
    )


@pytest.mark.parametrize("path", DOCS)
def test_the_flags_entry_points_at_a_heading_that_exists(path):
    """The Flags table's forward reference must resolve."""
    text = _text(path)
    flag_line = next(
        line for line in _flags(text).splitlines() if line.startswith(f"- `{RESUME_FLAG}")
    )
    assert "<run-id>" in flag_line and "claims" in flag_line, (
        f"the Flags entry no longer says what --resume takes and does: {flag_line}"
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
