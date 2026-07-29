"""Expected-negative responses stay successes (US-PM-2-4).

Closes the US-PM-2 acceptance criterion "expected-negative results are
distinguished from failures so pm_grab on a not-ready task is not an error".

Three sites are covered, the ones classified EXPECTED NEGATIVE by
``docs/reference/error-paths-inventory.md`` (3.4, 5.1, 5.2, 5.5):

* ``pm_grab`` on a not-ready task  -> ``status: not_ready``       (observed x12)
* ``pm_docs`` on an uncreated doc  -> ``status: not_created``     (observed x1)
* ``pm_commit`` with a clean tree  -> ``status: nothing_to_commit``

Each is asserted three ways, because "is a success" means three different
things at three different layers:

1. the body is not an ``error:`` envelope and carries the structured shape;
2. the human-readable detail that used to be in the error text survives;
3. ``tools/usage_telemetry/classify.py`` -- the measurement this whole epic
   is keyed on -- no longer counts the real body as a soft error.

Sibling task US-PM-2-5 asserts the converse for genuine failures.
"""

import json

import pytest
import yaml

from tools.usage_telemetry import classify as cf
from tools.usage_telemetry.extract import ToolCall, ToolResult

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: The three fixed keys every expected negative carries. See
#: ``projectman.server._expected_negative``.
SHAPE_KEYS = ("outcome", "status", "message")


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    _store_cache.clear()


# ---------------------------------------------------------------- helpers --


def assert_expected_negative(body: str, status: str) -> dict:
    """Assert *body* is a successful expected negative with reason *status*."""
    # 1. Nothing a failure metric keyed on the error prefix would count.
    assert not body.lstrip().startswith("error:"), body
    data = yaml.safe_load(body)
    assert isinstance(data, dict), body
    # The old shapes leaked an "error" key into the payload; that is what made
    # pm_grab's not-ready answer render as an "error: ..." body at all.
    assert "error" not in data, data

    # 2. The one consistent, machine-readable shape.
    assert list(data)[:3] == list(SHAPE_KEYS), data
    assert data["outcome"] == cf_expected_negative_marker(), data
    assert data["status"] == status, data
    assert isinstance(data["message"], str) and data["message"], data
    return data


def cf_expected_negative_marker() -> str:
    from projectman.server import EXPECTED_NEGATIVE

    return EXPECTED_NEGATIVE


def recorded_call(tool: str, body: str, seq: int = 0) -> ToolCall:
    """A joined :class:`ToolCall` exactly as the harness would record it.

    The transcript envelope is ``json.dumps({"result": <body>})`` -- the same
    thing ``classify.SOFT_ERROR_PATTERNS``' ``envelope`` pattern anchors on --
    so this feeds the classifier the real production string, not a paraphrase.
    """
    call = ToolCall(
        tool_use_id=f"tu-{seq}",
        name=f"mcp__projectman__{tool}",
        input={},
        timestamp="2026-07-29T00:00:00Z",
        session="sess-a",
        session_id="sess-a",
        project="proj",
        source_file="proj/sess-a.jsonl",
        line_no=seq + 1,
        seq=seq,
    )
    call.result = ToolResult(
        tool_use_id=f"tu-{seq}", is_error=False, text=json.dumps({"result": body})
    )
    return call


def recorded_raise(tool: str, exc: Exception, seq: int = 0) -> ToolCall:
    """A joined :class:`ToolCall` for a tool that *raised*, as the harness records it.

    US-PM-2-3 converted the genuine failures from an ``error:`` body into a
    real MCP error, so their transcript entry is no longer a successful result
    at all: FastMCP wraps anything raised out of a tool body and the low-level
    server renders it as a ``CallToolResult`` with ``isError=True`` carrying the
    message as text.  That is ``is_error=True`` here.
    """
    call = recorded_call(tool, "", seq)
    call.result = ToolResult(
        tool_use_id=f"tu-{seq}", is_error=True, text=str(exc)
    )
    return call


def raised_by(fn, *args, **kwargs) -> Exception:
    """Call *fn* and return the exception it raised, failing if it did not."""
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 -- type asserted by callers
        fn(*args, **kwargs)
    return excinfo.value


