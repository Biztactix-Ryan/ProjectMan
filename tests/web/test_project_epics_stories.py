"""Tests for project, epics, and stories API endpoints."""


def test_status_returns_project_info(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["project"] == "test-project"
    assert data["epics"] == 0
    assert data["stories"] == 0
    assert data["tasks"] == 0


def test_config_returns_project_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "test-project"
    assert data["prefix"] == "TST"
    assert data["hub"] is False


# ─── Epics CRUD ──────────────────────────────────────────────────


def test_epic_lifecycle(client):
    # Create
    r = client.post("/api/epics", json={
        "title": "Test Epic",
        "description": "An epic for testing",
        "priority": "must",
    })
    assert r.status_code == 201
    epic = r.json()
    assert epic["title"] == "Test Epic"
    epic_id = epic["id"]

    # List
    r = client.get("/api/epics")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Read detail
    r = client.get(f"/api/epics/{epic_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["epic"]["title"] == "Test Epic"
    assert data["rollup"]["story_count"] == 0

    # Update
    r = client.patch(f"/api/epics/{epic_id}", json={"status": "active"})
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    # Archive
    r = client.delete(f"/api/epics/{epic_id}")
    assert r.status_code == 200
    assert r.json()["archived"] == epic_id


def test_epic_not_found(client):
    r = client.get("/api/epics/EPIC-NOPE-99")
    assert r.status_code == 404


def test_epic_filter_by_status(client):
    client.post("/api/epics", json={"title": "E1", "description": "d"})
    client.post("/api/epics", json={"title": "E2", "description": "d"})

    # Both are "draft" by default
    r = client.get("/api/epics?status=draft")
    assert len(r.json()) == 2

    r = client.get("/api/epics?status=active")
    assert len(r.json()) == 0


# ─── Stories CRUD ────────────────────────────────────────────────


def test_story_lifecycle(client):
    # Create
    r = client.post("/api/stories", json={
        "title": "Test Story",
        "description": "A story for testing",
        "priority": "must",
        "points": 3,
    })
    assert r.status_code == 201
    story = r.json()
    assert story["title"] == "Test Story"
    assert story["points"] == 3
    story_id = story["id"]

    # List
    r = client.get("/api/stories")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Read detail
    r = client.get(f"/api/stories/{story_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Test Story"
    assert data["body"] == "A story for testing"
    assert data["tasks"] == []

    # Update
    r = client.patch(f"/api/stories/{story_id}", json={"status": "active"})
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    # Archive
    r = client.delete(f"/api/stories/{story_id}")
    assert r.status_code == 200


def test_story_not_found(client):
    r = client.get("/api/stories/US-NOPE-99")
    assert r.status_code == 404


def test_story_filter_by_status(client):
    client.post("/api/stories", json={"title": "S1", "description": "d"})
    r = client.get("/api/stories?status=backlog")
    assert len(r.json()) == 1

    r = client.get("/api/stories?status=active")
    assert len(r.json()) == 0


def test_story_with_epic_link(client):
    # Create epic first
    r = client.post("/api/epics", json={"title": "E", "description": "d"})
    epic_id = r.json()["id"]

    # Create story linked to epic
    r = client.post("/api/stories", json={
        "title": "S",
        "description": "d",
        "epic_id": epic_id,
    })
    assert r.status_code == 201
    assert r.json()["epic_id"] == epic_id

    # Epic detail should show the story
    r = client.get(f"/api/epics/{epic_id}")
    assert r.json()["rollup"]["story_count"] == 1


def test_invalid_points_returns_422(client):
    r = client.post("/api/stories", json={
        "title": "Bad Points",
        "description": "d",
        "points": 7,  # not fibonacci
    })
    assert r.status_code == 422
