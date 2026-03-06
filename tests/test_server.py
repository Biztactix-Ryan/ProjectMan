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
    from projectman.server import _store_cache
    _store_cache.clear()


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


def test_pm_create_story_with_tags(tmp_project):
    from projectman.server import pm_create_story
    result = pm_create_story("Tagged Story", "Desc", tags="security,mvp,backend")
    data = yaml.safe_load(result)
    assert data["created"]["tags"] == ["security", "mvp", "backend"]


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


def test_pm_create_task_with_tags(tmp_project):
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    result = pm_create_task("US-TST-1", "Tagged Task", "Task desc", tags="backend,api,v2")
    data = yaml.safe_load(result)
    assert data["created"]["tags"] == ["backend", "api", "v2"]


def test_pm_create_task_with_depends_on(tmp_project):
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "First Task", "Task desc")
    pm_create_task("US-TST-1", "Second Task", "Task desc")
    result = pm_create_task(
        "US-TST-1", "Dependent Task", "Task desc",
        depends_on="US-TST-1-1,US-TST-1-2",
    )
    data = yaml.safe_load(result)
    assert data["created"]["depends_on"] == ["US-TST-1-1", "US-TST-1-2"]


def test_pm_create_tasks_docstring_documents_depends_on():
    from projectman.server import pm_create_tasks
    assert "depends_on" in pm_create_tasks.__doc__


def test_pm_update(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", status="active")
    data = yaml.safe_load(result)
    assert data["updated"]["status"] == "active"


def test_pm_update_tags_story(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", tags="security,mvp,backend")
    data = yaml.safe_load(result)
    assert data["updated"]["tags"] == ["security", "mvp", "backend"]


def test_pm_update_tags_task(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "Task", "Task desc")
    result = pm_update("US-TST-1-1", tags="api,v2")
    data = yaml.safe_load(result)
    assert data["updated"]["tags"] == ["api", "v2"]


def test_pm_update_depends_on(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "Task A", "Desc")
    pm_create_task("US-TST-1", "Task B", "Desc")
    pm_create_task("US-TST-1", "Task C", "Desc")
    result = pm_update("US-TST-1-3", depends_on="US-TST-1-1,US-TST-1-2")
    data = yaml.safe_load(result)
    assert data["updated"]["depends_on"] == ["US-TST-1-1", "US-TST-1-2"]


def test_pm_create_task_depends_on_whitespace_stripped(tmp_project):
    """Comma-separated depends_on values have whitespace stripped."""
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "First", "Desc")
    pm_create_task("US-TST-1", "Second", "Desc")
    result = pm_create_task(
        "US-TST-1", "Third", "Desc",
        depends_on="US-TST-1-1 , US-TST-1-2 ",
    )
    data = yaml.safe_load(result)
    assert data["created"]["depends_on"] == ["US-TST-1-1", "US-TST-1-2"]


def test_pm_create_task_depends_on_single(tmp_project):
    """A single dependency (no comma) is parsed correctly."""
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "First", "Desc")
    result = pm_create_task(
        "US-TST-1", "Second", "Desc",
        depends_on="US-TST-1-1",
    )
    data = yaml.safe_load(result)
    assert data["created"]["depends_on"] == ["US-TST-1-1"]


def test_pm_create_task_depends_on_none(tmp_project):
    """Omitting depends_on results in no dependencies."""
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    result = pm_create_task("US-TST-1", "Task", "Desc")
    data = yaml.safe_load(result)
    assert data["created"].get("depends_on") in (None, [])


def test_pm_update_depends_on_whitespace_stripped(tmp_project):
    """pm_update strips whitespace from comma-separated depends_on."""
    from projectman.server import pm_create_story, pm_create_task, pm_update
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "Task A", "Desc")
    pm_create_task("US-TST-1", "Task B", "Desc")
    pm_create_task("US-TST-1", "Task C", "Desc")
    result = pm_update("US-TST-1-3", depends_on=" US-TST-1-1 , US-TST-1-2")
    data = yaml.safe_load(result)
    assert data["updated"]["depends_on"] == ["US-TST-1-1", "US-TST-1-2"]


def test_pm_update_depends_on_single(tmp_project):
    """pm_update parses a single depends_on ID correctly."""
    from projectman.server import pm_create_story, pm_create_task, pm_update
    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "Task A", "Desc")
    pm_create_task("US-TST-1", "Task B", "Desc")
    result = pm_update("US-TST-1-2", depends_on="US-TST-1-1")
    data = yaml.safe_load(result)
    assert data["updated"]["depends_on"] == ["US-TST-1-1"]