def classify_body(tool: str, body: str) -> cf.CallClass:
    """Classify one recorded *body* for *tool*."""
    return cf.classify(recorded_call(tool, body))


def classify_corpus(pairs) -> cf.Classification:
    """Run the real corpus-level classifier over ``(tool, body)`` pairs.

    This is the whole instrument -- :func:`classify_all` plus
    :class:`Classification` -- not just the single-call predicate, because the
    number this epic is judged on is a corpus rate, not a per-call verdict.
    """
    return cf.classify_all(
        [recorded_call(tool, body, seq) for seq, (tool, body) in enumerate(pairs)]
    )


def assert_not_a_failure(tool: str, body: str) -> None:
    """The classifier must score this body as a plain success."""
    result = classify_body(tool, body)
    assert result.soft is False
    assert result.hard is False
    assert result.failed is False
    assert result.primary == cf.SUCCESS
    assert cf.soft_error_pattern(json.dumps({"result": body})) is None


def _story_with_task(points=3, body=READY_BODY):
    from projectman.server import pm_create_story, pm_create_task, pm_update

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "A task", body, points=points)


# ------------------------------------------------------- pm_grab not ready --


def test_pm_grab_not_ready_is_a_success(tmp_project):
    """The single highest-volume live soft error must not be an error at all."""
    from projectman.server import pm_grab

    _story_with_task(points=None)

    body = pm_grab("US-TST-1-1")
    data = assert_expected_negative(body, "not_ready")
    assert data["message"] == "task is not ready to grab"


def test_pm_grab_not_ready_keeps_the_blocker_detail(tmp_project):
    """Structure is *added*; the human-readable recovery path is not lost."""
    from projectman.server import pm_grab, pm_update

    _story_with_task(points=None)
    pm_update("US-TST-1-1", assignee="alice")

    data = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert any("no point estimate" in b for b in data["blockers"])
    assert any("already assigned to 'alice'" in b for b in data["blockers"])


def test_pm_grab_not_ready_is_branchable_without_string_matching(tmp_project):
    """A caller decides purely on fields -- never on the prose."""
    from projectman.server import pm_grab

    from projectman.server import pm_create_task

    _story_with_task(points=None)
    not_ready = yaml.safe_load(pm_grab("US-TST-1-1"))

    pm_create_task("US-TST-1", "Ready one", READY_BODY, points=3)
    grabbed = yaml.safe_load(pm_grab("US-TST-1-2"))

    assert not_ready.get("outcome") == cf_expected_negative_marker()
    assert grabbed.get("outcome") is None
    assert "grabbed" in grabbed
    # The old "is this a success?" check keeps working, unchanged.
    assert "grabbed" not in not_ready


def test_pm_grab_not_ready_is_not_a_soft_error(tmp_project):
    from projectman.server import pm_grab

    _story_with_task(points=None)
    assert_not_a_failure("pm_grab", pm_grab("US-TST-1-1"))


def test_pm_grab_still_claims_a_ready_task(tmp_project):
    """Requirement 4: what these calls *do* is unchanged."""
    from projectman.server import pm_grab

    _story_with_task()
    data = yaml.safe_load(pm_grab("US-TST-1-1", assignee="claude"))
    assert data["grabbed"]["task"]["status"] == "in-progress"
    assert data["grabbed"]["task"]["assignee"] == "claude"


def test_pm_grab_not_ready_does_not_claim_the_task(tmp_project):
    from projectman.server import pm_get, pm_grab

    _story_with_task(points=None)
    pm_grab("US-TST-1-1")

    task = yaml.safe_load(pm_get("US-TST-1-1"))
    assert task["status"] == "todo"
    assert task["assignee"] is None


# ------------------------------------------------------ pm_docs not created --


def test_pm_docs_missing_doc_is_a_success(tmp_project):
    """The observed ``VISION.md not found``: a lookup over an optional set."""
    from projectman.server import pm_docs

    body = pm_docs("vision")
    data = assert_expected_negative(body, "not_created")
    assert data["doc"] == "vision"
    assert data["file"] == "VISION.md"
    assert "VISION.md" in data["message"]


def test_pm_docs_missing_doc_is_not_a_soft_error(tmp_project):
    from projectman.server import pm_docs

    assert_not_a_failure("pm_docs", pm_docs("vision"))


