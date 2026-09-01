"""pm_audit accepts ``since`` and short-circuits when nothing changed (US-PM-11-6).

pm-orchestrate polls pm_audit as a health check every three accepted tasks and
stops the run on a new ERROR-level finding.  One measured session had 92 of 139
calls returning byte-identical reports.  Caching the tool would disable the
check; instead US-PM-11-5 gave every report a content digest of the audit's
inputs, and this task lets the caller hand it back.

The safety argument, asserted below rather than asserted in prose: the digest
hashes the *content* of everything the audit reads, so any state change that
could produce a new finding changes the digest.  A matching digest therefore
means byte-identical inputs, which means identical findings — a new ERROR
cannot hide behind a short-circuit (``§ the check is not weakened``).

Also asserted: the short answer really is short (< 200 bytes over a real
``tools/call``), it does not re-run the checks, it does not rewrite DRIFT.md,
and a stale/garbage/absent ``since`` quietly runs the full audit instead of
erroring.
"""

import re

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.audit import (
    DIGEST_LINE_PREFIX,
    UNCHANGED_LINE,
    compute_state_digest,
    run_audit,
)
from projectman.store import Store, clear_all_caches

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def store(tmp_project) -> Store:
    """One active story with two tasks — enough state to move."""
    store = Store(tmp_project)
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in (1, 2):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    return store


def _digest_of(report: str) -> str:
    lines = [l for l in report.splitlines() if l.startswith(DIGEST_LINE_PREFIX)]
    assert len(lines) == 1, report
    return lines[0][len(DIGEST_LINE_PREFIX) :]


def _audit(tmp_project, **kwargs) -> str:
    clear_all_caches()
    return run_audit(tmp_project, **kwargs)


def _drift_path(tmp_project):
    return tmp_project / ".project" / "DRIFT.md"


def _drift_state(tmp_project):
    """Bytes and mtime — a rewrite of identical bytes still moves mtime_ns."""
    path = _drift_path(tmp_project)
    if not path.exists():
        return None
    return path.read_bytes(), path.stat().st_mtime_ns


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


def _audit_over_the_wire(arguments: dict | None = None) -> tuple[bool, str]:
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()
    return _call_over_the_wire("pm_audit", arguments or {})


def _make_error_finding(store: Store):
    """Flip the story to done with its tasks still open — Check 1, severity error."""
    store.update("US-TST-1", status="done")


# ═══ § unchanged — the short answer ═════════════════════════════


def test_a_matching_since_returns_the_short_answer(store, tmp_project):
    first = _audit(tmp_project)
    digest = _digest_of(first)

    answer = _audit(tmp_project, since=digest)

    assert _digest_of(answer) == digest
    assert UNCHANGED_LINE in answer.splitlines()
    assert len(answer) < len(first)


def test_the_short_answer_is_under_100_bytes(store, tmp_project):
    digest = _digest_of(_audit(tmp_project))
    answer = _audit(tmp_project, since=digest)
    assert len(answer.encode()) < 100, (len(answer.encode()), answer)


def test_the_short_answer_carries_the_last_reports_counts(store, tmp_project):
    """The counts are read off DRIFT.md, and only when its digest matches."""
    full = _audit(tmp_project)
    errors = int(re.search(r"\*\*Errors:\*\* (\d+)", full).group(1))
    warnings = int(re.search(r"\*\*Warnings:\*\* (\d+)", full).group(1))

    answer = _audit(tmp_project, since=_digest_of(full))

    assert f"errors: {errors} | warnings: {warnings}" in answer.splitlines()


def test_the_counts_are_omitted_rather_than_guessed_when_drift_is_gone(
    store, tmp_project
):
    """No DRIFT.md to vouch for them — the answer says less, never something
    it cannot prove, and still never re-runs the checks."""
    digest = _digest_of(_audit(tmp_project))
    _drift_path(tmp_project).unlink()

    answer = _audit(tmp_project, since=digest)

    assert UNCHANGED_LINE in answer.splitlines()
    assert "errors:" not in answer
    assert not _drift_path(tmp_project).exists()


