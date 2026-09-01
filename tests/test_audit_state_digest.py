"""pm_audit returns a state digest (US-PM-11-5).

pm-orchestrate calls pm_audit in pre-flight and again as a health check every
three accepted tasks; one measured session had 92 of 139 calls returning
byte-identical reports.  Caching the tool would disable the health check, so
instead every report now carries a fingerprint of the audit's *inputs*.
US-PM-11-6 compares a caller's ``since`` against it and short-circuits.

The properties asserted here are the ones the next task depends on:

* **stable** — two calls with no writes between them agree, and the audit's own
  DRIFT.md write does not perturb the answer it just reported;
* **complete** — it moves for anything a finding could be derived from: an item
  create, a status update, config, project docs, sprints;
* **short and fixed-width** — 16 lowercase hex characters, cheap to pass back;
* **reachable** — it survives a real ``tools/call``, in both the default and
  the ``include_info`` response, in a fixed, easily-parsed position.
"""

import re

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.audit import DIGEST_LENGTH, compute_state_digest, run_audit
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
    """The digest as a caller would parse it: the ``digest:`` line."""
    lines = [l for l in report.splitlines() if l.startswith("digest: ")]
    assert len(lines) == 1, report
    # Fixed position: first non-empty line after the title.
    body = [l for l in report.splitlines() if l.strip()]
    assert body[1] == lines[0], report
    return lines[0][len("digest: ") :]


def _audit_digest(tmp_project, **kwargs) -> str:
    clear_all_caches()
    return _digest_of(run_audit(tmp_project, **kwargs))


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


# ═══ shape ══════════════════════════════════════════════════════


def test_the_digest_is_a_short_fixed_width_hex_string(store, tmp_project):
    digest = _audit_digest(tmp_project)
    assert len(digest) == DIGEST_LENGTH == 16
    assert re.fullmatch(r"[0-9a-f]{16}", digest), digest


def test_an_empty_project_still_has_a_digest(tmp_project):
    """No stories, no tasks — the fingerprint is still well formed."""
    assert re.fullmatch(r"[0-9a-f]{16}", _audit_digest(tmp_project))


# ═══ stability ══════════════════════════════════════════════════


def test_two_calls_with_no_writes_return_the_same_digest(store, tmp_project):
    """The whole point: an unchanged project answers with the same bytes."""
    assert _audit_digest(tmp_project) == _audit_digest(tmp_project)


def test_the_audits_own_drift_md_write_does_not_change_the_digest(
    store, tmp_project
):
    """DRIFT.md is audit output and carries the digest; hashing it would make
    every audit invalidate its own answer."""
    first = _audit_digest(tmp_project)
    drift = tmp_project / ".project" / "DRIFT.md"
    assert drift.exists() and f"digest: {first}" in drift.read_text()

    drift.write_text("# tampered\n")
    assert _audit_digest(tmp_project) == first


def test_include_info_does_not_change_the_digest(store, tmp_project):
    """Same inputs, different projection of the findings — same fingerprint."""
    full = _audit_digest(tmp_project, include_info=True)
    brief = _audit_digest(tmp_project, include_info=False)
    assert full == brief


def test_the_digest_does_not_depend_on_the_absolute_project_path(
    store, tmp_project, tmp_path_factory
):
    """Paths are hashed relative to the PM directory, so a copied project (or
    a differently-mounted checkout) is recognised as the same state."""
    import shutil

    copy_root = tmp_path_factory.mktemp("copy")
    shutil.copytree(tmp_project / ".project", copy_root / ".project")
    assert compute_state_digest(copy_root) == compute_state_digest(tmp_project)


# ═══ sensitivity — anything a finding derives from moves it ═════


def test_the_digest_changes_after_a_task_status_update(store, tmp_project):
    before = _audit_digest(tmp_project)
    store.update("US-TST-1-1", status="done")
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_after_an_item_is_created(store, tmp_project):
    before = _audit_digest(tmp_project)
    store.create_task("US-TST-1", "Task 3", READY_BODY, points=1)
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_after_a_config_change(store, tmp_project):
    before = _audit_digest(tmp_project)
    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["description"] = "A test project, re-described"
    config_path.write_text(yaml.dump(config))
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_when_a_project_doc_changes(store, tmp_project):
    """Check 7 reads PROJECT.md, so PROJECT.md is audit state."""
    before = _audit_digest(tmp_project)
    doc = tmp_project / ".project" / "PROJECT.md"
    doc.write_text(doc.read_text() + "\nAnother decision.\n")
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_when_a_sprint_file_appears(store, tmp_project):
    """Files no check reads *today* are hashed too — the digest must not go
    stale the day a new check starts reading them."""
    before = _audit_digest(tmp_project)
    sprints = tmp_project / ".project" / "sprints"
    sprints.mkdir(exist_ok=True)
    (sprints / "SPRINT-TST-1.md").write_text("# Sprint 1\n")
    assert _audit_digest(tmp_project) != before


def test_a_run_log_entry_changes_the_digest(store, tmp_project):
    """The done-without-evidence check reads logs/*.jsonl."""
    before = _audit_digest(tmp_project)
    store.update("US-TST-1-2", outcome="info", note="worked on it")
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_when_a_task_is_archived(store, tmp_project):
    """Archiving sets the orthogonal ``archived`` flag and leaves ``status``
    alone, so it is a state change no status comparison would catch."""
    before = _audit_digest(tmp_project)
    store.archive("US-TST-1-2")
    assert _audit_digest(tmp_project) != before