def test_pm_docs_unknown_doc_stays_an_error(tmp_project):
    """Inventory 5.1: an unknown doc *name* is a bad argument, not a negative.

    This is the boundary that keeps the expected-negative class honest.
    Inverted by US-PM-2-3: it used to be an ``error:`` *body* (a successful
    result that merely read like a failure); it is now a raised ``ToolError``,
    so the MCP layer sets ``is_error``.  The human-readable message, including
    the list of valid doc names, is preserved verbatim.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    from projectman.server import pm_docs

    with pytest.raises(ToolError) as excinfo:
        pm_docs("nonsense")
    message = str(excinfo.value)
    assert message.startswith("unknown doc 'nonsense'")
    assert "vision" in message
    # The old body prefix is gone, not merely moved into the message.
    assert not message.startswith("error:")


def test_pm_docs_returns_the_doc_when_it_exists(tmp_project):
    """Requirement 4: behaviour unchanged on the positive path."""
    from projectman.server import pm_docs

    (tmp_project / ".project" / "VISION.md").write_text("# Vision\n\nShip it.\n")
    assert "Ship it." in pm_docs("vision")


# ------------------------------------------------ pm_commit nothing to commit --


def test_pm_commit_nothing_to_commit_is_a_success(tmp_git_project, monkeypatch):
    """Idempotent no-op: an orchestrator's clean loop must not log a failure."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit

    body = pm_commit()
    data = assert_expected_negative(body, "nothing_to_commit")
    assert data["message"] == "No .project/ changes to commit"


def test_pm_commit_nothing_to_commit_is_not_a_soft_error(tmp_git_project, monkeypatch):
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit

    assert_not_a_failure("pm_commit", pm_commit())


def test_pm_commit_nothing_to_commit_survives_the_generic_handler(
    tmp_git_project, monkeypatch
):
    """The non-hub route reaches this by *raising*, not by returning a dict.

    ``store.commit_project_changes`` raises ``NothingToCommit`` from
    ``store.py``; without the dedicated ``except`` in ``pm_commit`` it would
    fall through to the generic handler that US-PM-2-3 turns into a real error
    (inventory 3.1, line 1733) and this negative would regress into a failure.
    """
    monkeypatch.chdir(tmp_git_project)
    from projectman.store import NothingToCommit, Store

    with pytest.raises(NothingToCommit):
        Store(tmp_git_project).commit_project_changes()
    # Still a RuntimeError for every pre-existing caller (cli.py, old tests).
    assert issubclass(NothingToCommit, RuntimeError)


def test_pm_commit_still_commits_real_changes(tmp_git_project, monkeypatch):
    """Requirement 4: behaviour unchanged when there *is* something to commit."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit, pm_create_story

    pm_create_story("Feature", "Description")
    data = yaml.safe_load(pm_commit())
    assert data["committed"]["commit_hash"]
    assert "outcome" not in data


# ------------------------------------------------------------- consistency --


def test_all_expected_negatives_share_one_shape(tmp_git_project, monkeypatch):
    """Requirement 2: one shape across tools, not a bespoke shape per tool."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit, pm_docs, pm_grab

    _story_with_task(points=None)
    pm_commit()  # drain the tree the fixture setup dirtied

    bodies = {
        "pm_grab": pm_grab("US-TST-1-1"),
        "pm_docs": pm_docs("vision"),
        "pm_commit": pm_commit(),
    }
    statuses = set()
    for tool, body in bodies.items():
        data = yaml.safe_load(body)
        assert list(data)[:3] == list(SHAPE_KEYS), (tool, data)
        assert data["outcome"] == cf_expected_negative_marker(), tool
        assert_not_a_failure(tool, body)
        statuses.add(data["status"])

    # Distinct reason codes, so a caller branching on `status` never confuses
    # one negative for another.
    assert statuses == {"not_ready", "not_created", "nothing_to_commit"}


def test_expected_negatives_stay_small(tmp_git_project, monkeypatch):
    """Requirement 6: response bytes are a tracked cost for this epic.

    Baseline median is 341 bytes/call (docs/telemetry/baseline-pre-fix.md).
    The envelope itself is three short lines; only pm_grab adds detail, and
    that detail is the pre-existing blocker list.
    """
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit, pm_docs

    assert len(pm_commit()) < 120
    assert len(pm_docs("vision")) < 180


