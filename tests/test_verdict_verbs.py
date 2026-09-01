"""The four verdict verbs (US-PM-8-7).

`docs/reference/verdict-verbs-contract.md` is the binding design.  Its
governing rule, the sibling of the claim/release one:

    A verdict is said by the verb, never by a values triple the caller must
    remember.

`pm-orchestrate` step 19 has exactly four terminal moves — Accept, Retry,
Park, Accept-as-review — and each used to be a generic `pm_update` where the
model had to remember the right status + outcome + note triple.  The measured
result: 13% of `status=done` writes carried no run-log entry at all, and the
outcome vocabulary collapsed to ~90% `success`.

So the properties under test here are structural, not advisory:

* `status` and `outcome` are **not parameters** on any of the four verbs —
  there is no way to call `pm_park` and get `success`, and no way to reach
  `done` without `success`;
* `note` is **required and non-blank**, and combined with the fixed outcome
  that makes a run-log entry unavoidable — the mechanism behind the story's
  "share of completions lacking a run-log entry drops to zero";
* the omitted-note case is rejected *before* any write, so a rejected verdict
  never leaves half of itself on disk.

Covers contract §5's "US-PM-8-1" and "US-PM-8-2" bullets and the "also worth
covering" list.  US-PM-8-1/-2/-4 extend these; §4's backwards-compatibility
surface is pinned separately in `tests/test_pm_update_compat.py`.
"""

import inspect
import pathlib

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.store import RUN_LOG_NOTE_LIMIT, Store

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: verb → (status on disk, run-log outcome, response key, keeps assignee?)
VERDICTS = {
    "pm_accept": ("done", "success", "completed", True),
    "pm_retry": ("todo", "failed", "retried", False),
    "pm_park": ("review", "blocked", "parked", False),
    "pm_review": ("review", "partial", "reviewed", False),
}
VERB_NAMES = sorted(VERDICTS)
#: the three that share the `pm_release` response shape
SIMPLE_VERBS = ["pm_park", "pm_retry", "pm_review"]


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _seed(tmp_project, n: int = 1) -> Store:
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, n + 1):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    return store


@pytest.fixture
def task(tmp_project) -> str:
    """One story, one ready task, claimed by `claude`."""
    store = _seed(tmp_project)
    store.claim_task("US-TST-1-1", "claude")
    return "US-TST-1-1"


def _verb(name):
    import projectman.server as server

    return getattr(server, name)


def _fresh(tmp_project) -> Store:
    """A Store reading straight from disk, so nothing is answered from cache."""
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _on_disk(tmp_project, item_id: str):
    return _fresh(tmp_project).get_task(item_id)[0]


def _run_log(tmp_project, item_id: str) -> list:
    return _fresh(tmp_project).get_run_log(item_id)


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


def _schemas() -> dict:
    from projectman.server import mcp as mcp_server

    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ═══ §5 / US-PM-8-1 — structural status and outcome ═════════════


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_the_verb_is_registered_as_a_tool(verb):
    assert verb in _schemas()


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_status_and_outcome_are_not_parameters(verb):
    """The acceptance criterion itself: the verdict is in the verb's name.

    If either were a parameter there would be a way to spell `pm_park` +
    `success`, and the whole point of the four verbs would be gone.
    """
    parameters = set(inspect.signature(_verb(verb)).parameters)
    assert "status" not in parameters, verb
    assert "outcome" not in parameters, verb

    properties = set(_schemas()[verb].inputSchema.get("properties", {}))
    assert "status" not in properties, verb
    assert "outcome" not in properties, verb


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_the_verb_leaves_its_documented_status_and_outcome(tmp_project, task, verb):
    status, outcome, _, _ = VERDICTS[verb]

    _verb(verb)(task, note="a real verdict note")

    assert _on_disk(tmp_project, task).status.value == status
    entries = _run_log(tmp_project, task)
    assert len(entries) == 1, entries
    assert entries[0].outcome.value == outcome
    # The entry records the *post*-update status: pm_park reads review/blocked.
    assert entries[0].status == status


@pytest.mark.parametrize("verb", SIMPLE_VERBS)
def test_retry_park_and_review_clear_the_assignee(tmp_project, task, verb):
    """The task is going back to the pool or to a human — a stale holder
    blocks the next `pm_grab`."""
    assert _on_disk(tmp_project, task).assignee == "claude"

    result = yaml.safe_load(_verb(verb)(task, note="handing it on"))

    key = VERDICTS[verb][2]
    assert _on_disk(tmp_project, task).assignee is None
    assert result[key]["from_assignee"] == "claude"
    assert result[key]["from_status"] == "in-progress"
    assert result[key]["task"]["assignee"] is None