def test_a_stale_drift_md_does_not_lend_its_counts(store, tmp_project):
    """DRIFT.md from another state carries another state's counts."""
    digest = _digest_of(_audit(tmp_project))
    _drift_path(tmp_project).write_text(
        "# Project Audit Report\n\ndigest: ffffffffffffffff\n\n"
        "**Errors:** 9 | **Warnings:** 9 | **Info:** 9\n"
    )
    # DRIFT.md is excluded from the hash, so the digest still matches.
    assert compute_state_digest(tmp_project) == digest

    answer = _audit(tmp_project, since=digest)

    assert UNCHANGED_LINE in answer.splitlines()
    assert "9" not in answer.replace(digest, "")


def test_the_short_answer_does_not_rewrite_drift_md(store, tmp_project):
    digest = _digest_of(_audit(tmp_project))
    before = _drift_state(tmp_project)
    assert before is not None

    _audit(tmp_project, since=digest)

    assert _drift_state(tmp_project) == before


def test_the_short_answer_does_not_run_the_checks(store, tmp_project, monkeypatch):
    """A check that explodes proves it was never reached."""
    import projectman.audit as audit_module

    digest = _digest_of(_audit(tmp_project))

    def boom(_store):
        raise AssertionError("checks were run for an unchanged project")

    monkeypatch.setattr(audit_module, "check_completions_without_evidence", boom)

    answer = _audit(tmp_project, since=digest)
    assert UNCHANGED_LINE in answer.splitlines()

    # The same monkeypatched check *is* reached on the full path — so the test
    # above is evidence of a short-circuit, not of a check that stopped firing.
    with pytest.raises(AssertionError, match="checks were run"):
        _audit(tmp_project, since="nope")


def test_repeated_unchanged_polls_stay_byte_identical(store, tmp_project):
    digest = _digest_of(_audit(tmp_project))
    assert _audit(tmp_project, since=digest) == _audit(tmp_project, since=digest)


def test_the_short_answer_survives_whitespace_and_case(store, tmp_project):
    """An orchestrator that pasted the digest with a stray newline still hits."""
    digest = _digest_of(_audit(tmp_project))
    for variant in (f"  {digest} ", digest.upper(), f"{digest}\n"):
        assert UNCHANGED_LINE in _audit(tmp_project, since=variant)


# ═══ § the check is not weakened ════════════════════════════════


def test_a_new_error_finding_moves_the_digest_and_is_reported(store, tmp_project):
    """The health check's whole job: a new ERROR reaches the caller promptly."""
    before = _audit(tmp_project)
    assert "[ERROR]" not in before

    _make_error_finding(store)

    after = _audit(tmp_project, since=_digest_of(before))
    assert UNCHANGED_LINE not in after
    assert "[ERROR]" in after
    assert "done but has 2 incomplete task(s)" in after
    assert _digest_of(after) != _digest_of(before)


def test_the_poll_after_a_new_error_answers_short_once_acknowledged(
    store, tmp_project
):
    """The error is not silenced by the *next* poll's digest — it is still in
    DRIFT.md and its counts ride along in the short answer."""
    _make_error_finding(store)
    full = _audit(tmp_project)
    assert "[ERROR]" in full

    answer = _audit(tmp_project, since=_digest_of(full))
    assert "errors: 1 | warnings:" in answer


def test_every_state_change_that_creates_a_finding_breaks_the_match(
    store, tmp_project
):
    """One mutation per finding class the health check cares about; none of
    them may still match the pre-change digest."""
    mutations = [
        ("story done with open tasks", lambda s: s.update("US-TST-1", status="done")),
        ("new undecomposed story", lambda s: s.create_story("Second", "x" * 40)),
        ("task blocked", lambda s: s.update("US-TST-1-1", status="blocked")),
        ("new task", lambda s: s.create_task("US-TST-1", "Task 3", READY_BODY)),
        (
            "thin task body",
            lambda s: s.update("US-TST-1-2", body="short"),
        ),
        ("story archived", lambda s: s.archive("US-TST-1")),
    ]
    for label, mutate in mutations:
        digest = _digest_of(_audit(tmp_project))
        mutate(Store(tmp_project))
        clear_all_caches()
        assert compute_state_digest(tmp_project) != digest, label
        assert UNCHANGED_LINE not in _audit(tmp_project, since=digest), label