def test_pm_update_tags_epic(tmp_project):
    from projectman.server import pm_create_epic, pm_update
    pm_create_epic("Epic", "Epic desc")
    result = pm_update("EPIC-TST-1", tags="infra,q2")
    data = yaml.safe_load(result)
    assert data["updated"]["tags"] == ["infra", "q2"]


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


def test_pm_active_tag_filter(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_active

    # Story with "api" tag
    pm_create_story("API Story", "Description", tags="api")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "API task", READY_TASK_BODY, points=3)
    pm_update("US-TST-1-1", status="in-progress")

    # Story without tag, but task has "api" tag
    pm_create_story("Other Story", "Description")
    pm_update("US-TST-2", status="active")
    pm_create_task("US-TST-2", "Tagged task", READY_TASK_BODY, points=2, tags="api")
    pm_update("US-TST-2-1", status="in-progress")

    # Story and task with "web" tag only
    pm_create_story("Web Story", "Description", tags="web")
    pm_update("US-TST-3", status="active")
    pm_create_task("US-TST-3", "Web task", READY_TASK_BODY, points=2)
    pm_update("US-TST-3-1", status="in-progress")

    # Unfiltered: all 3 stories and 3 tasks visible
    result = pm_active()
    data = yaml.safe_load(result)
    assert data["active_stories_total"] == 3
    assert data["active_tasks_total"] == 3

    # Filtered by "api": 1 story (API Story) + 2 tasks (task has tag, or story has tag)
    result = pm_active(tag="api")
    data = yaml.safe_load(result)
    assert data["active_stories_total"] == 1
    assert data["active_stories"][0]["title"] == "API Story"
    assert data["active_tasks_total"] == 2
    task_ids = {t["id"] for t in data["active_tasks"]}
    assert task_ids == {"US-TST-1-1", "US-TST-2-1"}

    # Filtered by "web": 1 story + 1 task (inherits from story tag)
    result = pm_active(tag="web")
    data = yaml.safe_load(result)
    assert data["active_stories_total"] == 1
    assert data["active_tasks_total"] == 1
    assert data["active_tasks"][0]["id"] == "US-TST-3-1"

    # Non-existent tag: nothing
    result = pm_active(tag="nonexistent")
    data = yaml.safe_load(result)
    assert data["active_stories_total"] == 0
    assert data["active_tasks_total"] == 0


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


def test_pm_search_tag_filter(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_search

    # Story with "api" tag
    pm_create_story("API Authentication", "API auth flow", tags="api")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "Implement API auth", "Build the auth endpoint", points=3, tags="api")

    # Story with "web" tag
    pm_create_story("Web Authentication", "Web auth flow", tags="web")
    pm_update("US-TST-2", status="active")
    pm_create_task("US-TST-2", "Implement web auth", "Build the web login", points=2, tags="web")

    # Story with no tags
    pm_create_story("Auth docs", "Document auth", tags=None)

    # Unfiltered: all items match "auth"
    result = pm_search("auth")
    data = yaml.safe_load(result)
    assert len(data) >= 3  # at least both stories + tasks

    # Filtered by "api": only items tagged "api"
    result = pm_search("auth", tag="api")
    data = yaml.safe_load(result)
    ids = {item["id"] for item in data}
    assert "US-TST-1" in ids
    assert "US-TST-2" not in ids

    # Filtered by "web": only items tagged "web"
    result = pm_search("auth", tag="web")
    data = yaml.safe_load(result)
    ids = {item["id"] for item in data}
    assert "US-TST-2" in ids
    assert "US-TST-1" not in ids

    # Non-existent tag: empty results
    result = pm_search("auth", tag="nonexistent")
    data = yaml.safe_load(result)
    assert data is None or len(data) == 0


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


