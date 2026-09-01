"""A new ERROR is never more than one poll away (US-PM-11-3).

US-PM-11-5 gave every audit report a content digest of the audit's inputs and
US-PM-11-6 lets a caller hand it back as ``since``, answering an unchanged
project in ~65 bytes.  pm-orchestrate polls pm_audit every three accepted
tasks and halts the run on a new ERROR-level finding, so the short-circuit is
only safe if it can never swallow one.

This file verifies the acceptance criterion "the health check still detects
new ERROR-level findings promptly" for *every* ERROR-level check the audit
implements, not just the one class the US-PM-11-6 tests happened to use.  For
each check the sequence is the orchestrator's own:

    poll -> ``unchanged`` -> introduce the condition -> poll with the *old*
    digest -> the full audit runs and reports the ERROR

so detection latency is exactly one poll, never more.  The converse is
asserted alongside it: acknowledging the new digest answers short again, and
repairing the condition moves the digest a third time.

``test_the_parametrisation_covers_every_error_level_check`` reads the severity
of every finding straight out of ``audit.py`` and fails if a Check 19 ever
adds an ERROR class this file does not exercise.
"""

import re
from pathlib import Path

import anyio
import mcp.types as types
import pytest

from projectman import audit as audit_module
from projectman.audit import DIGEST_LINE_PREFIX, UNCHANGED_LINE
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
def project(tmp_project) -> Path:
    """A clean project rich enough for every ERROR class to become reachable.

    Two active stories (the second already depending on the first, so one more
    edge closes a cycle), tasks under each, and an active epic owning the
    first story.  Deliberately ERROR-free — every test below asserts that.
    """
    store = Store(tmp_project)
    store.create_story("First story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in (1, 2):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)

    store.create_story("Second story", "Another body long enough to matter.")
    store.update("US-TST-2", status="active", depends_on=["US-TST-1"])
    store.create_task("US-TST-2", "Task A", READY_BODY, points=1)

    epic = store.create_epic("Epic", "An epic with a body long enough to matter.")
    store.update(epic.id, status="active")
    store.update("US-TST-1", epic_id=epic.id)
    return tmp_project


# ── the wire ─────────────────────────────────────────────────────


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


def _poll(since: str | None = None) -> str:
    """One health-check poll, exactly as pm-orchestrate makes it."""
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()
    arguments = {} if since is None else {"since": since}
    is_error, text = _call_over_the_wire("pm_audit", arguments)
    assert not is_error, text
    return text


def _digest_of(report: str) -> str:
    lines = [l for l in report.splitlines() if l.startswith(DIGEST_LINE_PREFIX)]
    assert len(lines) == 1, report
    return lines[0][len(DIGEST_LINE_PREFIX) :]


# ── one mutation per ERROR-level check ───────────────────────────
#
# Each entry: (check name in audit.py, introduce, repair, message fragment).
# ``introduce`` and ``repair`` take a fresh Store and the project root, and
# every one of them writes only inside the PM directory — which is the whole
# reason the digest can see it.


def _restore_security_md(root: Path) -> None:
    (root / ".project" / "SECURITY.md").write_text(
        "# test-project — Security\n\n## Authentication\n\nNone — CLI tool.\n\n"
        "## Authorization\n\nN/A.\n\n## Known Risks\n\nNone identified.\n"
    )


ERROR_CASES = [
    pytest.param(
        "done-story-incomplete-tasks",
        lambda s, root: s.update("US-TST-1", status="done"),
        lambda s, root: s.update("US-TST-1", status="active"),
        "is done but has 2 incomplete task(s)",
        id="done-story-incomplete-tasks",
    ),
    pytest.param(
        "done-epic-open-stories",
        lambda s, root: s.update("EPIC-TST-1", status="done"),
        lambda s, root: s.update("EPIC-TST-1", status="active"),
        "is done but has 1 open story/stories",
        id="done-epic-open-stories",
    ),
    pytest.param(
        "dependency-cycle",
        lambda s, root: s.update("US-TST-1", depends_on=["US-TST-2"]),
        lambda s, root: s.update("US-TST-1", clear="depends_on"),
        "Dependency cycle detected:",
        id="dependency-cycle",
    ),
    pytest.param(
        "missing-documentation",
        lambda s, root: (root / ".project" / "SECURITY.md").unlink(),
        lambda s, root: _restore_security_md(root),
        "SECURITY.md is missing from .project/",
        id="missing-documentation",
    ),
]


# ═══ § detection latency is one poll ════════════════════════════


@pytest.mark.parametrize("check,introduce,repair,fragment", ERROR_CASES)
def test_a_new_error_is_reported_by_the_very_next_poll(
    project, check, introduce, repair, fragment
):
    """The criterion, end to end, over real ``tools/call`` traffic.

    An orchestrator that has just been told ``unchanged`` holds a digest from
    *before* the condition existed.  Its next poll must therefore run the full
    audit and surface the ERROR — one poll of latency, never two.
    """
    baseline = _poll()
    assert "[ERROR]" not in baseline, baseline
    digest_before = _digest_of(baseline)

    # The poll that answers short: this is the state the orchestrator is in
    # when the condition appears.
    quiet = _poll(digest_before)
    assert UNCHANGED_LINE in quiet.splitlines(), quiet
    assert "[ERROR]" not in quiet

    introduce(Store(project), project)

    detected = _poll(digest_before)

    assert UNCHANGED_LINE not in detected, detected
    assert "[ERROR]" in detected, detected
    assert fragment in detected, detected
    digest_after = _digest_of(detected)
    assert digest_after != digest_before


@pytest.mark.parametrize("check,introduce,repair,fragment", ERROR_CASES)
def test_the_error_state_answers_short_once_its_digest_is_acknowledged(
    project, check, introduce, repair, fragment
):
    """The converse: a *known* error does not force a full report forever.

    The short answer still carries the error count, so an orchestrator that
    has already halted on this finding keeps seeing it without paying for the
    report again.
    """
    introduce(Store(project), project)
    full = _poll()
    assert "[ERROR]" in full, full

    answer = _poll(_digest_of(full))

    assert UNCHANGED_LINE in answer.splitlines(), answer
    assert re.search(r"errors: [1-9]\d* \| warnings:", answer), answer
    assert len(answer.encode()) < 200, answer


@pytest.mark.parametrize("check,introduce,repair,fragment", ERROR_CASES)
def test_repairing_the_condition_moves_the_digest_again(
    project, check, introduce, repair, fragment
):
    """Fixing the state is a state change too — the next poll sees it clear."""
    introduce(Store(project), project)
    errored = _poll()
    assert "[ERROR]" in errored
    digest_errored = _digest_of(errored)

    repair(Store(project), project)

    cleared = _poll(digest_errored)

    assert UNCHANGED_LINE not in cleared, cleared
    assert "[ERROR]" not in cleared, cleared
    assert fragment not in cleared, cleared
    assert _digest_of(cleared) != digest_errored


# ═══ § the enumeration cannot go stale ══════════════════════════


_FINDING_RE = re.compile(r'"severity":\s*"(\w+)",\s*"check":\s*"([a-z-]+)"')


def _error_checks_in_source() -> set[str]:
    source = Path(audit_module.__file__).read_text()
    findings = _FINDING_RE.findall(source)
    # Sanity: the regex must see every finding, not a subset — otherwise a
    # missed ERROR class would look like coverage.
    assert len(findings) == source.count('"check": "'), findings
    return {check for severity, check in findings if severity == "error"}


def test_the_parametrisation_covers_every_error_level_check():
    """Add a Check 19 at error level and this fails until it is exercised."""
    covered = {case.values[0] for case in ERROR_CASES}
    assert _error_checks_in_source() == covered


def test_every_error_condition_is_visible_to_the_digest_alone(project):
    """Why the short-circuit is safe for all four: the digest hashes the PM
    directory, and every ERROR check's inputs live there.

    Introducing *and* repairing each condition moves the digest, with no
    audit run in between — so the comparison ``since == digest`` is enough on
    its own to rule a new ERROR out.  A check whose condition lived outside
    ``.project/`` would fail here rather than fail silently in production.
    """
    for case in ERROR_CASES:
        check, introduce, repair, _fragment = case.values

        clean = audit_module.compute_state_digest(project)
        introduce(Store(project), project)
        clear_all_caches()
        errored = audit_module.compute_state_digest(project)
        assert errored != clean, check

        repair(Store(project), project)
        clear_all_caches()
        assert audit_module.compute_state_digest(project) != errored, check