# ═══ § a since it cannot use is never an error ══════════════════


@pytest.mark.parametrize(
    "since",
    [
        "",
        "   ",
        "NOPE-1",
        "not-a-digest",
        "0" * 16,
        "deadbeef",
        "deadbeefdeadbeefdeadbeefdeadbeef",
        "digest: deadbeefdeadbeef",
        "☃",
        "../../etc/passwd",
    ],
    ids=lambda v: repr(v),
)
def test_a_garbage_since_runs_the_full_audit(store, tmp_project, since):
    report = _audit(tmp_project, since=since)
    assert report.startswith("# Project Audit Report")
    assert UNCHANGED_LINE not in report
    assert "**Errors:**" in report


def test_a_stale_since_runs_the_full_audit(store, tmp_project):
    stale = _digest_of(_audit(tmp_project))
    _make_error_finding(store)
    clear_all_caches()

    report = _audit(tmp_project, since=stale)

    assert UNCHANGED_LINE not in report
    assert "[ERROR]" in report


def test_no_since_at_all_runs_the_full_audit_and_rewrites_drift(store, tmp_project):
    _audit(tmp_project)
    before = _drift_state(tmp_project)

    report = _audit(tmp_project)

    assert report.startswith("# Project Audit Report")
    assert _drift_state(tmp_project)[1] != before[1]


def test_a_full_audit_after_a_short_circuit_still_writes_drift(store, tmp_project):
    digest = _digest_of(_audit(tmp_project))
    _drift_path(tmp_project).unlink()

    _audit(tmp_project, since=digest)
    assert not _drift_path(tmp_project).exists()

    _audit(tmp_project, since="stale")
    assert _drift_path(tmp_project).exists()


# ═══ § over the wire ════════════════════════════════════════════


def test_the_tool_accepts_since_and_answers_short(store, tmp_project):
    is_error, first = _audit_over_the_wire()
    assert not is_error, first
    digest = _digest_of(first)

    is_error, answer = _audit_over_the_wire({"since": digest})

    assert not is_error, answer
    assert _digest_of(answer) == digest
    assert UNCHANGED_LINE in answer.splitlines()


def test_the_wire_response_for_an_unchanged_project_is_under_200_bytes(
    store, tmp_project
):
    """The measurement the task is for: 162-10,440 chars becomes this."""
    _, first = _audit_over_the_wire()
    _, answer = _audit_over_the_wire({"since": _digest_of(first)})

    measured = len(answer.encode())
    assert measured < 200, (measured, answer)
    assert measured < len(first.encode())


def test_the_wire_reports_a_new_error_when_the_digest_moved(store, tmp_project):
    _, first = _audit_over_the_wire()
    _make_error_finding(store)

    is_error, after = _audit_over_the_wire({"since": _digest_of(first)})

    assert not is_error, after
    assert "[ERROR]" in after


def test_a_garbage_since_over_the_wire_is_not_an_error(store, tmp_project):
    is_error, report = _audit_over_the_wire({"since": "NOPE-1"})
    assert not is_error, report
    assert not report.lstrip().startswith("error:")
    assert report.startswith("# Project Audit Report")


def test_since_composes_with_include_info(store, tmp_project):
    """include_info changes what a full report shows, never the short answer."""
    _, full = _audit_over_the_wire({"include_info": True})
    digest = _digest_of(full)

    _, answer = _audit_over_the_wire({"since": digest, "include_info": True})
    assert UNCHANGED_LINE in answer.splitlines()
    assert len(answer.encode()) < 200