def test_pm_accept_preserves_the_assignee(tmp_project, task):
    """A done task records who did it — attribution, not a stale holder."""
    yaml.safe_load(_verb("pm_accept")(task, note="all DoD items met"))

    assert _on_disk(tmp_project, task).assignee == "claude"


@pytest.mark.parametrize("verb", SIMPLE_VERBS)
def test_retry_park_and_review_accept_a_done_task(tmp_project, task, verb):
    """The common case: a worker self-reported done and failed validation.

    Only `pm_accept` guards; refusing this would leave the orchestrator with
    no way to overturn a bad self-report.
    """
    Store(tmp_project).update(task, status="done")

    result = yaml.safe_load(_verb(verb)(task, note="validation failed"))

    assert _on_disk(tmp_project, task).status.value == VERDICTS[verb][0]
    assert result[VERDICTS[verb][2]]["from_status"] == "done"


def test_pm_retry_reopens_a_done_task_to_todo(tmp_project, task):
    Store(tmp_project).update(task, status="done")

    _verb("pm_retry")(task, note="tests are still red")

    meta = _on_disk(tmp_project, task)
    assert meta.status.value == "todo"
    assert meta.assignee is None


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_the_verb_accepts_the_id_alias(tmp_project, task, verb):
    _verb(verb)(id=task, note="spelled with the generic id")

    assert _on_disk(tmp_project, task).status.value == VERDICTS[verb][0]


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("smuggled", ["status", "outcome"])
def test_the_triple_cannot_be_overridden_over_the_wire(tmp_project, task, verb, smuggled):
    """The guarantee is enforced by the *values*, not by an argument check.

    `test_status_and_outcome_are_not_parameters` proves neither name is in
    the published `inputSchema`; this is the other half — what actually
    happens when a caller sends one anyway.  FastMCP validates arguments
    against a model built from the signature and drops what it does not
    know, so the smuggled key is neither rejected nor honoured: the verdict
    still lands exactly where the verb says it does.  That is the property
    the acceptance criterion needs — `pm_park` + `success` is unreachable by
    any spelling.
    """
    status, outcome, _, _ = VERDICTS[verb]
    # A value from a *different* verdict, so honouring it would be visible.
    smuggled_value = "done" if smuggled == "status" else "success"
    if verb == "pm_accept":
        smuggled_value = "todo" if smuggled == "status" else "failed"

    is_error, body = _call_over_the_wire(
        verb,
        {"task_id": task, "note": "a verdict note", smuggled: smuggled_value},
    )

    assert is_error is False, body
    assert _on_disk(tmp_project, task).status.value == status
    entries = _run_log(tmp_project, task)
    assert len(entries) == 1, entries
    assert entries[0].outcome.value == outcome


# ═══ §1 — the verb table in server.py is the one in the contract ═


def _contract_table() -> dict:
    """Parse the four-verb table out of contract §1.

    The doc is binding, so drift between it and `server._VERDICTS` is a
    defect in one of the two.  Reading the markdown makes that a test
    failure instead of a comment nobody re-reads.
    """
    doc = (
        pathlib.Path(__file__).resolve().parent.parent
        / "docs"
        / "reference"
        / "verdict-verbs-contract.md"
    )
    rows = {}
    for line in doc.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not cells[0].startswith("`pm_"):
            continue
        verb = cells[0].strip("`")
        status, outcome = cells[2].strip("`"), cells[3].strip("`")
        keeps_assignee = "kept" in cells[4]
        rows[verb] = (status, outcome, keeps_assignee)
    return rows


def test_the_contract_table_lists_exactly_the_four_verbs():
    assert sorted(_contract_table()) == VERB_NAMES


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_the_contract_table_matches_the_verdicts_under_test(verb):
    """Guards this module's own `VERDICTS` constant against the doc."""
    status, outcome, keeps_assignee = _contract_table()[verb]

    assert (status, outcome) == VERDICTS[verb][:2], verb
    assert keeps_assignee is VERDICTS[verb][3], verb


