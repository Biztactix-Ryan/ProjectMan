"""Tests for token-usage optimizations: minimal write echoes, multi-ID pm_get,
opt-in run-log, pm_grab include_story, audit info filtering, pm_done_next."""

import pytest
import yaml


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Change to the project directory so server tools can find it."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    _store_cache.clear()


READY_TASK_BODY = """## Implementation
Do the thing.

## Testing
Verify the thing.

## Definition of Done
- [ ] Works
"""


# ─── Minimal write echoes ────────────────────────────────────────

def test_pm_update_echo_is_minimal(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", status="active")
    data = yaml.safe_load(result)
    assert data["updated"]["id"] == "US-TST-1"
    assert data["updated"]["status"] == "active"
    # Unchanged fields are not echoed back
    assert "body" not in data["updated"]
    assert "created" not in data["updated"]
    assert "acceptance_criteria" not in data["updated"]


def test_pm_update_echoes_changed_fields_only(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", tags="security,mvp")
    data = yaml.safe_load(result)
    assert data["updated"]["tags"] == ["security", "mvp"]
    assert "points" not in data["updated"]


def test_pm_update_run_log_ack(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", outcome="partial", note="halfway")
    data = yaml.safe_load(result)
    assert data["updated"]["run_log"] == "partial"


def test_pm_update_body_ack_without_echo(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", body="New body content")
    data = yaml.safe_load(result)
    assert data["updated"]["body_chars"] == len("New body content")
    assert "body" not in data["updated"]


def test_pm_create_story_echo_is_minimal(tmp_project):
    from projectman.server import pm_create_story
    result = pm_create_story(
        "My Story", "Long description here",
        acceptance_criteria="Can log in,Sees error",
        tags="mvp",
    )
    data = yaml.safe_load(result)
    assert data["created"]["id"] == "US-TST-1"
    assert data["created"]["title"] == "My Story"
    assert data["created"]["tags"] == ["mvp"]
    # Body/acceptance criteria are not echoed back
    assert "body" not in data["created"]
    assert "acceptance_criteria" not in data["created"]
    # Auto-created test tasks are id+title only
    assert len(data["test_tasks"]) == 2
    assert set(data["test_tasks"][0]) == {"id", "title"}


def test_pm_create_tasks_echo_is_minimal(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks
    pm_create_story("Story", "Desc")
    result = pm_create_tasks("US-TST-1", [
        {"title": "A", "description": "d", "points": 2},
        {"title": "B", "description": "d", "depends_on": ["US-TST-1-1"]},
    ])
    data = yaml.safe_load(result)
    assert data["count"] == 2
    assert data["created"][0] == {"id": "US-TST-1-1", "title": "A", "points": 2}
    assert data["created"][1]["depends_on"] == ["US-TST-1-1"]
    assert "description" not in data["created"][0]
    assert "body" not in data["created"][0]


# ─── pm_get: multi-ID + opt-in run log ───────────────────────────

def test_pm_get_multiple_ids(tmp_project):
    from projectman.server import pm_create_story, pm_get
    pm_create_story("First", "Body one")
    pm_create_story("Second", "Body two")
    result = pm_get("US-TST-1,US-TST-2")
    data = yaml.safe_load(result)
    assert isinstance(data, list)
    assert [d["id"] for d in data] == ["US-TST-1", "US-TST-2"]
    assert "Body one" in data[0]["body"]


def test_pm_get_multiple_ids_with_missing(tmp_project):
    from projectman.server import pm_create_story, pm_get
    pm_create_story("First", "Body one")
    result = pm_get("US-TST-1, US-TST-99")
    data = yaml.safe_load(result)
    assert data[0]["id"] == "US-TST-1"
    assert data[1]["id"] == "US-TST-99"
    assert "error" in data[1]


def test_pm_get_single_id_stays_flat(tmp_project):
    from projectman.server import pm_create_story, pm_get
    pm_create_story("First", "Body one")
    result = pm_get("US-TST-1")
    data = yaml.safe_load(result)
    assert isinstance(data, dict)
    assert data["id"] == "US-TST-1"


def test_pm_get_run_log_opt_in(tmp_project):
    from projectman.server import pm_create_story, pm_get, pm_update
    pm_create_story("Story", "Desc")
    pm_update("US-TST-1", outcome="info", note="a note")
    default = yaml.safe_load(pm_get("US-TST-1"))
    assert "recent_run_log" not in default
    with_log = yaml.safe_load(pm_get("US-TST-1", include_log=True))
    assert with_log["recent_run_log"][0]["note"] == "a note"


def test_pm_batch_get_by_ids(tmp_project):
    from projectman.server import pm_create_story, pm_batch_get
    pm_create_story("First", "Body one")
    pm_create_story("Second", "Body two")
    result = pm_batch_get(ids="US-TST-1,US-TST-2")
    data = yaml.safe_load(result)
    assert [d["id"] for d in data] == ["US-TST-1", "US-TST-2"]


def test_pm_batch_get_requires_type_or_ids(tmp_project):
    from projectman.server import pm_batch_get
    assert pm_batch_get().startswith("error:")


# ─── pm_grab: include_story + open siblings only ─────────────────

def _story_with_tasks(n=3):
    from projectman.server import pm_create_story, pm_create_tasks, pm_update
    pm_create_story("Story", "Story body text")
    pm_update("US-TST-1", status="active")
    pm_create_tasks("US-TST-1", [
        {"title": f"Task {i}", "description": READY_TASK_BODY, "points": 1}
        for i in range(1, n + 1)
    ])


def test_pm_grab_include_story_false_omits_body(tmp_project):
    from projectman.server import pm_grab
    _story_with_tasks()
    result = pm_grab("US-TST-1-1", include_story=False)
    data = yaml.safe_load(result)
    ctx = data["grabbed"]["story_context"]
    assert ctx["id"] == "US-TST-1"
    assert ctx["title"] == "Story"
    assert "body" not in ctx


def test_pm_grab_default_includes_body(tmp_project):
    from projectman.server import pm_grab
    _story_with_tasks()
    result = pm_grab("US-TST-1-1")
    data = yaml.safe_load(result)
    assert "Story body text" in data["grabbed"]["story_context"]["body"]


def test_pm_grab_siblings_exclude_done(tmp_project):
    from projectman.server import pm_grab, pm_update
    _story_with_tasks(3)
    pm_update("US-TST-1-2", status="in-progress", assignee="x")
    pm_update("US-TST-1-2", status="done")
    result = pm_grab("US-TST-1-1")
    data = yaml.safe_load(result)
    sibling_ids = [s["id"] for s in data["grabbed"]["sibling_tasks"]]
    assert "US-TST-1-2" not in sibling_ids
    assert "US-TST-1-3" in sibling_ids
    assert data["grabbed"]["sibling_tasks_total"] == 2
    assert data["grabbed"]["sibling_tasks_done"] == 1


# ─── pm_audit: info findings filtered by default ─────────────────

def test_pm_audit_hides_info_by_default(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks, pm_audit
    # Story 2pts, tasks sum to 3pts → info finding
    from projectman.server import pm_update
    pm_create_story("Story", "A reasonably long description of the story goes here")
    pm_update("US-TST-1", points=2, acceptance_criteria="It works")
    pm_create_tasks("US-TST-1", [
        {"title": "A", "description": READY_TASK_BODY, "points": 2},
        {"title": "B", "description": READY_TASK_BODY, "points": 1},
    ])
    report = pm_audit()
    assert "[INFO]" not in report
    if "Info:** 0" not in report:
        assert "omitted" in report
    full = pm_audit(include_info=True)
    assert "[INFO]" in full


def test_run_audit_still_writes_full_drift(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_audit
    pm_create_story("Story", "A reasonably long description of the story goes here")
    pm_update("US-TST-1", points=2, acceptance_criteria="It works")
    pm_create_tasks("US-TST-1", [
        {"title": "A", "description": READY_TASK_BODY, "points": 2},
        {"title": "B", "description": READY_TASK_BODY, "points": 1},
    ])
    pm_audit()  # default: info hidden from response
    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "[INFO]" in drift


# ─── pm_done_next ────────────────────────────────────────────────

def test_pm_done_next_completes_and_grabs_sibling(tmp_project):
    from projectman.server import pm_grab, pm_done_next, pm_get
    _story_with_tasks(3)
    pm_grab("US-TST-1-1")
    result = pm_done_next("US-TST-1-1", note="did the thing")
    data = yaml.safe_load(result)
    assert data["completed"] == {
        "id": "US-TST-1-1", "status": "done", "run_log": "success",
    }
    # Next task is the same-story sibling, claimed and in progress
    assert data["next"]["task"]["story_id"] == "US-TST-1"
    assert data["next"]["task"]["status"] == "in-progress"
    assert data["next"]["task"]["assignee"] == "claude"
    # Same story → story body omitted
    assert "body" not in data["next"]["story_context"]
    # Completed task really is done
    got = yaml.safe_load(pm_get("US-TST-1-1"))
    assert got["status"] == "done"


def test_pm_done_next_closes_story_when_last_task(tmp_project):
    from projectman.server import pm_grab, pm_done_next, pm_get
    _story_with_tasks(2)
    pm_grab("US-TST-1-1")
    yaml.safe_load(pm_done_next("US-TST-1-1"))
    result = yaml.safe_load(pm_done_next("US-TST-1-2"))
    assert result["story_closed"] == "US-TST-1"
    assert result["next"] is None
    assert "next_info" in result
    story = yaml.safe_load(pm_get("US-TST-1"))
    assert story["status"] == "done"


def test_pm_done_next_crosses_to_other_story_with_body(tmp_project):
    from projectman.server import (
        pm_create_story, pm_create_tasks, pm_update, pm_grab, pm_done_next,
    )
    _story_with_tasks(1)
    pm_create_story("Other story", "Other body text")
    pm_update("US-TST-2", status="active")
    pm_create_tasks("US-TST-2", [
        {"title": "Other task", "description": READY_TASK_BODY, "points": 1},
    ])
    pm_grab("US-TST-1-1")
    result = yaml.safe_load(pm_done_next("US-TST-1-1"))
    assert result["story_closed"] == "US-TST-1"
    assert result["next"]["task"]["story_id"] == "US-TST-2"
    # Different story → body included
    assert "Other body text" in result["next"]["story_context"]["body"]


def test_pm_done_next_same_story_only_stops(tmp_project):
    from projectman.server import (
        pm_create_story, pm_create_tasks, pm_update, pm_grab, pm_done_next,
    )
    _story_with_tasks(1)
    pm_create_story("Other story", "Other body")
    pm_update("US-TST-2", status="active")
    pm_create_tasks("US-TST-2", [
        {"title": "Other task", "description": READY_TASK_BODY, "points": 1},
    ])
    pm_grab("US-TST-1-1")
    result = yaml.safe_load(pm_done_next("US-TST-1-1", same_story_only=True))
    assert result["next"] is None
    assert "next_info" in result


def test_pm_done_next_without_note_skips_run_log(tmp_project):
    from projectman.server import pm_grab, pm_done_next
    from projectman.store import Store
    _story_with_tasks(2)
    pm_grab("US-TST-1-1")
    result = yaml.safe_load(pm_done_next("US-TST-1-1"))
    assert "run_log" not in result["completed"]
    store = Store(tmp_project)
    assert store.get_run_log("US-TST-1-1") == []


# ─── serialization ───────────────────────────────────────────────

def test_yaml_dump_unicode_and_no_wrapping():
    from projectman.server import _yaml_dump
    text = "Gossip push — " + "long words " * 30
    out = _yaml_dump({"title": text})
    assert "\\u2014" not in out  # em-dash not escaped
    assert "—" in out
    data = yaml.safe_load(out)
    assert data["title"] == text
