"""Tests for tasks CRUD, board, docs, and error cases."""


def _create_story(client, title="Test Story", status="active"):
    """Helper: create and activate a story, return its ID."""
    r = client.post("/api/stories", json={
        "title": title,
        "description": "test description",
        "points": 3,
    })
    story_id = r.json()["id"]
    if status != "backlog":
        client.patch(f"/api/stories/{story_id}", json={"status": status})
    return story_id


# ─── Tasks CRUD ──────────────────────────────────────────────────


def test_task_lifecycle(client):
    story_id = _create_story(client)

    # Create
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Test Task",
        "description": "do the thing",
        "points": 2,
    })
    assert r.status_code == 201
    task = r.json()
    assert task["title"] == "Test Task"
    assert task["points"] == 2
    task_id = task["id"]

    # List
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Read detail
    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["body"] == "do the thing"

    # Update
    r = client.patch(f"/api/tasks/{task_id}", json={"status": "in-progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in-progress"

    # Archive
    r = client.delete(f"/api/tasks/{task_id}")
    assert r.status_code == 200


def test_task_not_found(client):
    r = client.get("/api/tasks/US-NOPE-1-1")
    assert r.status_code == 404


def test_task_filter_by_story(client):
    s1 = _create_story(client, "Story 1")
    s2 = _create_story(client, "Story 2")

    client.post("/api/tasks", json={"story_id": s1, "title": "T1", "description": "d"})
    client.post("/api/tasks", json={"story_id": s2, "title": "T2", "description": "d"})

    r = client.get(f"/api/tasks?story_id={s1}")
    assert len(r.json()) == 1
    assert r.json()[0]["story_id"] == s1


def test_task_filter_by_status(client):
    story_id = _create_story(client)
    client.post("/api/tasks", json={"story_id": story_id, "title": "T1", "description": "d"})

    r = client.get(f"/api/tasks?story_id={story_id}&status=todo")
    assert len(r.json()) == 1

    r = client.get(f"/api/tasks?story_id={story_id}&status=done")
    assert len(r.json()) == 0


def test_task_create_missing_story_returns_404(client):
    r = client.post("/api/tasks", json={
        "story_id": "US-NOPE-99",
        "title": "Orphan",
        "description": "d",
    })
    assert r.status_code == 404


def test_grab_ready_task(client):
    story_id = _create_story(client, status="active")
    # Task must have points and a description >= 50 chars to pass readiness
    long_desc = "This is a sufficiently long task description that passes the readiness check."
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Grabbable",
        "description": long_desc,
        "points": 2,
    })
    task_id = r.json()["id"]

    r = client.post(f"/api/tasks/{task_id}/grab", json={"assignee": "tester"})
    assert r.status_code == 200
    assert r.json()["task"]["status"] == "in-progress"
    assert r.json()["task"]["assignee"] == "tester"
    assert "story_context" in r.json()


def test_create_task_with_depends_on(client):
    story_id = _create_story(client)

    # Create first task
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Task A",
        "description": "first task",
        "points": 2,
    })
    assert r.status_code == 201
    task_a_id = r.json()["id"]

    # Create second task that depends on the first
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Task B",
        "description": "depends on A",
        "points": 2,
        "depends_on": [task_a_id],
    })
    assert r.status_code == 201
    task_b = r.json()
    assert task_b["depends_on"] == [task_a_id]

    # Verify via GET
    r = client.get(f"/api/tasks/{task_b['id']}")
    assert r.status_code == 200
    assert r.json()["depends_on"] == [task_a_id]


def test_update_task_depends_on(client):
    story_id = _create_story(client)

    # Create two tasks
    r1 = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Task A",
        "description": "first",
        "points": 2,
    })
    task_a_id = r1.json()["id"]

    r2 = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Task B",
        "description": "second",
        "points": 2,
    })
    task_b_id = r2.json()["id"]

    # Update Task B to depend on Task A
    r = client.patch(f"/api/tasks/{task_b_id}", json={"depends_on": [task_a_id]})
    assert r.status_code == 200
    assert r.json()["depends_on"] == [task_a_id]


def test_create_task_without_depends_on(client):
    story_id = _create_story(client)
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "No deps",
        "description": "no dependencies",
        "points": 1,
    })
    assert r.status_code == 201
    assert r.json()["depends_on"] == []


def test_task_response_schema_includes_depends_on():
    """TaskResponse schema must declare depends_on field."""
    from projectman.web.schemas import TaskResponse

    assert "depends_on" in TaskResponse.model_fields
    # Verify the field has the correct default and type
    field = TaskResponse.model_fields["depends_on"]
    assert field.default == []


def test_task_detail_response_includes_depends_on(client):
    """GET /api/tasks/{id} response includes depends_on."""
    story_id = _create_story(client)
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Detail deps test",
        "description": "check detail response",
        "points": 1,
    })
    task_id = r.json()["id"]

    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    data = r.json()
    assert "depends_on" in data
    assert data["depends_on"] == []


def test_grab_not_ready_task_returns_409(client):
    # Story in backlog = task not ready
    story_id = _create_story(client, status="backlog")
    r = client.post("/api/tasks", json={
        "story_id": story_id,
        "title": "Blocked",
        "description": "d",
    })
    task_id = r.json()["id"]

    r = client.post(f"/api/tasks/{task_id}/grab")
    assert r.status_code == 409


# ─── Board ───────────────────────────────────────────────────────


def test_board_returns_grouped_tasks(client):
    story_id = _create_story(client, status="active")
    client.post("/api/tasks", json={"story_id": story_id, "title": "T1", "description": "d"})

    r = client.get("/api/board")
    assert r.status_code == 200
    data = r.json()
    assert "board" in data
    assert "summary" in data
    assert data["summary"]["available"] + data["summary"]["not_ready"] >= 1


def test_burndown_returns_points(client):
    r = client.get("/api/burndown")
    assert r.status_code == 200
    data = r.json()
    assert "total_points" in data
    assert "completed_points" in data
    assert "completion" in data


def test_audit_returns_dict(client):
    r = client.get("/api/audit")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_search_returns_results(client):
    _create_story(client, "Searchable Story")

    r = client.get("/api/search?q=Searchable")
    assert r.status_code == 200
    results = r.json()
    assert len(results) >= 1
    assert any("Searchable" in item.get("title", "") for item in results)


def test_search_requires_query(client):
    r = client.get("/api/search")
    assert r.status_code == 422


# ─── Documentation ───────────────────────────────────────────────


def test_docs_summary(client):
    r = client.get("/api/docs")
    assert r.status_code == 200
    data = r.json()
    assert "project" in data
    assert data["project"]["status"] in ("current", "stale")


def test_doc_read(client):
    r = client.get("/api/docs/project")
    assert r.status_code == 200
    assert "# test-project" in r.json()["content"]


def test_doc_read_unknown_returns_404(client):
    r = client.get("/api/docs/nonexistent")
    assert r.status_code == 404


def test_doc_update(client):
    new_content = "# Updated\n\nNew content."
    r = client.put("/api/docs/project", json={"content": new_content})
    assert r.status_code == 200
    assert r.json()["updated"] == "PROJECT.md"

    # Verify content persisted
    r = client.get("/api/docs/project")
    assert r.json()["content"] == new_content