def test_already_correct_negatives_are_still_not_failures():
    """Inventory 3.5: the negatives that were already right stay right.

    Left alone by this task, but they use the same ``status: <code>`` key with
    the same meaning, so the shape above is consistent with them rather than a
    second competing convention.
    """
    from projectman.server import _yaml_dump

    for tool, body in (
        ("pm_malformed", "no malformed files"),
        ("pm_reindex", "reindexed: index.yaml (embeddings not available)"),
        ("pm_web_start", _yaml_dump({"status": "already_running", "port": 8000})),
        ("pm_web_stop", _yaml_dump({"status": "not_running"})),
        ("pm_web_status", _yaml_dump({"running": False})),
    ):
        assert_not_a_failure(tool, body)


def test_the_old_pm_grab_body_was_a_soft_error():
    """Guards the regression this task exists to prevent.

    The pre-change payload rendered as ``error: task is not ready to grab``
    and *was* counted as a soft error (12 real calls). If a future change
    reintroduces a leading ``error`` key, this shows what it costs.
    """
    old_body = _yaml_dump_old_grab()
    assert cf.soft_error_pattern(json.dumps({"result": old_body})) == "envelope"
    assert classify_body("pm_grab", old_body).primary == cf.SOFT_ERROR


def _yaml_dump_old_grab() -> str:
    from projectman.server import _yaml_dump

    return _yaml_dump(
        {"error": "task is not ready to grab", "blockers": ["no point estimate"]}
    )


# ------------------------------------------- the measurement loop closes --
#
# Everything above asserts one call at a time. The claim this epic actually
# makes is about a *rate* over a corpus, produced by
# ``tools/usage_telemetry/classify.py``. If the instrument still counted these
# bodies, every number the epic reports would be wrong -- so the instrument is
# run here, on the real bodies, end to end.


def _three_negatives() -> list[tuple[str, str]]:
    """The three converted sites' real bodies, at their observed volumes.

    12 x ``pm_grab`` not-ready and 1 x ``pm_docs`` not-created are the counts
    the story quotes from the Study B corpus; ``pm_commit`` on a clean tree
    is the orchestrator's idempotent loop.
    """
    from projectman.server import pm_commit, pm_docs, pm_grab

    _story_with_task(points=None)
    pm_commit()  # drain the tree the setup above dirtied
    grab, docs, commit = pm_grab("US-TST-1-1"), pm_docs("vision"), pm_commit()
    return [("pm_grab", grab)] * 12 + [("pm_docs", docs)] + [("pm_commit", commit)] * 3


def test_a_corpus_of_expected_negatives_measures_a_zero_failure_rate(
    tmp_git_project, monkeypatch
):
    """The epic's own instrument, run over the epic's own output.

    Not "no call is soft" -- the actual reported figures: the combined true
    failure rate, the exclusive partition, the per-tool table and the
    top-messages list a study would quote from.
    """
    monkeypatch.chdir(tmp_git_project)
    report = classify_corpus(_three_negatives())

    assert report.total == 16
    assert report.failures == 0
    assert report.failure_rate == 0.0
    assert (report.soft, report.hard, report.malformed) == (0, 0, 0)
    assert report.successes == report.total
    assert report.primary_counts == {
        cf.MALFORMED_INPUT: 0,
        cf.HARD_ERROR: 0,
        cf.SOFT_ERROR: 0,
        cf.SUCCESS: 16,
        cf.UNMATCHED: 0,
    }
    assert set(report.soft_patterns.values()) == {0}
    assert report.top_messages() == []
    assert report.overlaps == {}

    # Per-tool, because a study quotes the per-tool table and pm_grab is the
    # row that carried this epic's headline soft-error count.
    for tool, row in report.by_tool().items():
        assert row.failures == 0, tool
        assert row.failure_rate == 0.0, tool
        assert row.successes == row.calls, tool

    summary = report.as_dict()
    assert summary["rates"]["combined_failure_rate"] == 0.0
    assert summary["failures"] == 0
    assert summary["top_soft_messages"] == []


