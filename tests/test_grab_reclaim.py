"""Tests for idempotent pm_grab re-claim (same assignee) and pm_update unassign —
the orchestrator pre-claims tasks via pm_done_next, then workers re-grab them."""

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


def _story_with_tasks(n=3):
    from projectman.server import pm_create_story, pm_create_tasks, pm_update
    pm_create_story("Story", "Story body text")
    pm_update("US-TST-1", status="active")
    pm_create_tasks("US-TST-1", [
        {"title": f"Task {i}", "description": READY_TASK_BODY, "points": 1}
        for i in range(1, n + 1)
    ])


# ─── Idempotent re-claim ─────────────────────────────────────────

def test_pm_grab_reclaim_same_assignee(tmp_project):
    from projectman.server import pm_grab
    _story_with_tasks(1)
    first = yaml.safe_load(pm_grab("US-TST-1-1"))
    again = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert "grabbed" in first and "grabbed" in again
    assert again["grabbed"]["task"]["status"] == "in-progress"
    assert again["grabbed"]["task"]["assignee"] == "claude"


def test_pm_grab_still_blocks_other_assignee(tmp_project):
    from projectman.server import pm_grab
    _story_with_tasks(1)
    pm_grab("US-TST-1-1")
    result = yaml.safe_load(pm_grab("US-TST-1-1", assignee="bob"))
    assert result["error"] == "task is not ready to grab"
    assert any("already assigned to 'claude'" in b for b in result["blockers"])


def test_pm_grab_reclaims_todo_task_assigned_to_self(tmp_project):
    """Retry path: orchestrator resets status to todo but assignee sticks —
    the retry worker's grab must still succeed."""
    from projectman.server import pm_grab, pm_update
    _story_with_tasks(1)
    pm_grab("US-TST-1-1")
    pm_update("US-TST-1-1", status="todo")
    result = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert "grabbed" in result
    assert result["grabbed"]["task"]["status"] == "in-progress"


def test_pm_grab_blocks_done_task_even_for_same_assignee(tmp_project):
    from projectman.server import pm_grab, pm_update
    _story_with_tasks(1)
    pm_grab("US-TST-1-1")
    pm_update("US-TST-1-1", status="done")
    result = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert result["error"] == "task is not ready to grab"


def test_done_next_pre_claim_then_worker_grab(tmp_project):
    """Orchestrator handoff: pm_done_next pre-claims the next task, then the
    worker re-grabs it without error and gets the full context payload."""
    from projectman.server import pm_grab, pm_done_next
    _story_with_tasks(2)
    pm_grab("US-TST-1-1")
    done = yaml.safe_load(pm_done_next("US-TST-1-1", note="done", same_story_only=True))
    next_id = done["next"]["task"]["id"]
    assert done["next"]["task"]["assignee"] == "claude"
    worker = yaml.safe_load(pm_grab(next_id))
    assert "grabbed" in worker
    assert worker["grabbed"]["task"]["id"] == next_id
    assert worker["grabbed"]["task"]["status"] == "in-progress"


# ─── Unassign via assignee="" ────────────────────────────────────

def test_pm_update_unassign_with_empty_string(tmp_project):
    from projectman.server import pm_grab, pm_update, pm_get
    _story_with_tasks(1)
    pm_grab("US-TST-1-1")
    pm_update("US-TST-1-1", status="todo", assignee="")
    got = yaml.safe_load(pm_get("US-TST-1-1"))
    assert got.get("assignee") is None
    assert got["status"] == "todo"


def test_unassigned_task_grabbable_by_someone_else(tmp_project):
    from projectman.server import pm_grab, pm_update
    _story_with_tasks(1)
    pm_grab("US-TST-1-1")
    pm_update("US-TST-1-1", status="todo", assignee="")
    result = yaml.safe_load(pm_grab("US-TST-1-1", assignee="bob"))
    assert "grabbed" in result
    assert result["grabbed"]["task"]["assignee"] == "bob"


def test_released_task_visible_to_done_next(tmp_project):
    """A released pre-claim must re-enter the pm_done_next candidate pool
    (it filters to unassigned todo tasks)."""
    from projectman.server import pm_grab, pm_update, pm_done_next
    _story_with_tasks(2)
    pm_grab("US-TST-1-2")
    pm_update("US-TST-1-2", status="todo", assignee="")
    pm_grab("US-TST-1-1")
    done = yaml.safe_load(pm_done_next("US-TST-1-1", same_story_only=True))
    assert done["next"]["task"]["id"] == "US-TST-1-2"