@pytest.mark.parametrize("verb", SIMPLE_VERBS)
def test_server_verdicts_table_matches_the_contract(verb):
    """`_VERDICTS` is the literal source of the status/outcome pair for the
    three simple verbs — assert the tuple itself, not just its effect."""
    from projectman.server import _VERDICTS

    status, outcome, _ = _VERDICTS[verb]
    assert (status, outcome) == _contract_table()[verb][:2], verb


def test_pm_accept_status_and_outcome_match_the_contract(tmp_project, task):
    """`pm_accept` is not in `_VERDICTS` — `_do_accept` writes `done` /
    `success` as literals, so pin them against the doc through a real call."""
    status, outcome, _ = _contract_table()["pm_accept"]

    result = yaml.safe_load(_verb("pm_accept")(task, note="all DoD items met"))

    assert result["completed"]["status"] == status
    assert result["completed"]["run_log"] == outcome
    assert _on_disk(tmp_project, task).status.value == status
    assert _run_log(tmp_project, task)[0].outcome.value == outcome


# ═══ §5 / US-PM-8-2 — outcome cannot be omitted ═════════════════


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_note_is_required_in_the_tool_schema(verb):
    """FastMCP rejects the call before the body runs, so an omitted note can
    never leave half a verdict on disk."""
    schema = _schemas()[verb].inputSchema
    assert "note" in schema.get("required", []), (verb, schema.get("required"))
    # ...and the operand's two spellings stay optional, as everywhere else.
    assert "task_id" not in schema.get("required", [])
    assert "id" not in schema.get("required", [])


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_omitting_the_note_over_the_wire_is_rejected(tmp_project, task, verb):
    is_error, body = _call_over_the_wire(verb, {"task_id": task})

    assert is_error is True, body
    assert _on_disk(tmp_project, task).status.value == "in-progress"
    assert _run_log(tmp_project, task) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_note_is_a_pre_write_error(tmp_project, task, verb, blank):
    """Whitespace is not a run-log entry.  Nothing may be written."""
    with pytest.raises(ToolError):
        _verb(verb)(task, note=blank)

    assert _on_disk(tmp_project, task).status.value == "in-progress"
    assert _run_log(tmp_project, task) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_calling_the_verb_with_no_note_at_all_raises(tmp_project, task, verb):
    """Direct Python callers never went through the schema; the unfilled
    default arrives as `Ellipsis` and must be caught the same way."""
    with pytest.raises(ToolError):
        _verb(verb)(task)

    assert _on_disk(tmp_project, task).status.value == "in-progress"
    assert _run_log(tmp_project, task) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_every_verb_call_appends_exactly_one_entry_with_a_non_null_outcome(
    tmp_project, task, verb
):
    _verb(verb)(task, note="the one and only entry")

    entries = _run_log(tmp_project, task)
    assert len(entries) == 1, entries
    assert entries[0].outcome is not None
    assert entries[0].note == "the one and only entry"


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_an_oversized_note_is_truncated_not_rejected(tmp_project, task, verb):
    """The verdict must land regardless: truncation is reported, never fatal."""
    note = "x" * (RUN_LOG_NOTE_LIMIT + 500)

    result = yaml.safe_load(_verb(verb)(task, note=note))

    assert _on_disk(tmp_project, task).status.value == VERDICTS[verb][0]
    assert result["note_truncated"] is True
    assert result["note_original_length"] == RUN_LOG_NOTE_LIMIT + 500
    assert result["note_stored_length"] == RUN_LOG_NOTE_LIMIT
    # The stored note includes the `...[truncated N chars]` marker, so more
    # original characters are dropped than the plain overshoot.
    assert result["note_dropped_chars"] >= 500
    assert result["note_limit"] == RUN_LOG_NOTE_LIMIT
    entries = _run_log(tmp_project, task)
    assert len(entries) == 1
    assert len(entries[0].note) == RUN_LOG_NOTE_LIMIT


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_a_note_that_fits_reports_no_truncation(tmp_project, task, verb):
    """Absence of the fields means "stored whole" — response bytes are a
    tracked cost, so the common path stays the size it was."""
    result = yaml.safe_load(_verb(verb)(task, note="short and complete"))

    assert "note_truncated" not in result
    assert "note_limit" not in result