def test_the_measured_rate_moves_by_exactly_the_converted_calls(tmp_project):
    """Before/after on the same 12 calls -- 100% measured, then 0%.

    This is the delta the epic claims. The *only* thing that changed between
    the two corpora is the response body.
    """
    old = classify_corpus([("pm_grab", _yaml_dump_old_grab())] * 12)
    assert old.failure_rate == 1.0
    assert old.soft == 12
    assert old.primary_counts[cf.SOFT_ERROR] == 12
    assert old.top_messages() == [("pm_grab", "task is not ready to grab", 12)]

    from projectman.server import pm_grab

    _story_with_task(points=None)
    new = classify_corpus([("pm_grab", pm_grab("US-TST-1-1"))] * 12)
    assert new.total == old.total
    assert new.failure_rate == 0.0
    assert old.failures - new.failures == 12


def test_the_instrument_still_sees_genuine_failures_alongside_them(tmp_project):
    """The metric is fixed, not blinded.

    A corpus of 12 expected negatives plus 2 real failures must report exactly
    2 -- if `outcome: expected_negative` could suppress a real failure, the
    epic would have bought a nicer number rather than a truer one.

    Inverted by US-PM-2-3: the two real failures no longer produce a body at
    all, so they arrive as *hard* errors rather than soft ones.  The headline
    number is deliberately unchanged -- still 2 failures out of 14 -- which is
    the point: converting a soft error into a real one moves it between
    columns without hiding it.
    """
    from projectman.server import pm_get, pm_grab

    _story_with_task(points=None)
    negatives = [
        recorded_call("pm_grab", pm_grab("US-TST-1-1"), seq) for seq in range(12)
    ]
    failures = [
        recorded_raise("pm_get", raised_by(pm_get, "US-TST-9-9"), 12),
        recorded_raise("pm_grab", raised_by(pm_grab, "US-TST-9-9"), 13),
    ]

    report = cf.classify_all(negatives + failures)
    assert report.total == 14
    assert report.failures == 2
    assert report.hard == 2
    # The whole point of the conversion: nothing is a soft error any more.
    assert report.soft == 0
    assert report.failure_rate == pytest.approx(2 / 14)
    # top_messages only ranks soft errors, so it is now empty -- the failures
    # are counted, just no longer as bodies.
    assert report.top_messages() == []
    # The human-readable message survived the conversion.
    assert "Task not found: US-TST-9-9" in failures[0].result.text


# ---------------------------------------------------- negative controls --
#
# The cheapest way to make this epic's metric read 0% is to stamp
# `expected_negative` on everything. These tests are what makes that fail.


def failure_signal(fn, *args, **kwargs) -> str:
    """How a call presents itself: raised / soft_error / expected_negative / ok.

    Written to survive US-PM-2-3, which converts several of these bodies into
    raised errors -- a raise is still "a failure", which is all these assert.
    """
    try:
        body = fn(*args, **kwargs)
    except Exception:
        return "raised"
    if cf.soft_error_pattern(json.dumps({"result": body})) is not None:
        return "soft_error"
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return "ok"
    if isinstance(data, dict) and data.get("outcome") == cf_expected_negative_marker():
        return "expected_negative"
    return "ok"


def test_genuine_failures_are_never_expected_negatives(tmp_project):
    """Bad ids and bad arguments must stay distinguishable from a valid "no"."""
    from projectman.server import (
        pm_archive,
        pm_batch_get,
        pm_docs,
        pm_estimate,
        pm_get,
        pm_grab,
        pm_update,
    )

    cases = {
        "pm_get missing id": (pm_get, ("US-TST-9-9",)),
        "pm_grab missing id": (pm_grab, ("US-TST-9-9",)),
        "pm_update missing id": (pm_update, ("US-TST-9-9",)),
        "pm_archive missing id": (pm_archive, ("US-TST-9-9",)),
        "pm_estimate missing id": (pm_estimate, ("US-TST-9-9",)),
        "pm_docs unknown name": (pm_docs, ("nonsense",)),
        "pm_batch_get bad type": (pm_batch_get, ("task",)),
    }
    for label, (fn, args) in cases.items():
        assert failure_signal(fn, *args) in {"raised", "soft_error"}, label