def test_pm_board_tag_filter(tmp_project):
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_board
    # Story with "api" tag
    pm_create_story("API Story", "Description", tags="api")
    pm_update("US-TST-1", status="active")
    pm_create_task("US-TST-1", "API task", READY_TASK_BODY, points=3)

    # Story without tag, but task has "api" tag
    pm_create_story("Other Story", "Description")
    pm_update("US-TST-2", status="active")
    pm_create_task("US-TST-2", "Tagged task", READY_TASK_BODY, points=2, tags="api")

    # Story and task with no matching tag
    pm_create_story("Web Story", "Description", tags="web")
    pm_update("US-TST-3", status="active")
    pm_create_task("US-TST-3", "Web task", READY_TASK_BODY, points=2)

    # Unfiltered: all 3 tasks visible
    result = pm_board()
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 3

    # Filtered by "api": task inherits from story tag + task's own tag
    result = pm_board(tag="api")
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 2
    ids = {t["id"] for t in data["board"]["available"]}
    assert ids == {"US-TST-1-1", "US-TST-2-1"}

    # Filtered by "web": only the web story's task
    result = pm_board(tag="web")
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 1
    assert data["board"]["available"][0]["id"] == "US-TST-3-1"

    # Non-existent tag: nothing
    result = pm_board(tag="nonexistent")
    data = yaml.safe_load(result)
    assert data["summary"]["available"] == 0


def test_pm_board_incomplete_deps_not_ready(tmp_project):
    """Tasks with incomplete dependencies appear in not_ready on the board."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_board

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create two tasks: task 2 depends on task 1
    pm_create_tasks("US-TST-1", [
        {"title": "Prerequisite task", "description": READY_TASK_BODY, "points": 2},
        {"title": "Dependent task", "description": READY_TASK_BODY, "points": 3,
         "depends_on": ["US-TST-1-1"]},
    ])

    result = pm_board()
    data = yaml.safe_load(result)

    # Task 1 (no deps) should be available
    available_ids = {t["id"] for t in data["board"]["available"]}
    assert "US-TST-1-1" in available_ids

    # Task 2 (depends on incomplete task 1) should be not_ready
    not_ready_ids = {t["id"] for t in data["board"]["not_ready"]}
    assert "US-TST-1-2" in not_ready_ids
    assert "US-TST-1-2" not in available_ids

    # Verify the blocker message mentions the dependency
    not_ready_task = next(t for t in data["board"]["not_ready"] if t["id"] == "US-TST-1-2")
    assert any("depend" in b.lower() or "US-TST-1-1" in b for b in not_ready_task["blockers"])


def test_pm_board_completed_deps_available(tmp_project):
    """Tasks whose dependencies are all done appear in available on the board."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_board

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    pm_create_tasks("US-TST-1", [
        {"title": "Prerequisite task", "description": READY_TASK_BODY, "points": 2},
        {"title": "Dependent task", "description": READY_TASK_BODY, "points": 3,
         "depends_on": ["US-TST-1-1"]},
    ])

    # Complete the prerequisite
    pm_update("US-TST-1-1", status="in-progress", assignee="alice")
    pm_update("US-TST-1-1", status="done")

    result = pm_board()
    data = yaml.safe_load(result)

    # Task 2 should now be available (dep is done)
    available_ids = {t["id"] for t in data["board"]["available"]}
    assert "US-TST-1-2" in available_ids


