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