def test_pm_grabs_two_negative_branches_are_distinguishable(tmp_project):
    """The sharpest control: same tool, one valid "no" and one failure.

    ``pm_grab`` on a not-ready task is an expected negative; ``pm_grab`` on an
    id that does not exist is a failure. If the discriminator were applied by
    tool rather than by branch, these two would collapse into one.
    """
    from projectman.server import pm_grab

    _story_with_task(points=None)
    assert failure_signal(pm_grab, "US-TST-1-1") == "expected_negative"
    assert failure_signal(pm_grab, "US-TST-9-9") in {"raised", "soft_error"}


def test_a_failure_never_carries_the_discriminator(tmp_project):
    """No failure may claim to be an expected negative.

    Inverted by US-PM-2-3: these two no longer return a body, so the assertion
    moves from "the body must not carry the marker" to the stronger "there is
    no body, and the classifier still scores the call as failed".
    """
    from projectman.server import pm_docs, pm_get

    for tool, fn, args in (
        ("pm_get", pm_get, ("US-TST-9-9",)),
        ("pm_docs", pm_docs, ("nonsense",)),
    ):
        exc = raised_by(fn, *args)
        assert cf_expected_negative_marker() not in str(exc)
        assert cf.classify(recorded_raise(tool, exc)).failed is True


# ------------------------------------------- the discriminator is usable --


def test_status_codes_are_stable_identifiers_not_prose(tmp_git_project, monkeypatch):
    """Requirement: branch on a value, never parse a sentence.

    A ``status`` a caller can put in a dispatch table has to be an identifier:
    lowercase, snake_case, no whitespace, no punctuation, and not just the
    message repeated.
    """
    monkeypatch.chdir(tmp_git_project)
    import re

    from projectman.server import pm_commit, pm_docs, pm_grab

    _story_with_task(points=None)
    pm_commit()

    identifier = re.compile(r"^[a-z][a-z0-9_]*$")
    for body in (pm_grab("US-TST-1-1"), pm_docs("vision"), pm_commit()):
        data = yaml.safe_load(body)
        assert identifier.match(data["status"]), data["status"]
        assert len(data["status"]) <= 40, data["status"]
        assert data["status"] != data["message"]
        # The prose is prose, and it is not what anyone branches on.
        assert " " in data["message"]


def test_a_caller_branches_with_no_string_matching(tmp_git_project, monkeypatch):
    """A literal dispatch table over ``status`` routes every negative.

    No ``in``, no ``startswith``, no regex over the message -- two dict
    lookups. That is the acceptance criterion's "distinguished from failures"
    stated as code a caller would actually write.
    """
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit, pm_docs, pm_grab

    _story_with_task(points=None)
    pm_commit()

    handlers = {
        "not_ready": "wait",
        "not_created": "create it",
        "nothing_to_commit": "carry on",
    }
    routed = []
    for body in (pm_grab("US-TST-1-1"), pm_docs("vision"), pm_commit(), pm_grab("US-TST-1-1")):
        data = yaml.safe_load(body)
        if data.get("outcome") == cf_expected_negative_marker():
            routed.append(handlers[data["status"]])
    assert routed == ["wait", "create it", "carry on", "wait"]


def test_status_codes_do_not_collide_with_the_pre_existing_ones():
    """Inventory 3.5 already uses ``status``; the new codes must not overlap.

    Otherwise ``status: not_running`` from ``pm_web_stop`` and a new negative
    could mean two different things in the same field.
    """
    new = {"not_ready", "not_created", "nothing_to_commit"}
    pre_existing = {"already_running", "not_running", "error"}
    assert new.isdisjoint(pre_existing)


# --------------------------------- inventory 3.5, exercised for real --