def test_the_digest_changes_when_an_existing_sprint_is_edited(store, tmp_project):
    """Not just a new sprint file — an edit to one already there."""
    sprint = store.create_sprint("Sprint 1", goal="Ship the digest")
    before = _audit_digest(tmp_project)
    store.update_sprint(sprint.id, goal="Ship the digest, then the since param")
    assert _audit_digest(tmp_project) != before


def test_rewriting_identical_bytes_does_not_change_the_digest(store, tmp_project):
    """Content, not mtime: a no-op rewrite is not a state change."""
    before = _audit_digest(tmp_project)
    task_path = tmp_project / ".project" / "tasks" / "US-TST-1-1.md"
    task_path.write_text(task_path.read_text())
    assert _audit_digest(tmp_project) == before


# ═══ over the wire ══════════════════════════════════════════════


def test_the_tool_response_carries_the_digest(store, tmp_project):
    is_error, report = _audit_over_the_wire()
    assert not is_error, report
    assert re.fullmatch(r"[0-9a-f]{16}", _digest_of(report))


def test_both_tool_responses_carry_the_same_digest(store, tmp_project):
    """Default and include_info responses agree, and agree with DRIFT.md."""
    _, brief = _audit_over_the_wire()
    _, full = _audit_over_the_wire({"include_info": True})
    drift = (tmp_project / ".project" / "DRIFT.md").read_text()

    assert _digest_of(brief) == _digest_of(full) == _digest_of(drift)


def test_the_wire_digest_moves_when_the_project_moves(store, tmp_project):
    """What an orchestrator will do in US-PM-11-6: keep the digest, accept a
    task, poll again, and see that it changed."""
    _, before = _audit_over_the_wire()
    store.update("US-TST-1-1", status="done")
    _, after = _audit_over_the_wire()

    assert _digest_of(after) != _digest_of(before)


# ═══ identity — a digest names one state, and only that state ═══


def _snapshot(tmp_project):
    """Every hashed byte under .project, as {relative path: bytes}."""
    pm_dir = tmp_project / ".project"
    return {
        p.relative_to(pm_dir).as_posix(): p.read_bytes()
        for p in pm_dir.rglob("*")
        if p.is_file()
    }


def _restore(tmp_project, snapshot):
    """Put the project back exactly as ``_snapshot`` found it."""
    import shutil

    pm_dir = tmp_project / ".project"
    shutil.rmtree(pm_dir)
    for rel, data in snapshot.items():
        path = pm_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_restoring_a_state_restores_its_digest(store, tmp_project):
    """The digest names the state, not the history that reached it: undo the
    writes and the old digest comes back, so an orchestrator holding a stale
    digest across a revert is told the truth."""
    before = _audit_digest(tmp_project)
    # Snapshot after the audit, so anything the audit itself wrote is part of
    # the state being restored.
    original = _snapshot(tmp_project)

    store.update("US-TST-1-1", status="done")
    store.create_task("US-TST-1", "Task 3", READY_BODY, points=1)
    assert _audit_digest(tmp_project) != before

    _restore(tmp_project, original)
    assert _audit_digest(tmp_project) == before


def test_every_distinct_project_state_gets_a_distinct_digest(store, tmp_project):
    """Walk the project through every kind of change an audit cares about and
    assert no two of the states collide — the digest *identifies* the state,
    it does not merely react to some changes."""
    seen = {}

    def record(label):
        digest = _audit_digest(tmp_project)
        assert digest not in seen, f"{label} collides with {seen.get(digest)}"
        seen[digest] = label

    record("initial")

    store.update("US-TST-1-1", status="done")
    record("task status update")

    store.create_task("US-TST-1", "Task 3", READY_BODY, points=1)
    record("item creation")

    store.archive("US-TST-1-2")
    record("archive")

    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["description"] = "A test project, re-described"
    config_path.write_text(yaml.dump(config))
    record("config change")

    sprint = store.create_sprint("Sprint 1", goal="Ship the digest")
    record("sprint creation")

    store.update_sprint(sprint.id, status="active")
    record("sprint change")

    store.update("US-TST-1-2", outcome="info", note="worked on it")
    record("run-log entry")

    assert len(seen) == 8


# ═══ hub subprojects ════════════════════════════════════════════


@pytest.fixture
def tmp_hub(tmp_path_factory):
    """A minimal hub, built off its own root.

    Not the shared ``tmp_hub`` fixture: the autouse ``chdir_to_project`` above
    already claims ``tmp_path`` for a non-hub project, and both fixtures create
    ``<tmp_path>/.project``.
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
def hub_subproject(tmp_hub):
    """A hub with one registered subproject holding its own PM data."""
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
    return pm_dir


def test_a_hub_subproject_audit_reports_a_stable_digest(tmp_hub, hub_subproject):
    report = run_audit(tmp_hub, project_dir=hub_subproject)
    digest = _digest_of(report)
    assert re.fullmatch(r"[0-9a-f]{16}", digest)
    assert _digest_of(run_audit(tmp_hub, project_dir=hub_subproject)) == digest
    # And it fingerprints the subproject, not the hub root.
    assert digest != _digest_of(run_audit(tmp_hub))


def test_a_hub_subproject_digest_covers_the_hub_config(tmp_hub, hub_subproject):
    """Check 11 keys off ``load_config(root).hub``, and that file lives outside
    the subproject directory — so it has to be hashed explicitly."""
    before = _digest_of(run_audit(tmp_hub, project_dir=hub_subproject))

    hub_config = tmp_hub / ".project" / "config.yaml"
    config = yaml.safe_load(hub_config.read_text())
    config["hub"] = False
    hub_config.write_text(yaml.dump(config))
    clear_all_caches()

    assert _digest_of(run_audit(tmp_hub, project_dir=hub_subproject)) != before
