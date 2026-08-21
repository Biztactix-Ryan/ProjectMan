"""Structured evidence on run-log entries (US-PM-9-7).

`docs/reference/evidence-contract.md` is the binding design.  Its governing
rule:

    The note says what happened; the evidence says what proves it.  Prose is
    never the container for a list.

`pm-orchestrate` steps 17-19 already make the orchestrator collect three
structured things — which files changed, which test commands ran and passed,
which DoD criteria are evidenced — and today it flattens them into prose,
which is why note lengths cluster at the cap.  They become a bounded
`evidence` object *alongside* an unchanged, still-required `note`.

So the properties under test here are structural:

* evidence and note are **separate** — the note is byte-identical to what was
  passed and carries no part of the evidence;
* every pre-existing `.jsonl` line still parses, to `evidence is None`, and an
  entry written without evidence has **no `evidence` key on disk** — there is
  no migration and no version marker;
* the caps **clamp, never reject** — an oversized payload still lands the
  status/outcome write, and says so in the response;
* evidence is **queryable**: `pm_run_log(has_evidence=...)` answers "did this
  completion prove anything" in one call, and `pm_get` shows a compact marker
  rather than spending the context budget the contract defends.

Covers contract §8's "US-PM-9-1" and "US-PM-9-2" bullets and the §4 read
paths.  US-PM-9-1/-2 extend these; §5's detection is US-PM-9-3/-8.
"""

import inspect
import json

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.models import (
    EVIDENCE_MAX_DOD,
    EVIDENCE_MAX_FILES,
    EVIDENCE_MAX_STRING,
    EVIDENCE_MAX_TESTS,
    Evidence,
    EvidenceTest,
    RunLogEntry,
)
from projectman.store import NOTE_SUMMARY_RECOMMENDED, Store, clamp_evidence

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: The six tools that can append a run-log entry, per contract §3.
EVIDENCE_TOOLS = [
    "pm_accept",
    "pm_done_next",
    "pm_park",
    "pm_retry",
    "pm_review",
    "pm_update",
]

SAMPLE = {
    "files": ["src/projectman/models.py", "tests/test_run_log_evidence.py"],
    "tests": [
        {
            "command": "uv run pytest tests/test_run_log_evidence.py",
            "passed": True,
            "summary": "12 passed",
        }
    ],
    "dod_met": ["Evidence model with caps", "old entries still parse"],
    "dod_unmet": [],
}


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
def store(tmp_project) -> Store:
    """One story with two ready tasks, the first claimed by `claude`."""
    store = _seed(tmp_project, n=2)
    store.claim_task("US-TST-1-1", "claude")
    return store


def _fresh(tmp_project) -> Store:
    """A Store reading straight from disk, so nothing is answered from cache."""
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _log_path(tmp_project, item_id: str):
    return tmp_project / ".project" / "logs" / f"{item_id}.jsonl"


def _lines_on_disk(tmp_project, item_id: str) -> list[dict]:
    text = _log_path(tmp_project, item_id).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


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


# ═══ §8 / US-PM-9-1 — evidence is separate from the note ════════