def test_already_correct_negatives_from_the_real_tools_are_not_failures(tmp_project):
    """Inventory 3.5 asserted against live output, not against literals.

    ``test_already_correct_negatives_are_still_not_failures`` above pins
    hard-coded strings, which cannot notice the code drifting away from them.
    These are the bodies the tools actually return on an empty project.

    Finding recorded here rather than fixed (out of scope for US-PM-2-6): none
    of these carry the ``outcome`` discriminator, and two are not even mappings
    -- ``pm_malformed`` returns the bare sentence ``no malformed files`` and
    ``pm_search`` returns ``[]``. They are correctly *not failures*, which is
    what this task's criterion requires, but a caller still cannot branch on
    them uniformly. Converting them is a separate change.
    """
    from projectman.server import (
        pm_active,
        pm_activity,
        pm_board,
        pm_list_sprints,
        pm_malformed,
        pm_search,
        pm_web_status,
    )

    bodies = {
        "pm_malformed": pm_malformed(),
        "pm_search": pm_search("zzzz-no-such-term-zzzz"),
        "pm_board": pm_board(),
        "pm_active": pm_active(),
        "pm_activity": pm_activity(),
        "pm_list_sprints": pm_list_sprints(),
        "pm_web_status": pm_web_status(),
    }
    for tool, body in bodies.items():
        assert not body.lstrip().startswith("error:"), (tool, body)
        assert_not_a_failure(tool, body)
        data = yaml.safe_load(body)
        # No competing convention: either the discriminator is absent, or it
        # means what this task made it mean.
        if isinstance(data, dict) and "outcome" in data:
            assert data["outcome"] == cf_expected_negative_marker(), tool

    report = classify_corpus(list(bodies.items()))
    assert report.failure_rate == 0.0
    assert report.successes == report.total == len(bodies)


# -------------------------------------------------- pm_done_next: landed --


def test_pm_done_next_with_no_next_task_is_a_success(tmp_project):
    """US-PM-2-6's second site, now that the tool is in this checkout.

    This test replaces the one that proved ``pm_done_next`` was absent (the
    checkout was 12 commits behind; see ``docs/reference/error-paths-inventory.md``
    7.1).  The shape asserted here is the one
    :func:`test_the_shape_pm_done_next_must_adopt_is_already_valid` pinned in
    advance of the port, driven for real against the only task in the project.
    """
    from projectman.server import pm_done_next, pm_grab

    _story_with_task()
    pm_grab("US-TST-1-1")

    body = pm_done_next("US-TST-1-1", note="did it")
    data = assert_expected_negative(body, "no_next_task")
    assert data["message"] == "no ready task follows US-TST-1-1"
    # Completing the task is not the part that had no answer -- the work the
    # call actually did survives alongside the negative.
    assert data["completed"] == {
        "id": "US-TST-1-1",
        "status": "done",
        "run_log": "success",
    }
    assert data["next"] is None
    assert "see pm_board" in data["next_info"]
    assert_not_a_failure("pm_done_next", body)


def test_pm_done_next_no_next_task_is_not_counted_as_a_soft_error(tmp_project):
    """The instrument agrees, at the corpus rate this epic is judged on.

    89 of 413 observed ``pm_done_next`` calls ended this way -- the highest-
    traffic negative of any tool -- so it is the single largest contributor to
    the measured soft-error rate if it is scored wrong.
    """
    from projectman.server import pm_done_next, pm_grab

    _story_with_task()
    pm_grab("US-TST-1-1")
    body = pm_done_next("US-TST-1-1")

    assert classify_corpus([("pm_done_next", body)] * 89).failure_rate == 0.0


def test_the_shape_pm_done_next_must_adopt_is_already_valid():
    """The port-forward contract, executable today.

    Inventory 7.1: upstream, ``next: null`` with a ``next_info`` hint is the
    highest-traffic negative of any tool. It is the same kind of answer as
    ``not_ready`` -- the call worked, the answer is "none" -- so it adopts this
    shape with ``status: no_next_task`` and the hint kept as detail. Asserted
    here so the shape is known to accommodate it before the port, rather than
    discovered not to afterwards.
    """
    from projectman.server import _expected_negative

    body = _expected_negative(
        "no_next_task",
        "no ready task follows US-TST-1-1",
        next=None,
        next_info={"blocked": 2, "ready": 0},
    )
    data = assert_expected_negative(body, "no_next_task")
    # The detail a caller needs survives, including an explicit null.
    assert "next" in data and data["next"] is None
    assert data["next_info"] == {"blocked": 2, "ready": 0}
    assert_not_a_failure("pm_done_next", body)
    assert classify_corpus([("pm_done_next", body)] * 89).failure_rate == 0.0


def test_the_helper_documents_the_port_forward():
    """The note must live in the code, not only in a task description."""
    from projectman.server import _expected_negative

    doc = _expected_negative.__doc__ or ""
    assert "pm_done_next" in doc
    assert "error-paths-inventory.md" in doc