def test_the_tool_schema_declares_since_as_an_optional_string(store, tmp_project):
    from projectman.server import mcp as mcp_server

    tools = {t.name: t for t in anyio.run(mcp_server.list_tools)}
    schema = tools["pm_audit"].inputSchema

    assert "since" in schema["properties"], schema["properties"].keys()
    assert "since" not in schema.get("required", [])


# ═══ § the hub path ═════════════════════════════════════════════


@pytest.fixture
def tmp_hub(tmp_path_factory):
    """A minimal hub on its own root.

    Not the shared ``tmp_hub`` fixture: the autouse ``chdir_to_project`` above
    already claims ``tmp_path`` for a non-hub project, and both fixtures create
    ``<root>/.project``.
    """
    root = tmp_path_factory.mktemp("hub")
    proj = root / ".project"
    (proj / "projects").mkdir(parents=True)
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "config.yaml").write_text(
        yaml.dump(
            {
                "name": "test-hub",
                "prefix": "HUB",
                "description": "A test hub",
                "hub": True,
                "next_story_id": 1,
                "projects": [],
            }
        )
    )
    return root


@pytest.fixture
def hub_subproject(tmp_hub, monkeypatch):
    """One registered subproject, with the hub root as the cwd the tool sees."""
    pm_dir = tmp_hub / ".project" / "projects" / "alpha"
    (pm_dir / "stories").mkdir(parents=True)
    (pm_dir / "tasks").mkdir()
    (pm_dir / "config.yaml").write_text(
        yaml.dump(
            {
                "name": "alpha",
                "prefix": "ALP",
                "description": "A subproject",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            }
        )
    )
    monkeypatch.chdir(tmp_hub)
    return pm_dir


def _subproject_drift(pm_dir):
    path = pm_dir / "DRIFT.md"
    if not path.exists():
        return None
    return path.read_bytes(), path.stat().st_mtime_ns


def test_the_hub_path_threads_since_and_answers_short(tmp_hub, hub_subproject):
    """``project=`` and ``since=`` compose: US-PM-11-6 threads both branches."""
    is_error, first = _audit_over_the_wire({"project": "alpha"})
    assert not is_error, first
    digest = _digest_of(first)

    is_error, answer = _audit_over_the_wire({"project": "alpha", "since": digest})

    assert not is_error, answer
    assert UNCHANGED_LINE in answer.splitlines()
    assert _digest_of(answer) == digest
    assert len(answer.encode()) < 200
    assert len(answer.encode()) < len(first.encode())


def test_the_hub_short_answer_leaves_the_subprojects_drift_alone(
    tmp_hub, hub_subproject
):
    _, first = _audit_over_the_wire({"project": "alpha"})
    before = _subproject_drift(hub_subproject)
    assert before is not None, "the full hub audit should have written DRIFT.md"

    _audit_over_the_wire({"project": "alpha", "since": _digest_of(first)})

    assert _subproject_drift(hub_subproject) == before


def test_a_change_inside_the_subproject_breaks_the_hub_match(
    tmp_hub, hub_subproject
):
    """The short answer must not be able to hide a subproject's own drift."""
    _, first = _audit_over_the_wire({"project": "alpha"})
    digest = _digest_of(first)

    store = Store(tmp_hub, project_dir=hub_subproject)
    store.create_story("Story", "Story body text long enough to matter.")

    is_error, after = _audit_over_the_wire({"project": "alpha", "since": digest})

    assert not is_error, after
    assert UNCHANGED_LINE not in after.splitlines()
    assert after.startswith("# Project Audit Report")
    assert _digest_of(after) != digest


def test_a_stale_since_on_the_hub_path_runs_the_full_audit(tmp_hub, hub_subproject):
    is_error, report = _audit_over_the_wire({"project": "alpha", "since": "NOPE-1"})

    assert not is_error, report
    assert report.startswith("# Project Audit Report")
    assert UNCHANGED_LINE not in report.splitlines()