def test_one_call_writes_one_entry_carrying_both(store, tmp_project):
    note = "evidence field lands on RunLogEntry; 12 store tests pass"
    store.update(
        "US-TST-1-1", status="done", outcome="success", note=note, evidence=SAMPLE
    )

    entries = _fresh(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.note == note  # byte-identical to what was passed
    assert entry.evidence is not None
    assert entry.evidence.files == SAMPLE["files"]


def test_no_part_of_the_evidence_leaks_into_the_note(store, tmp_project):
    note = "all DoD met"
    store.update("US-TST-1-1", outcome="success", note=note, evidence=SAMPLE)

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.note == note
    for path in SAMPLE["files"]:
        assert path not in entry.note
    assert SAMPLE["tests"][0]["command"] not in entry.note


def test_evidence_round_trips_through_get_run_log(store, tmp_project):
    store.update("US-TST-1-1", outcome="success", note="n", evidence=SAMPLE)

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.evidence.model_dump(exclude_none=True) == {
        "files": SAMPLE["files"],
        "tests": [dict(SAMPLE["tests"][0])],
        "dod_met": SAMPLE["dod_met"],
        "dod_unmet": [],
    }


def test_an_old_format_line_parses_with_evidence_none(store, tmp_project):
    """Hand-written, exactly as every pre-existing line looks on disk."""
    path = _log_path(tmp_project, "US-TST-1-1")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "outcome": "success",
                "status": "done",
                "note": "written before evidence existed",
                "actor": "claude",
            }
        )
        + "\n"
    )

    entries = _fresh(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 1
    assert entries[0].note == "written before evidence existed"
    assert entries[0].evidence is None


def test_an_entry_written_without_evidence_has_no_evidence_key_on_disk(
    store, tmp_project
):
    store.update("US-TST-1-1", outcome="success", note="no evidence here")

    (line,) = _lines_on_disk(tmp_project, "US-TST-1-1")
    assert "evidence" not in line
    assert line["note"] == "no evidence here"


def test_evidence_is_written_to_disk_when_supplied(store, tmp_project):
    store.update("US-TST-1-1", outcome="success", note="n", evidence=SAMPLE)

    (line,) = _lines_on_disk(tmp_project, "US-TST-1-1")
    assert line["evidence"]["files"] == SAMPLE["files"]
    assert line["evidence"]["tests"][0]["passed"] is True


def test_evidence_alone_still_appends_an_entry(store, tmp_project):
    """Contract §3: the append condition widens, so this is `info` + empty note."""
    store.update("US-TST-1-1", evidence=SAMPLE)

    entries = _fresh(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 1
    assert entries[0].outcome.value == "info"
    assert entries[0].note == ""
    assert entries[0].evidence is not None


def test_bare_status_write_still_writes_no_entry(store, tmp_project):
    """Contract §7: the escape hatch stays open — flagged, never blocked."""
    store.update("US-TST-1-1", status="done")

    assert not _log_path(tmp_project, "US-TST-1-1").exists()
    assert _fresh(tmp_project).get_run_log("US-TST-1-1") == []


#: How each of the six run-log-writing tools names its target and its verdict
#: (contract §3).  `next_task=False` keeps `pm_accept` from also claiming the
#: sibling task, which would say nothing about separation.
EVIDENCE_CALL_ARGS = {
    "pm_accept": {"task_id": "US-TST-1-1", "next_task": False},
    "pm_done_next": {"task_id": "US-TST-1-1"},
    "pm_park": {"task_id": "US-TST-1-1"},
    "pm_retry": {"task_id": "US-TST-1-1"},
    "pm_review": {"task_id": "US-TST-1-1"},
    "pm_update": {"id": "US-TST-1-1", "outcome": "success"},
}


def _evidence_strings(evidence: dict) -> list[str]:
    """Every piece of prose the evidence carries — paths, commands, criteria."""
    strings = [*evidence["files"], *evidence["dod_met"], *evidence["dod_unmet"]]
    for test in evidence["tests"]:
        strings.append(test["command"])
        if test.get("summary"):
            strings.append(test["summary"])
    return strings


@pytest.mark.parametrize("tool", EVIDENCE_TOOLS)
def test_note_and_evidence_stay_separate_on_every_tool(tool, store, tmp_project):
    """All six tools, over the wire: one entry, note kept whole, evidence intact.

    The single-tool cases below prove `pm_accept` and `pm_review`; the
    contract makes the parameter uniform across all six, so the separation
    property has to hold on all six.
    """
    note = "one line of prose and nothing else"
    is_error, body = _call_over_the_wire(
        tool, {**EVIDENCE_CALL_ARGS[tool], "note": note, "evidence": SAMPLE}
    )
    assert not is_error, body

    entries = _fresh(tmp_project).get_run_log("US-TST-1-1")
    assert len(entries) == 1, entries
    assert entries[0].note == note  # byte-identical to what was passed
    assert entries[0].evidence is not None
    assert entries[0].evidence.model_dump() == {
        "files": SAMPLE["files"],
        "tests": [dict(SAMPLE["tests"][0])],
        "dod_met": SAMPLE["dod_met"],
        "dod_unmet": [],
    }


@pytest.mark.parametrize("tool", EVIDENCE_TOOLS)
def test_no_evidence_string_is_folded_into_the_note_by_any_tool(
    tool, store, tmp_project
):
    """Not one path, command or DoD item may reach the prose (§: "Verdict")."""
    is_error, body = _call_over_the_wire(
        tool, {**EVIDENCE_CALL_ARGS[tool], "note": "done", "evidence": SAMPLE}
    )
    assert not is_error, body

    stored = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].note
    for text in _evidence_strings(SAMPLE):
        assert text not in stored, (tool, text, stored)


def test_a_legacy_line_is_returned_unchanged_by_pm_run_log(store, tmp_project):
    """§7: an entry without evidence is byte-for-byte the response it was."""
    from projectman.server import pm_run_log

    legacy = {
        "timestamp": "2026-01-01T00:00:00Z",
        "outcome": "success",
        "status": "done",
        "note": "written before evidence existed",
        "actor": "claude",
    }
    path = _log_path(tmp_project, "US-TST-1-1")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(legacy) + "\n")
    _fresh(tmp_project)  # nothing answered from cache

    assert json.loads(pm_run_log("US-TST-1-1")) == [legacy]