def _verdict_bytes(tmp_project, item_id: str) -> tuple:
    """Every byte a verdict could touch: the task file and its run log."""
    task_path = tmp_project / ".project" / "tasks" / f"{item_id}.md"
    log_path = tmp_project / ".project" / "logs" / f"{item_id}.jsonl"
    return (
        task_path.read_bytes(),
        log_path.read_bytes() if log_path.exists() else None,
    )


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("note", [None, "", "   \n\t "], ids=["omitted", "empty", "blank"])
def test_a_rejected_note_leaves_the_task_byte_identical(tmp_project, task, verb, note):
    """Pre-write means pre-write.

    Not "the status still happens to read in-progress" but *nothing changed
    at all*: same task-file bytes, no run log created.  The assignee matters
    on its own — three of the four verbs clear it, so a half-applied
    rejection would release a task nobody had a verdict on.
    """
    assert _on_disk(tmp_project, task).assignee == "claude"
    before = _verdict_bytes(tmp_project, task)

    with pytest.raises(ToolError):
        _verb(verb)(task) if note is None else _verb(verb)(task, note=note)

    assert _verdict_bytes(tmp_project, task) == before
    after = _on_disk(tmp_project, task)
    assert after.status.value == "in-progress"
    assert after.assignee == "claude"
    assert _run_log(tmp_project, task) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("blank", ["", "   \n\t "], ids=["empty", "whitespace"])
def test_a_blank_note_is_rejected_over_the_wire_too(tmp_project, task, verb, blank):
    """The schema can only say `note` is a required string — whitespace
    satisfies it, so the guard has to hold on the real transport as well and
    not just for direct Python callers."""
    before = _verdict_bytes(tmp_project, task)

    is_error, body = _call_over_the_wire(verb, {"task_id": task, "note": blank})

    assert is_error is True, body
    assert _verdict_bytes(tmp_project, task) == before
    assert _run_log(tmp_project, task) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_a_truncated_note_still_carries_the_verbs_fixed_outcome(tmp_project, task, verb):
    """Truncation is a property of the note alone: the outcome is the verb's,
    never the caller's, so the longest note in the world cannot leave an
    entry with a missing or wrong outcome behind it."""
    _verb(verb)(task, note="y" * (RUN_LOG_NOTE_LIMIT + 10))

    entries = _run_log(tmp_project, task)
    assert len(entries) == 1, entries
    assert entries[0].outcome is not None
    assert entries[0].outcome.value == VERDICTS[verb][1]
    assert entries[0].note


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"note": ""}, {"outcome": "partial"}],
    ids=["no-note", "empty-note", "partial-and-no-note"],
)
def test_pm_done_next_cannot_reach_done_without_a_run_log_entry(tmp_project, kwargs):
    """§3: the legacy terminal path is the one that carried the 13% hole.

    Whatever the caller omits — the note, or the note while naming a
    non-default outcome — the `done` write is accompanied by exactly one
    entry whose outcome is non-null and is the one asked for.
    """
    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    _verb("pm_done_next")("US-TST-1-1", **kwargs)

    assert _on_disk(tmp_project, "US-TST-1-1").status.value == "done"
    entries = _run_log(tmp_project, "US-TST-1-1")
    assert len(entries) == 1, (kwargs, entries)
    assert entries[0].outcome is not None
    assert entries[0].outcome.value == kwargs.get("outcome", "success")


@pytest.mark.parametrize("note", ["", "   \n\t"])
def test_pm_done_next_with_an_empty_string_note_logs_the_sentinel(tmp_project, note):
    """An empty note is an omitted note by any reading of §3."""
    from projectman.server import DONE_NEXT_NO_NOTE

    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    _verb("pm_done_next")("US-TST-1-1", note=note)

    entries = _run_log(tmp_project, "US-TST-1-1")
    assert entries[0].note == DONE_NEXT_NO_NOTE



# ═══ §1–§2 — the "also worth covering" list ═════════════════════


def test_pm_accept_on_an_already_done_task_is_an_expected_negative(tmp_project):
    _seed(tmp_project, n=2)
    store = Store(tmp_project)
    store.claim_task("US-TST-1-1", "claude")
    _verb("pm_accept")("US-TST-1-1", note="first acceptance", next_task=False)
    before = _run_log(tmp_project, "US-TST-1-1")
    assert len(before) == 1

    result = yaml.safe_load(_verb("pm_accept")("US-TST-1-1", note="second try"))

    assert result["outcome"] == "expected_negative"
    assert result["status"] == "already_done"
    assert result["task_id"] == "US-TST-1-1"
    # No second run-log entry, and no next grab taken on the caller's behalf.
    assert len(_run_log(tmp_project, "US-TST-1-1")) == 1
    assert "next" not in result
    assert _on_disk(tmp_project, "US-TST-1-2").assignee is None


