"""Tests for MCP server tool functions."""

import pytest
import os
import yaml

from projectman.store import Store
from projectman.indexer import write_index


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Change to the project directory so server tools can find it."""
    monkeypatch.chdir(tmp_project)


def test_pm_status(tmp_project):
    from projectman.server import pm_status
    result = pm_status()
    data = yaml.safe_load(result)
    assert data["project"] == "test-project"
    assert data["stories"] == 0


def test_pm_create_story(tmp_project):
    from projectman.server import pm_create_story
    result = pm_create_story("My Story", "Description here")
    data = yaml.safe_load(result)
    assert data["created"]["id"] == "US-TST-1"


def test_pm_get(tmp_project):
    from projectman.server import pm_create_story, pm_get
    pm_create_story("My Story", "Body text")
    result = pm_get("US-TST-1")
    data = yaml.safe_load(result)
    assert data["title"] == "My Story"
    assert "Body text" in data["body"]


def test_pm_create_task(tmp_project):
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    result = pm_create_task("US-TST-1", "Task 1", "Task desc")
    data = yaml.safe_load(result)
    assert data["created"]["id"] == "US-TST-1-1"


def test_pm_update(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", status="active")
    data = yaml.safe_load(result)
    assert data["updated"]["status"] == "active"


def test_pm_archive(tmp_project):
    from projectman.server import pm_create_story, pm_archive
    pm_create_story("Story", "Desc")
    result = pm_archive("US-TST-1")
    assert "archived" in result


def test_pm_active(tmp_project):
    from projectman.server import pm_create_story, pm_update, pm_active
    pm_create_story("Story", "Desc")
    pm_update("US-TST-1", status="active")
    result = pm_active()
    data = yaml.safe_load(result)
    assert len(data["active_stories"]) == 1


def test_pm_burndown(tmp_project):
    from projectman.server import pm_create_story, pm_burndown
    pm_create_story("Story", "Desc", points=5)
    result = pm_burndown()
    data = yaml.safe_load(result)
    assert data["total_points"] == 5


def test_pm_search(tmp_project):
    from projectman.server import pm_create_story, pm_search
    pm_create_story("Authentication system", "Login and signup flow")
    result = pm_search("auth")
    data = yaml.safe_load(result)
    assert len(data) >= 1


# ─── pm_board tests ─────────────────────────────────────────────

READY_TASK_BODY = """\
## Implementation

Add the login endpoint to the API router. Create a POST /login handler
that accepts email and password, validates credentials, and returns a JWT.

## Testing

Run pytest tests/test_auth.py to verify the endpoint works.

## Definition of Done

- [ ] POST /login endpoint works
- [ ] Returns JWT on success
"""


def test_pm_board_empty(tmp_project):
    from projectman.server import pm_board
    result = pm_board()
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 0
    assert data["summary"]["in_progress"] == 0


def test_pm_board_mixed_tasks(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_board
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create a ready task (has points, parent active, good body)
    pm_create_task("US-TST-1", "Ready task", READY_TASK_BODY, points=3)
    # Create a not-ready task (no points)
    pm_create_task("US-TST-1", "Not ready task", READY_TASK_BODY)
    # Create an in-progress task
    pm_create_task("US-TST-1", "In progress task", READY_TASK_BODY, points=2)
    pm_update("US-TST-1-3", status="in-progress", assignee="alice")

    result = pm_board()
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 1
    assert data["summary"]["not_ready"] == 1
    assert data["summary"]["in_progress"] == 1
    assert data["board"]["available"][0]["id"] == "US-TST-1-1"
    assert data["board"]["in_progress"][0]["assignee"] == "alice"


def test_pm_board_assignee_filter(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_board
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "Alice task", READY_TASK_BODY, points=2)
    pm_update("US-TST-1-1", status="in-progress", assignee="alice")
    pm_create_task("US-TST-1", "Bob task", READY_TASK_BODY, points=3)
    pm_update("US-TST-1-2", status="in-progress", assignee="bob")

    result = pm_board(assignee="alice")
    data = yaml.safe_load(result)
    assert data["summary"]["in_progress"] == 1
    assert data["board"]["in_progress"][0]["assignee"] == "alice"


# ─── pm_grab tests ──────────────────────────────────────────────

def test_pm_grab_success(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_grab
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "Grab me", READY_TASK_BODY, points=3)

    result = pm_grab("US-TST-1-1", assignee="claude")
    data = yaml.safe_load(result)
    assert "grabbed" in data
    assert data["grabbed"]["task"]["status"] == "in-progress"
    assert data["grabbed"]["task"]["assignee"] == "claude"
    assert data["grabbed"]["story_context"]["id"] == "US-TST-1"


def test_pm_grab_not_ready_no_points(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_grab
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "No points", READY_TASK_BODY)

    result = pm_grab("US-TST-1-1")
    data = yaml.safe_load(result)
    assert "error" in data
    assert any("no point estimate" in b for b in data["blockers"])


def test_pm_grab_already_assigned(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_grab
    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "Taken", READY_TASK_BODY, points=2)
    pm_update("US-TST-1-1", assignee="alice")

    result = pm_grab("US-TST-1-1")
    data = yaml.safe_load(result)
    assert "error" in data
    assert any("already assigned" in b for b in data["blockers"])


def test_pm_grab_parent_story_backlog(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_grab
    pm_create_story("Story", "Description")
    # Story stays in backlog (default)
    pm_create_task("US-TST-1", "Blocked by story", READY_TASK_BODY, points=3)

    result = pm_grab("US-TST-1-1")
    data = yaml.safe_load(result)
    assert "error" in data
    assert any("backlog" in b for b in data["blockers"])