# ═══ §8 / US-PM-9-2 — files, tests and DoD ══════════════════════


def test_all_four_lists_round_trip_with_values_intact(store, tmp_project):
    evidence = {
        "files": ["a.py", "b.py"],
        "tests": [
            {"command": "pytest -q", "passed": False, "summary": "3 failed"},
            {"command": "ruff check", "passed": True},
        ],
        "dod_met": ["met one"],
        "dod_unmet": ["unmet one", "unmet two"],
    }
    store.update("US-TST-1-1", outcome="partial", note="n", evidence=evidence)

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert got.files == ["a.py", "b.py"]
    assert got.tests[0].passed is False
    assert got.tests[0].summary == "3 failed"
    assert got.tests[1].passed is True
    assert got.tests[1].summary is None  # a None summary survives exclude_none
    assert got.dod_met == ["met one"]
    assert got.dod_unmet == ["unmet one", "unmet two"]


def test_dod_unmet_survives_a_pm_review(store, tmp_project):
    from projectman.server import pm_review

    pm_review(
        "US-TST-1-1",
        note="endpoint works; error paths untested",
        evidence={"dod_unmet": ["error paths untested"]},
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert got.dod_unmet == ["error paths untested"]


def test_a_hundred_files_stores_forty(store, tmp_project):
    store.update(
        "US-TST-1-1",
        outcome="success",
        note="n",
        evidence={"files": [f"f{i}.py" for i in range(100)]},
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert len(got.files) == EVIDENCE_MAX_FILES == 40
    assert got.files[0] == "f0.py"  # the *first* N are kept


def test_a_five_hundred_char_path_stores_one_sixty(store, tmp_project):
    store.update(
        "US-TST-1-1", outcome="success", note="n", evidence={"files": ["x" * 500]}
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert len(got.files[0]) == EVIDENCE_MAX_STRING == 160


def test_every_cap_clamps_rather_than_rejects(store, tmp_project):
    store.update(
        "US-TST-1-1",
        outcome="success",
        note="n",
        evidence={
            "files": [f"f{i}.py" for i in range(100)],
            "tests": [{"command": f"c{i}", "passed": True} for i in range(30)],
            "dod_met": [f"m{i}" for i in range(50)],
            "dod_unmet": [f"u{i}" for i in range(50)],
        },
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert len(got.files) == EVIDENCE_MAX_FILES
    assert len(got.tests) == EVIDENCE_MAX_TESTS
    assert len(got.dod_met) == EVIDENCE_MAX_DOD
    assert len(got.dod_unmet) == EVIDENCE_MAX_DOD


def test_the_status_write_still_lands_when_evidence_is_clamped(store, tmp_project):
    """The whole reason caps clamp: an oversized payload must not eat the write."""
    store.update(
        "US-TST-1-1",
        status="done",
        outcome="success",
        note="n",
        evidence={"files": [f"f{i}.py" for i in range(100)]},
    )

    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "done"


def test_a_clamp_is_reported_in_the_response(store):
    from projectman.server import pm_update

    body = yaml.safe_load(
        pm_update(
            "US-TST-1-1",
            outcome="success",
            note="n",
            evidence={"files": [f"f{i}.py" for i in range(100)]},
        )
    )
    assert body["evidence_clamped"] is True
    assert body["evidence_dropped"]["files"] == 60


def test_a_clamped_string_is_reported_too(store):
    from projectman.server import pm_update

    body = yaml.safe_load(
        pm_update("US-TST-1-1", outcome="success", note="n", evidence={"files": ["x" * 500]})
    )
    assert body["evidence_clamped"] is True
    assert body["evidence_dropped"]["chars"] == 340


def test_evidence_that_fits_reports_nothing(store):
    """Absence means "stored whole" — the common response keeps its size."""
    from projectman.server import pm_update

    body = yaml.safe_load(
        pm_update("US-TST-1-1", outcome="success", note="n", evidence=SAMPLE)
    )
    assert "evidence_clamped" not in body
    assert "evidence_dropped" not in body


def test_the_clamp_record_does_not_outlive_its_call(store):
    """The Store is cached for the life of the process; the record must not be."""
    from projectman.server import pm_update

    pm_update(
        "US-TST-1-1",
        outcome="success",
        note="n",
        evidence={"files": [f"f{i}.py" for i in range(100)]},
    )
    body = yaml.safe_load(pm_update("US-TST-1-2", outcome="success", note="n"))
    assert "evidence_clamped" not in body


def test_clamp_evidence_passes_a_fitting_payload_through_untouched():
    evidence, clamped, dropped = clamp_evidence(Evidence.model_validate(SAMPLE))
    assert clamped is False
    assert dropped == {}
    assert evidence.files == SAMPLE["files"]


def test_clamp_evidence_leaves_none_alone():
    assert clamp_evidence(None) == (None, False, {})


def test_the_four_lists_are_pinned_on_the_wire(store, tmp_project):
    """The model round-trip is not the contract; the on-disk line is.

    `_append_run_log` writes `exclude_none=True`, so a `None` summary must
    leave *no* key behind rather than a `"summary": null` every entry pays
    for — and `passed: false` must survive as a real boolean.
    """
    store.update(
        "US-TST-1-1",
        outcome="partial",
        note="n",
        evidence={
            "files": ["a.py", "b.py"],
            "tests": [
                {"command": "pytest -q", "passed": False, "summary": "3 failed"},
                {"command": "ruff check", "passed": True},
            ],
            "dod_met": ["met one"],
            "dod_unmet": ["unmet one", "unmet two"],
        },
    )

    (raw,) = _lines_on_disk(tmp_project, "US-TST-1-1")
    assert raw["evidence"] == {
        "files": ["a.py", "b.py"],
        "tests": [
            {"command": "pytest -q", "passed": False, "summary": "3 failed"},
            {"command": "ruff check", "passed": True},
        ],
        "dod_met": ["met one"],
        "dod_unmet": ["unmet one", "unmet two"],
    }
    assert "summary" not in raw["evidence"]["tests"][1]


@pytest.mark.parametrize(
    ("field", "cap", "make"),
    [
        ("files", EVIDENCE_MAX_FILES, lambda i: f"f{i}.py"),
        ("tests", EVIDENCE_MAX_TESTS, lambda i: {"command": f"c{i}", "passed": True}),
        ("dod_met", EVIDENCE_MAX_DOD, lambda i: f"m{i}"),
        ("dod_unmet", EVIDENCE_MAX_DOD, lambda i: f"u{i}"),
    ],
)
def test_one_over_the_cap_keeps_the_first_n_in_order(
    field, cap, make, store, tmp_project
):
    """Each cap on its own boundary: cap + 1 in, cap out, order untouched."""
    from projectman.server import pm_update

    body = yaml.safe_load(
        pm_update(
            "US-TST-1-1",
            status="done",
            outcome="success",
            note="n",
            evidence={field: [make(i) for i in range(cap + 1)]},
        )
    )

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    stored = getattr(entry.evidence, field)
    assert len(stored) == cap
    if field == "tests":
        assert [t.command for t in stored] == [f"c{i}" for i in range(cap)]
    else:
        assert stored == [make(i) for i in range(cap)]
    # The clamp is announced, and it never eats the status/outcome write.
    assert body["evidence_clamped"] is True
    assert body["evidence_dropped"] == {field: 1}
    assert entry.outcome.value == "success"
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "done"


def test_one_char_over_the_string_cap_is_cut_in_every_string_field(store, tmp_project):
    from projectman.server import pm_update

    long = "x" * (EVIDENCE_MAX_STRING + 1)
    body = yaml.safe_load(
        pm_update(
            "US-TST-1-1",
            status="done",
            outcome="success",
            note="n",
            evidence={
                "files": [long],
                "tests": [{"command": long, "passed": True, "summary": long}],
                "dod_met": [long],
                "dod_unmet": [long],
            },
        )
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert len(got.files[0]) == EVIDENCE_MAX_STRING
    assert len(got.tests[0].command) == EVIDENCE_MAX_STRING
    assert len(got.tests[0].summary) == EVIDENCE_MAX_STRING
    assert len(got.dod_met[0]) == EVIDENCE_MAX_STRING
    assert len(got.dod_unmet[0]) == EVIDENCE_MAX_STRING
    assert body["evidence_clamped"] is True
    assert body["evidence_dropped"] == {"chars": 5}  # one char off each of five
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "done"


def test_dod_unmet_survives_a_pm_park(store, tmp_project):
    """The other verdict whose whole job is naming what is outstanding."""
    from projectman.server import pm_park

    pm_park(
        "US-TST-1-1",
        note="needs the staging DB credentials",
        evidence={"dod_unmet": ["integration test cannot run"]},
    )

    got = _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence
    assert got.dod_unmet == ["integration test cannot run"]


def test_the_summary_of_empty_evidence_says_nothing_to_show():
    """§5: present-but-empty is evidence — it must still render a line."""
    assert Evidence().summary() == "0 files, 0/0 tests passed, 0/0 DoD"


def test_the_summary_of_unmet_only_evidence_counts_none_met():
    evidence = Evidence(dod_unmet=["one", "two"])
    assert evidence.summary() == "0 files, 0/0 tests passed, 0/2 DoD"


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param({"tests": [{"command": "x"}]}, id="test-missing-passed"),
        pytest.param({"files": "not-a-list"}, id="files-not-a-list"),
    ],
)
def test_a_malformed_evidence_shape_is_rejected_before_any_write(
    malformed, store, tmp_project
):
    """Caps clamp on *size*; the contract says nothing about *shape*.

    Silently accepting a mis-shaped object would be worse than either — it
    would write evidence that proves something other than what happened.  So
    schema validation rejects it, and rejects it *before* the task moves.
    """
    is_error, text = _call_over_the_wire(
        "pm_accept", {"task_id": "US-TST-1-1", "note": "n", "evidence": malformed}
    )

    assert is_error, text
    assert "validation error" in text
    assert not _log_path(tmp_project, "US-TST-1-1").exists()
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "in-progress"


# ═══ §3 — evidence over the wire ════════════════════════════════


@pytest.mark.parametrize("tool", EVIDENCE_TOOLS)
def test_every_run_log_writing_tool_declares_evidence(tool):
    schema = _schemas()[tool].inputSchema
    assert "evidence" in schema.get("properties", {}), sorted(schema["properties"])
    # Trailing and optional: every existing call site is untouched (§7).
    assert "evidence" not in schema.get("required", [])
    parameters = list(
        inspect.signature(
            getattr(__import__("projectman.server", fromlist=["x"]), tool)
        ).parameters
    )
    assert parameters[-1] == "evidence", parameters


def test_evidence_over_the_wire_on_pm_accept(store, tmp_project):
    is_error, body = _call_over_the_wire(
        "pm_accept",
        {"task_id": "US-TST-1-1", "note": "all DoD met", "evidence": SAMPLE},
    )
    assert not is_error, body

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.note == "all DoD met"
    assert entry.evidence.files == SAMPLE["files"]
    assert entry.evidence.tests[0].command == SAMPLE["tests"][0]["command"]
    assert entry.evidence.dod_met == SAMPLE["dod_met"]


def test_evidence_over_the_wire_on_pm_review(store, tmp_project):
    is_error, body = _call_over_the_wire(
        "pm_review",
        {
            "task_id": "US-TST-1-1",
            "note": "half landed",
            "evidence": {
                "tests": [{"command": "pytest -q", "passed": False, "summary": "3 failed"}],
                "dod_unmet": ["error paths untested"],
            },
        },
    )
    assert not is_error, body

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.evidence.tests[0].passed is False
    assert entry.evidence.dod_unmet == ["error paths untested"]
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "review"


def test_a_call_without_evidence_over_the_wire_is_unchanged(store, tmp_project):
    is_error, _ = _call_over_the_wire(
        "pm_accept", {"task_id": "US-TST-1-1", "note": "all DoD met"}
    )
    assert not is_error
    assert _fresh(tmp_project).get_run_log("US-TST-1-1")[0].evidence is None


# ═══ §3 — the advisory note-length signal ═══════════════════════


def test_a_long_note_alongside_evidence_is_flagged(store):
    from projectman.server import pm_review

    long_note = "x" * (NOTE_SUMMARY_RECOMMENDED + 1)
    body = yaml.safe_load(pm_review("US-TST-1-1", note=long_note, evidence=SAMPLE))
    assert body["note_long"] is True
    assert body["note_length"] == NOTE_SUMMARY_RECOMMENDED + 1
    assert body["note_recommended"] == NOTE_SUMMARY_RECOMMENDED == 200


def test_the_flag_is_advisory_and_the_note_is_stored_whole(store, tmp_project):
    from projectman.server import pm_review

    long_note = "y" * (NOTE_SUMMARY_RECOMMENDED + 50)
    pm_review("US-TST-1-1", note=long_note, evidence=SAMPLE)

    entry = _fresh(tmp_project).get_run_log("US-TST-1-1")[0]
    assert entry.note == long_note  # no extra truncation
    assert _fresh(tmp_project).get_task("US-TST-1-1")[0].status.value == "review"


def test_a_long_note_without_evidence_is_not_flagged(store):
    """The signal is about prose that should have been a list, not length alone."""
    from projectman.server import pm_review

    body = yaml.safe_load(
        pm_review("US-TST-1-1", note="z" * (NOTE_SUMMARY_RECOMMENDED + 1))
    )
    assert "note_long" not in body


def test_a_short_note_with_evidence_is_not_flagged(store):
    from projectman.server import pm_review

    body = yaml.safe_load(pm_review("US-TST-1-1", note="one line", evidence=SAMPLE))
    assert "note_long" not in body


# ═══ §4 — how evidence gets out ═════════════════════════════════


def test_pm_run_log_returns_evidence_verbatim(store):
    from projectman.server import pm_run_log

    store.update("US-TST-1-1", outcome="success", note="n", evidence=SAMPLE)

    (entry,) = json.loads(pm_run_log("US-TST-1-1"))
    assert entry["evidence"]["files"] == SAMPLE["files"]
    assert entry["evidence"]["tests"] == [dict(SAMPLE["tests"][0])]
    assert entry["evidence"]["dod_met"] == SAMPLE["dod_met"]


def test_pm_run_log_omits_the_key_entirely_when_there_is_no_evidence(store):
    from projectman.server import pm_run_log

    store.update("US-TST-1-1", outcome="success", note="n")

    (entry,) = json.loads(pm_run_log("US-TST-1-1"))
    assert "evidence" not in entry
    # Every pre-existing key keeps its place (§7).
    assert {"timestamp", "outcome", "status", "note", "actor"} <= set(entry)


def test_pm_run_log_declares_the_has_evidence_filter():
    schema = _schemas()["pm_run_log"].inputSchema
    assert "has_evidence" in schema.get("properties", {})
    assert "has_evidence" not in schema.get("required", [])


def test_the_has_evidence_filter_selects_entries(store):
    from projectman.server import pm_run_log

    store.update("US-TST-1-1", outcome="info", note="bare one")
    store.update("US-TST-1-1", outcome="success", note="proved it", evidence=SAMPLE)

    with_evidence = json.loads(pm_run_log("US-TST-1-1", has_evidence=True))
    without = json.loads(pm_run_log("US-TST-1-1", has_evidence=False))
    everything = json.loads(pm_run_log("US-TST-1-1"))

    assert [e["note"] for e in with_evidence] == ["proved it"]
    assert [e["note"] for e in without] == ["bare one"]
    assert len(everything) == 2


def test_has_evidence_false_on_a_task_with_no_log_is_an_empty_list(store, tmp_project):
    """The no-log completion is detectable by query too, not just by audit.

    Contract §5 counts a done task with no run log at all as a completion
    without evidence — the measured 13%.  Asking the query about it must
    answer "nothing proved anything", not raise: an error here would make the
    per-item check impossible for exactly the worst case.
    """
    from projectman.server import pm_run_log

    assert not _log_path(tmp_project, "US-TST-1-2").exists()
    store.update("US-TST-1-2", status="done")  # a bare status write logs nothing
    assert not _log_path(tmp_project, "US-TST-1-2").exists()

    assert json.loads(pm_run_log("US-TST-1-2", has_evidence=False)) == []
    assert json.loads(pm_run_log("US-TST-1-2", has_evidence=True)) == []
    assert json.loads(pm_run_log("US-TST-1-2")) == []

    is_error, body = _call_over_the_wire(
        "pm_run_log", {"id": "US-TST-1-2", "has_evidence": False}
    )
    assert not is_error, body
    assert json.loads(body) == []


def test_present_but_empty_evidence_counts_as_evidence(store):
    """Contract §5: presence, never truthiness — `Evidence()` says "nothing to show"."""
    from projectman.server import pm_run_log

    store.update("US-TST-1-1", outcome="success", note="a docs task", evidence={})

    with_evidence = json.loads(pm_run_log("US-TST-1-1", has_evidence=True))
    assert [e["note"] for e in with_evidence] == ["a docs task"]
    assert json.loads(pm_run_log("US-TST-1-1", has_evidence=False)) == []


def test_the_filter_runs_before_the_limit(store):
    from projectman.server import pm_run_log

    for i in range(5):
        store.update("US-TST-1-1", outcome="info", note=f"bare {i}")
    store.update("US-TST-1-1", outcome="success", note="proved it", evidence=SAMPLE)

    entries = json.loads(pm_run_log("US-TST-1-1", limit=2, has_evidence=True))
    assert [e["note"] for e in entries] == ["proved it"]


def test_pm_get_shows_a_marker_not_the_object(store):
    from projectman.server import pm_get

    store.update("US-TST-1-1", outcome="success", note="n", evidence=SAMPLE)

    body = yaml.safe_load(pm_get("US-TST-1-1", include_log=True))
    (entry,) = body["recent_run_log"]
    assert entry["has_evidence"] is True
    assert entry["evidence_summary"] == "2 files, 1/1 tests passed, 2/2 DoD"
    assert "evidence" not in entry


def test_pm_get_marks_an_entry_without_evidence(store):
    from projectman.server import pm_get

    store.update("US-TST-1-1", outcome="success", note="n")

    body = yaml.safe_load(pm_get("US-TST-1-1", include_log=True))
    (entry,) = body["recent_run_log"]
    assert entry["has_evidence"] is False
    assert "evidence_summary" not in entry
    assert entry["note"] == "n"


def test_the_evidence_summary_counts_failures_and_unmet_criteria():
    evidence = Evidence(
        files=["a.py", "b.py", "c.py"],
        tests=[
            EvidenceTest(command="pytest", passed=True),
            EvidenceTest(command="ruff", passed=False),
        ],
        dod_met=["one"],
        dod_unmet=["two", "three"],
    )
    assert evidence.summary() == "3 files, 1/2 tests passed, 1/3 DoD"


def test_pm_activity_is_untouched_by_evidence(store, tmp_project):
    """§4: evidence is run-log payload, not frontmatter."""
    store.update("US-TST-1-1", status="done", outcome="success", note="n", evidence=SAMPLE)

    activity = (tmp_project / ".project" / "activity.jsonl").read_text()
    assert "evidence" not in activity
    assert SAMPLE["files"][0] not in activity


# ═══ §7 — backwards compatibility ═══════════════════════════════


def test_the_model_still_parses_a_line_with_neither_status_nor_evidence():
    entry = RunLogEntry.model_validate_json(
        json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "outcome": "info",
                "note": "ancient",
                "actor": "human",
            }
        )
    )
    assert entry.status is None
    assert entry.evidence is None


def test_mixed_old_and_new_lines_read_back_together(store, tmp_project):
    path = _log_path(tmp_project, "US-TST-1-1")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "outcome": "success",
                "note": "old",
                "actor": "claude",
            }
        )
        + "\n"
    )
    store.update("US-TST-1-1", outcome="success", note="new", evidence=SAMPLE)

    entries = _fresh(tmp_project).get_run_log("US-TST-1-1")
    assert [e.note for e in entries] == ["new", "old"]  # most recent first
    assert entries[0].evidence is not None
    assert entries[1].evidence is None