def test_pm_accept_on_an_already_done_task_is_not_an_error(tmp_project):
    """An expected negative is a *successful* response — no `is_error`, and no
    body beginning with `error:`."""
    _seed(tmp_project)
    Store(tmp_project).update("US-TST-1-1", status="done")

    is_error, body = _call_over_the_wire(
        "pm_accept", {"task_id": "US-TST-1-1", "note": "already accepted"}
    )

    assert is_error is False, body
    assert not body.lstrip().startswith("error:")
    assert yaml.safe_load(body)["status"] == "already_done"


def test_pm_accept_closes_the_story_and_reports_no_next_task(tmp_project):
    """The expected end of a story: `story_closed` and `no_next_task` together."""
    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(
        _verb("pm_accept")("US-TST-1-1", note="last task in the story")
    )

    assert result["story_closed"] == "US-TST-1"
    assert result["outcome"] == "expected_negative"
    assert result["status"] == "no_next_task"
    assert result["next"] is None
    assert "in this story" in result["next_info"]
    assert _fresh(tmp_project).get_story("US-TST-1")[0].status.value == "done"


def test_pm_accept_grabs_the_next_sibling(tmp_project):
    _seed(tmp_project, n=2)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(_verb("pm_accept")("US-TST-1-1", note="first one done"))

    assert result["completed"] == {
        "id": "US-TST-1-1",
        "status": "done",
        "run_log": "success",
    }
    assert result["next"]["task"]["id"] == "US-TST-1-2"
    assert _on_disk(tmp_project, "US-TST-1-2").assignee == "claude"
    assert _on_disk(tmp_project, "US-TST-1-2").status.value == "in-progress"
    # Still open, so the story is not closed.
    assert "story_closed" not in result


def test_pm_accept_with_next_task_false_omits_the_next_key(tmp_project):
    """`next: null` means "I looked and there was none"; absence means "I did
    not look" — the two must not be confused."""
    _seed(tmp_project, n=2)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(
        _verb("pm_accept")("US-TST-1-1", note="done, taking nothing", next_task=False)
    )

    assert "next" not in result
    assert "next_info" not in result
    assert result["completed"]["status"] == "done"
    assert _on_disk(tmp_project, "US-TST-1-2").assignee is None


def test_pm_accept_defaults_to_same_story_only(tmp_project):
    """Step 19 already requires it, and siblings are always in-sprint."""
    signature = inspect.signature(_verb("pm_accept"))
    assert signature.parameters["same_story_only"].default is True
    assert signature.parameters["next_task"].default is True

    store = _seed(tmp_project)
    store.create_story("Other story", "Another body long enough to matter.")
    store.update("US-TST-2", status="active")
    store.create_task("US-TST-2", "Elsewhere", READY_BODY, points=1)
    store.claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(_verb("pm_accept")("US-TST-1-1", note="story is finished"))

    assert result["status"] == "no_next_task"
    assert _on_disk(tmp_project, "US-TST-2-1").assignee is None


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("wrong_id", ["US-TST-1", "EPIC-TST-1"])
def test_a_story_or_epic_id_is_a_tool_error_not_a_negative(
    tmp_project, verb, wrong_id
):
    """Status *and* assignee are set together here, and assignee is a
    task-only field — so a story or epic id means something else was meant."""
    store = _seed(tmp_project)
    store.create_epic("Epic", "Epic body long enough to matter.")

    with pytest.raises(ToolError) as excinfo:
        _verb(verb)(wrong_id, note="wrong kind of item")

    assert "tasks only" in str(excinfo.value)
    assert _fresh(tmp_project).get_run_log(wrong_id) == []


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_an_unknown_id_is_a_tool_error(tmp_project, verb):
    _seed(tmp_project)

    with pytest.raises(ToolError):
        _verb(verb)("US-TST-9-9", note="nothing to pass a verdict on")


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_the_verb_is_a_successful_response_over_the_wire(tmp_project, task, verb):
    is_error, body = _call_over_the_wire(
        verb, {"task_id": task, "note": "over the wire"}
    )

    assert is_error is False, body
    assert not body.lstrip().startswith("error:")
    payload = yaml.safe_load(body)
    assert payload.get("status") != "error"


# ═══ §2–§3 — pm_done_next is the same call, and always logs ═════


