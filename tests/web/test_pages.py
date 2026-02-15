"""Tests for HTML page routes."""


def test_dashboard_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ProjectMan" in r.text


def test_board_page(client):
    r = client.get("/board")
    assert r.status_code == 200
    assert "Board" in r.text


def test_epics_page(client):
    r = client.get("/epics")
    assert r.status_code == 200
    assert "Epics" in r.text


def test_stories_page(client):
    r = client.get("/stories")
    assert r.status_code == 200
    assert "Stories" in r.text


def test_docs_page(client):
    r = client.get("/project-docs")
    assert r.status_code == 200
    assert "Documentation" in r.text


def test_audit_page(client):
    r = client.get("/audit")
    assert r.status_code == 200
    assert "Audit" in r.text


def test_epic_detail_page(client):
    # Create an epic first
    r = client.post("/api/epics", json={"title": "E", "description": "d"})
    epic_id = r.json()["id"]

    r = client.get(f"/epics/{epic_id}")
    assert r.status_code == 200
    assert epic_id in r.text


def test_story_detail_page(client):
    r = client.post("/api/stories", json={"title": "S", "description": "d"})
    story_id = r.json()["id"]

    r = client.get(f"/stories/{story_id}")
    assert r.status_code == 200
    assert story_id in r.text


def test_task_detail_page(client):
    # Create story + task
    r = client.post("/api/stories", json={"title": "S", "description": "d"})
    story_id = r.json()["id"]
    client.patch(f"/api/stories/{story_id}", json={"status": "active"})

    r = client.post("/api/tasks", json={
        "story_id": story_id, "title": "T", "description": "d"
    })
    task_id = r.json()["id"]

    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200
    assert task_id in r.text