def test_pm_board_available_topological_order(tmp_project):
    """Board available section sorted by topological order within each story."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_board

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create tasks where topological order differs from ID order:
    # Task 1 depends on task 3, task 2 has no deps, task 3 has no deps.
    # Topological order: task 2 and task 3 come before task 1.
    pm_create_tasks("US-TST-1", [
        {"title": "Depends on task 3", "description": READY_TASK_BODY, "points": 2,
         "depends_on": ["US-TST-1-3"]},
        {"title": "No deps A", "description": READY_TASK_BODY, "points": 2},
        {"title": "No deps B", "description": READY_TASK_BODY, "points": 2},
    ])

    # Mark task 3 as done so task 1 becomes available
    pm_update("US-TST-1-3", status="in-progress", assignee="alice")
    pm_update("US-TST-1-3", status="done")

    result = pm_board()
    data = yaml.safe_load(result)

    available_ids = [t["id"] for t in data["board"]["available"]]

    # Both task 1 and task 2 should be available
    assert "US-TST-1-1" in available_ids
    assert "US-TST-1-2" in available_ids

    # Topological order: task 2 (no deps) should come before task 1 (depends on 3)
    idx_1 = available_ids.index("US-TST-1-1")
    idx_2 = available_ids.index("US-TST-1-2")
    assert idx_2 < idx_1, (
        f"Task 2 (no deps) should appear before task 1 (depends on 3) in "
        f"topological order, but got: {available_ids}"
    )


def test_pm_board_available_topological_order_chain(tmp_project):
    """Board orders available tasks by topological depth within a story."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_board

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Chain: task 4 -> task 2 -> task 1, task 3 independent.
    # ID order: 1, 2, 3, 4. Topological order: 1, 3, 2, 4.
    pm_create_tasks("US-TST-1", [
        {"title": "Root", "description": READY_TASK_BODY, "points": 2},
        {"title": "Mid (depends on 1)", "description": READY_TASK_BODY, "points": 2,
         "depends_on": ["US-TST-1-1"]},
        {"title": "Independent", "description": READY_TASK_BODY, "points": 2},
        {"title": "Leaf (depends on 2)", "description": READY_TASK_BODY, "points": 2,
         "depends_on": ["US-TST-1-2"]},
    ])

    # Complete tasks 1 and 2 so task 4 becomes available
    pm_update("US-TST-1-1", status="in-progress", assignee="alice")
    pm_update("US-TST-1-1", status="done")
    pm_update("US-TST-1-2", status="in-progress", assignee="alice")
    pm_update("US-TST-1-2", status="done")

    result = pm_board()
    data = yaml.safe_load(result)

    available_ids = [t["id"] for t in data["board"]["available"]]

    # Task 3 (independent, depth 0) and task 4 (depth 2) should both be available
    assert "US-TST-1-3" in available_ids
    assert "US-TST-1-4" in available_ids

    # Topological order: task 3 (depth 0) should come before task 4 (depth 2)
    idx_3 = available_ids.index("US-TST-1-3")
    idx_4 = available_ids.index("US-TST-1-4")
    assert idx_3 < idx_4, (
        f"Task 3 (depth 0) should appear before task 4 (depth 2) in "
        f"topological order, but got: {available_ids}"
    )


def test_pm_board_cycle_fallback(tmp_project):
    """Board with a dependency cycle in one story doesn't crash."""
    import frontmatter as fm
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_board

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create two tasks without deps first
    pm_create_tasks("US-TST-1", [
        {"title": "Task A", "description": READY_TASK_BODY, "points": 2},
        {"title": "Task B", "description": READY_TASK_BODY, "points": 2},
    ])

    # Inject a cycle by directly writing depends_on into both task files
    tasks_dir = tmp_project / ".project" / "tasks"
    for fname, dep in [("US-TST-1-1.md", "US-TST-1-2"), ("US-TST-1-2.md", "US-TST-1-1")]:
        path = tasks_dir / fname
        post = fm.load(path)
        post.metadata["depends_on"] = [dep]
        path.write_text(fm.dumps(post))

    # Board should not crash — cycle falls back to original order
    result = pm_board()
    data = yaml.safe_load(result)

    # Both tasks should appear somewhere on the board (not_ready due to
    # incomplete deps, but the board itself must not error)
    all_ids = []
    for group in data["board"].values():
        if isinstance(group, list):
            all_ids.extend(t["id"] for t in group)
    assert "US-TST-1-1" in all_ids or "US-TST-1-2" in all_ids


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


def test_pm_grab_incomplete_dependencies(tmp_project):
    """pm_grab returns error when task has incomplete dependencies."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_grab

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create two tasks: task 2 depends on task 1
    pm_create_tasks("US-TST-1", [
        {"title": "Prerequisite task", "description": READY_TASK_BODY, "points": 2},
        {"title": "Dependent task", "description": READY_TASK_BODY, "points": 3,
         "depends_on": ["US-TST-1-1"]},
    ])

    # Try to grab the dependent task while prerequisite is still todo
    result = pm_grab("US-TST-1-2")
    data = yaml.safe_load(result)
    assert "error" in data
    assert any("incomplete dependencies" in b for b in data["blockers"])
    assert any("US-TST-1-1" in b for b in data["blockers"])


def test_pm_grab_dependency_status_in_response(tmp_project):
    """pm_grab includes dependency_status in response showing dep titles and statuses."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_update, pm_grab

    pm_create_story("Story", "Description")
    pm_update("US-TST-1", status="active")

    # Create three tasks: task 3 depends on tasks 1 and 2
    pm_create_tasks("US-TST-1", [
        {"title": "First prerequisite", "description": READY_TASK_BODY, "points": 2},
        {"title": "Second prerequisite", "description": READY_TASK_BODY, "points": 2},
        {"title": "Dependent task", "description": READY_TASK_BODY, "points": 3,
         "depends_on": ["US-TST-1-1", "US-TST-1-2"]},
    ])

    # Complete both prerequisites so the dependent task can be grabbed
    pm_update("US-TST-1-1", status="in-progress", assignee="alice")
    pm_update("US-TST-1-1", status="done")
    pm_update("US-TST-1-2", status="in-progress", assignee="bob")
    pm_update("US-TST-1-2", status="done")

    # Grab the dependent task
    result = pm_grab("US-TST-1-3")
    data = yaml.safe_load(result)

    assert "grabbed" in data
    assert "dependency_status" in data["grabbed"]

    dep_status = data["grabbed"]["dependency_status"]
    assert len(dep_status) == 2

    # Each entry should include id, title, and status
    dep_ids = {d["id"] for d in dep_status}
    assert dep_ids == {"US-TST-1-1", "US-TST-1-2"}

    for dep in dep_status:
        assert "id" in dep
        assert "title" in dep
        assert "status" in dep
        assert dep["status"] == "done"