def test_pm_done_next_keeps_its_signature(tmp_project):
    """§2: it is a thin wrapper, it stays forever, and it is not deprecated.

    ``evidence`` was appended by US-PM-9-7 (``docs/reference/evidence-contract.md``
    §3/§7): a *trailing optional* keyword, which is what "keeps its signature"
    permits — every existing call site is untouched.  The published parameters
    before it, and their defaults, are what is actually pinned.
    """
    parameters = inspect.signature(_verb("pm_done_next")).parameters
    assert list(parameters)[:7] == [
        "task_id",
        "outcome",
        "note",
        "assignee",
        "same_story_only",
        "project",
        "id",
    ]
    # `run_id` was appended by US-PM-14-5 on the same terms as `evidence`:
    # trailing, optional, defaulted, so no existing call site moves.  It sits
    # before `evidence`, which the evidence contract requires to stay last.
    assert list(parameters)[7:] == ["run_id", "evidence"]
    assert parameters["run_id"].default is None
    assert parameters["evidence"].default is None
    assert parameters["outcome"].default == "success"
    assert parameters["note"].default is None
    assert parameters["same_story_only"].default is False


def test_pm_done_next_with_no_note_now_logs_the_sentinel(tmp_project):
    """§3, the 13% hole: it used to forward the outcome *only* when a note was
    given, so a completion could land with no run-log entry at all."""
    from projectman.server import DONE_NEXT_NO_NOTE

    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(_verb("pm_done_next")("US-TST-1-1"))

    assert result["completed"]["run_log"] == "success"
    entries = _run_log(tmp_project, "US-TST-1-1")
    assert len(entries) == 1
    assert entries[0].note == DONE_NEXT_NO_NOTE
    assert entries[0].outcome.value == "success"


def test_pm_done_next_still_forwards_an_explicit_outcome(tmp_project):
    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(
        _verb("pm_done_next")("US-TST-1-1", outcome="partial", note="half of it")
    )

    assert result["completed"]["run_log"] == "partial"
    entries = _run_log(tmp_project, "US-TST-1-1")
    assert entries[0].outcome.value == "partial"
    assert entries[0].note == "half of it"


def test_pm_accept_and_pm_done_next_leave_the_same_on_disk_state(tmp_project):
    """§5 / US-PM-8-4: the two spellings are one call."""
    _seed(tmp_project, n=2)
    store = Store(tmp_project)
    store.claim_task("US-TST-1-1", "claude")
    store.claim_task("US-TST-1-2", "claude")

    accepted = yaml.safe_load(
        _verb("pm_accept")("US-TST-1-1", note="same note", next_task=False)
    )
    via_done_next = yaml.safe_load(
        _verb("pm_done_next")("US-TST-1-2", note="same note")
    )

    one = _on_disk(tmp_project, "US-TST-1-1")
    two = _on_disk(tmp_project, "US-TST-1-2")
    assert one.status.value == two.status.value == "done"
    assert one.assignee == two.assignee == "claude"

    first, second = _run_log(tmp_project, "US-TST-1-1"), _run_log(
        tmp_project, "US-TST-1-2"
    )
    assert len(first) == len(second) == 1
    assert first[0].outcome.value == second[0].outcome.value == "success"
    assert first[0].note == second[0].note == "same note"
    assert accepted["completed"]["run_log"] == via_done_next["completed"]["run_log"]


def test_pm_done_next_keeps_its_no_next_task_shape(tmp_project):
    _seed(tmp_project)
    Store(tmp_project).claim_task("US-TST-1-1", "claude")

    result = yaml.safe_load(_verb("pm_done_next")("US-TST-1-1", note="all done"))

    assert result["outcome"] == "expected_negative"
    assert result["status"] == "no_next_task"
    assert result["next"] is None
    assert "in this project" in result["next_info"]


# ═══ The story's measure: no completion without a run-log entry ══


@pytest.mark.parametrize("verb", VERB_NAMES + ["pm_done_next"])
def test_no_verdict_can_reach_disk_without_a_run_log_entry(tmp_project, task, verb):
    """The acceptance criterion as a single sweep.

    Whatever the caller does — note or no note, over the wire or in Python —
    a status write by one of these verbs is accompanied by an entry.  For the
    four verbs the note is required; for `pm_done_next` the sentinel stands in.
    """
    kwargs = {} if verb == "pm_done_next" else {"note": "a verdict was reached"}
    _verb(verb)(task, **kwargs)

    entries = _run_log(tmp_project, task)
    assert len(entries) == 1, (verb, entries)
    assert entries[0].outcome is not None, verb
    assert entries[0].note, verb