# ─── pm_commit tests ────────────────────────────────────────────

def test_pm_commit_auto_message(tmp_git_project, monkeypatch):
    """pm_commit commits .project/ changes with an auto-generated message."""
    import subprocess

    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_create_story, pm_commit

    # Create a story (generates .project/ changes)
    pm_create_story("Auth feature", "Add login endpoint")

    result = pm_commit()
    data = yaml.safe_load(result)

    assert "committed" in data
    assert data["committed"]["commit_hash"]
    assert data["committed"]["message"].startswith("pm: ")
    assert len(data["committed"]["files_committed"]) > 0

    # Verify git log shows the commit
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=str(tmp_git_project),
        capture_output=True,
        text=True,
    )
    assert "pm: " in log.stdout


def test_pm_commit_custom_message(tmp_git_project, monkeypatch):
    """pm_commit accepts a custom message override."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_create_story, pm_commit

    pm_create_story("Feature", "Description")
    result = pm_commit(message="custom: my commit")
    data = yaml.safe_load(result)

    assert data["committed"]["message"] == "custom: my commit"


def test_pm_commit_no_changes(tmp_git_project, monkeypatch):
    """pm_commit returns an error when there are no .project/ changes."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_commit

    result = pm_commit()
    assert "error" in result
    assert "No .project/ changes" in result


def test_pm_commit_message_summarizes_file_types(tmp_git_project, monkeypatch):
    """Auto-generated message includes story and task counts."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_create_story, pm_create_task, pm_update, pm_commit

    pm_create_story("Story", "Description")
    pm_create_task("US-TST-1", "Task 1", "Do something", points=3)

    result = pm_commit()
    data = yaml.safe_load(result)
    msg = data["committed"]["message"]

    # Message should mention stories and tasks
    assert "stor" in msg.lower() or "task" in msg.lower()


# ─── pm_push tests ─────────────────────────────────────────────

def test_pm_push_success(tmp_git_project_with_remote, monkeypatch):
    """pm_push pushes committed .project/ changes to the remote."""
    import subprocess

    monkeypatch.chdir(tmp_git_project_with_remote)
    from projectman.server import pm_create_story, pm_commit, pm_push

    pm_create_story("Feature", "Description")
    pm_commit()

    result = pm_push()
    data = yaml.safe_load(result)

    assert "pushed" in data
    assert data["pushed"]["branch"]
    assert data["pushed"]["remote"] == "origin"


def test_pm_push_no_remote(tmp_git_project, monkeypatch):
    """pm_push returns an error when no remote is configured."""
    monkeypatch.chdir(tmp_git_project)
    from projectman.server import pm_create_story, pm_commit, pm_push

    pm_create_story("Feature", "Description")
    pm_commit()

    result = pm_push()
    assert "error" in result.lower()


def test_pm_push_nothing_to_push(tmp_git_project_with_remote, monkeypatch):
    """pm_push returns a message when there are no new commits to push."""
    monkeypatch.chdir(tmp_git_project_with_remote)
    from projectman.server import pm_push

    result = pm_push()
    data = yaml.safe_load(result)

    # Should succeed but indicate nothing new was pushed, or succeed cleanly
    assert "pushed" in data or "up_to_date" in data


def test_pm_push_validates_branch_not_detached(tmp_git_project_with_remote, monkeypatch):
    """pm_push rejects pushes from a detached HEAD state."""
    import subprocess

    monkeypatch.chdir(tmp_git_project_with_remote)
    from projectman.server import pm_push

    # Detach HEAD
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_git_project_with_remote),
        capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", head],
        cwd=str(tmp_git_project_with_remote),
        capture_output=True,
    )

    result = pm_push()
    assert "error" in result.lower()
    assert "detach" in result.lower() or "branch" in result.lower()


def test_pm_push_returns_branch_info(tmp_git_project_with_remote, monkeypatch):
    """pm_push response includes the branch that was pushed."""
    monkeypatch.chdir(tmp_git_project_with_remote)
    from projectman.server import pm_create_story, pm_commit, pm_push

    pm_create_story("Story", "Desc")
    pm_commit()

    result = pm_push()
    data = yaml.safe_load(result)

    assert "pushed" in data
    branch = data["pushed"]["branch"]
    assert branch in ("main", "master")


def test_store_cache_returns_same_instance(tmp_project):
    """_store() returns the same Store instance across calls (cache hit)."""
    from projectman.server import _store, _store_cache
    _store_cache.clear()
    store1 = _store()
    store2 = _store()
    assert store1 is store2


def test_store_cache_keyed_by_path(tmp_project):
    """_store() caches by project path — repeated calls return the same instance."""
    from projectman.server import _store, _store_cache
    _store_cache.clear()

    store1 = _store()
    store2 = _store()

    # Same default project path returns same instance
    assert store1 is store2

    # Cache has exactly one entry keyed by the .project/ Path
    assert len(_store_cache) == 1
    cached_path = next(iter(_store_cache.keys()))
    assert cached_path == tmp_project / ".project"


def test_store_cache_persists_across_tool_calls(tmp_project):
    """Cache persists so sequential MCP tool calls share the same Store."""
    from projectman.server import _store, _store_cache
    _store_cache.clear()
    store1 = _store()
    # Simulate a second tool call — _store() should return cached instance
    store2 = _store()
    assert store1 is store2
    assert len(_store_cache) == 1


def test_cache_persists_across_mcp_tool_invocations(tmp_project):
    """Cache persists across real MCP tool invocations within the same server process."""
    from projectman.server import (
        _store_cache, pm_status, pm_create_story, pm_get, pm_search,
    )
    _store_cache.clear()

    # First tool invocation: pm_status
    pm_status()
    assert len(_store_cache) == 1
    store_after_status = next(iter(_store_cache.values()))

    # Second tool invocation: pm_create_story
    pm_create_story("Cache Test Story", "Verify cache persistence")
    assert len(_store_cache) == 1
    store_after_create = next(iter(_store_cache.values()))
    assert store_after_create is store_after_status

    # Third tool invocation: pm_get
    pm_get("US-TST-1")
    assert len(_store_cache) == 1
    store_after_get = next(iter(_store_cache.values()))
    assert store_after_get is store_after_status

    # Fourth tool invocation: pm_search
    pm_search("cache")
    assert len(_store_cache) == 1
    store_after_search = next(iter(_store_cache.values()))
    assert store_after_search is store_after_status


def test_store_cache_same_project_returns_same_instance(tmp_project):
    """_store() returns the same cached Store for repeated calls with the same project name."""
    from projectman.config import load_config, save_config
    from projectman.server import _store, _store_cache

    # Convert tmp_project into a hub layout
    hub_config = load_config(tmp_project)
    hub_config.hub = True
    hub_config.projects = []
    save_config(hub_config, tmp_project)

    # Register two subprojects
    for name, prefix in [("alpha", "ALP"), ("beta", "BET")]:
        pm_dir = tmp_project / ".project" / "projects" / name
        pm_dir.mkdir(parents=True, exist_ok=True)
        (pm_dir / "stories").mkdir(exist_ok=True)
        (pm_dir / "tasks").mkdir(exist_ok=True)
        (pm_dir / "epics").mkdir(exist_ok=True)
        sub_conf = {"name": name, "prefix": prefix, "description": "",
                    "hub": False, "next_story_id": 1, "next_epic_id": 1, "projects": []}
        with open(pm_dir / "config.yaml", "w") as f:
            yaml.dump(sub_conf, f)
        hub_config = load_config(tmp_project)
        hub_config.projects.append(name)
        save_config(hub_config, tmp_project)

    _store_cache.clear()

    # Same project twice → same instance (identity check)
    store_a1 = _store(project="alpha")
    store_a2 = _store(project="alpha")
    assert store_a1 is store_a2

    # Different project → different instance
    store_b = _store(project="beta")
    assert store_b is not store_a1

    # Cache should have exactly two entries
    assert len(_store_cache) == 2
