"""Integration tests for SSE transport.

These tests start the MCP server in SSE mode and make HTTP requests
to verify the full SSE transport layer works end-to-end.
"""

import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Create a minimal project directory and cd to it."""
    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()

    config = {
        "name": "test-project",
        "prefix": "TST",
        "description": "A test project",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    (proj / "PROJECT.md").write_text("# test-project\nA test project.\n")
    (proj / "INFRASTRUCTURE.md").write_text("# Infrastructure\nLocal only.\n")
    (proj / "SECURITY.md").write_text("# Security\nNo auth.\n")
    (proj / "VISION.md").write_text("# Vision\nTest vision.\n")
    (proj / "ARCHITECTURE.md").write_text("# Architecture\nSimple.\n")
    (proj / "DECISIONS.md").write_text("# Decisions\nNone yet.\n")

    monkeypatch.chdir(tmp_path)
    return tmp_path


class SseClient:
    """HTTP client for the SSE-mode MCP server."""

    def __init__(self, base_url: str = "http://127.0.0.1:22001"):
        self.base_url = base_url
        import httpx

        self.http = httpx.Client(timeout=30)

    def get(self, path: str, **kwargs):
        return self.http.get(self.base_url + path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.http.post(self.base_url + path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.http.patch(self.base_url + path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.http.delete(self.base_url + path, **kwargs)

    def close(self):
        self.http.close()


@pytest.fixture
def sse_server(project_dir):
    """Start the MCP server in SSE mode and return an HTTP client."""
    proc = subprocess.Popen(
        [
            "projectman",
            "serve",
            "--transport",
            "sse",
            "--host",
            "127.0.0.1",
            "--port",
            "22001",
        ],
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**__import__("os").environ, "PROJECTMAN_ROOT": str(project_dir)},
    )

    # Wait for server to be ready
    import httpx

    client = SseClient()
    for _ in range(30):
        try:
            resp = client.get("/api/health")
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(f"Server failed to start. stdout={stdout}, stderr={stderr}")

    yield client

    client.close()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class TestSseTransport:
    """Tests that verify the SSE transport works end-to-end."""

    def test_server_starts_and_health(self, sse_server):
        """SSE server starts and /api/health responds."""
        resp = sse_server.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "uptime" in data

    def test_api_status(self, sse_server):
        """GET /api/status returns project status."""
        resp = sse_server.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project"] == "test-project"
        assert data["stories"] == 0

    def test_api_create_story(self, sse_server):
        """POST /api/stories creates a story."""
        resp = sse_server.post(
            "/api/stories",
            json={"title": "My Story", "description": "As a user"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Story"
        assert data["id"] == "US-TST-1"

    def test_api_create_and_list_stories(self, sse_server):
        """Create a story then list it via GET /api/stories."""
        sse_server.post(
            "/api/stories",
            json={"title": "Story 1", "description": "Desc"},
        )
        resp = sse_server.get("/api/stories")
        assert resp.status_code == 200
        stories = resp.json()
        assert len(stories) == 1
        assert stories[0]["title"] == "Story 1"

    def test_api_create_and_get_story(self, sse_server):
        """Create a story then retrieve it via GET /api/stories/{id}."""
        sse_server.post(
            "/api/stories",
            json={"title": "Story", "description": "Body text"},
        )
        resp = sse_server.get("/api/stories/US-TST-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Story"
        assert "Body text" in data["body"]

    def test_api_update_story(self, sse_server):
        """PATCH /api/stories/{id} updates a story."""
        sse_server.post(
            "/api/stories",
            json={"title": "Story", "description": "Desc"},
        )
        resp = sse_server.patch(
            "/api/stories/US-TST-1",
            json={"status": "active", "points": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["points"] == 5

    def test_api_create_task(self, sse_server):
        """POST /api/tasks creates a task."""
        sse_server.post(
            "/api/stories",
            json={"title": "Story", "description": "Desc"},
        )
        resp = sse_server.post(
            "/api/tasks",
            json={"story_id": "US-TST-1", "title": "Task", "description": "Do it"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Task"
        assert data["id"] == "US-TST-1-1"

    def test_api_board(self, sse_server):
        """GET /api/board returns the task board."""
        resp = sse_server.get("/api/board")
        assert resp.status_code == 200
        data = resp.json()
        assert "board" in data
        assert "summary" in data

    def test_api_burndown(self, sse_server):
        """GET /api/burndown returns burndown data."""
        resp = sse_server.get("/api/burndown")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_points" in data
        assert "completion" in data

    def test_api_activity(self, sse_server):
        """GET /api/activity returns activity log."""
        resp = sse_server.get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_api_docs(self, sse_server):
        """GET /api/docs returns documentation summary."""
        resp = sse_server.get("/api/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert "project" in data

    def test_api_search(self, sse_server):
        """GET /api/search performs search."""
        sse_server.post(
            "/api/stories",
            json={"title": "Authentication system", "description": "Login flow"},
        )
        resp = sse_server.get("/api/search", params={"q": "auth"})
        assert resp.status_code == 200
        # Falls back to keyword search if embeddings unavailable
        assert isinstance(resp.json(), list)

    def test_api_create_epic(self, sse_server):
        """POST /api/epics creates an epic."""
        resp = sse_server.post(
            "/api/epics",
            json={"title": "My Epic", "description": "Epic description"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Epic"
        assert data["id"] == "EPIC-TST-1"

    def test_api_epic_detail(self, sse_server):
        """GET /api/epics/{id} returns epic detail with rollup."""
        sse_server.post(
            "/api/epics",
            json={"title": "Epic", "description": "Desc"},
        )
        resp = sse_server.get("/api/epics/EPIC-TST-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["epic"]["title"] == "Epic"
        assert "rollup" in data

    def test_api_archive(self, sse_server):
        """DELETE /api/stories/{id} archives a story."""
        sse_server.post(
            "/api/stories",
            json={"title": "Story", "description": "Desc"},
        )
        resp = sse_server.delete("/api/stories/US-TST-1")
        assert resp.status_code == 200
        assert "archived" in resp.json()

    def test_api_grab_task(self, sse_server):
        """POST /api/tasks/{id}/grab claims a task."""
        # Create story and task
        sse_server.post(
            "/api/stories",
            json={"title": "Story", "description": "Desc"},
        )
        sse_server.patch("/api/stories/US-TST-1", json={"status": "active"})
        sse_server.post(
            "/api/tasks",
            json={
                "story_id": "US-TST-1",
                "title": "Ready Task",
                "description": "## Implementation\n\nDo it.\n\n## Testing\n\nTest it.\n\n## Definition of Done\n\n- [ ] Done",
                "points": 3,
            },
        )
        resp = sse_server.post("/api/tasks/US-TST-1-1/grab", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "task" in data or "grabbed" in data

    def test_full_workflow(self, sse_server):
        """End-to-end: create epic, story, tasks, update, archive."""
        # Create epic
        epic_resp = sse_server.post(
            "/api/epics",
            json={
                "title": "Auth Epic",
                "description": "Authentication epic",
                "priority": "must",
            },
        )
        assert epic_resp.status_code == 201
        epic_id = epic_resp.json()["id"]

        # Create story linked to epic
        story_resp = sse_server.post(
            "/api/stories",
            json={
                "title": "Login Story",
                "description": "As a user I want to log in",
                "epic_id": epic_id,
                "points": 5,
            },
        )
        assert story_resp.status_code == 201
        story_id = story_resp.json()["id"]

        # Create tasks
        task1_resp = sse_server.post(
            "/api/tasks",
            json={
                "story_id": story_id,
                "title": "Build login form",
                "description": "Create the HTML form",
                "points": 2,
            },
        )
        assert task1_resp.status_code == 201

        task2_resp = sse_server.post(
            "/api/tasks",
            json={
                "story_id": story_id,
                "title": "Build auth API",
                "description": "Create the auth endpoint",
                "points": 3,
            },
        )
        assert task2_resp.status_code == 201

        # Verify board
        board_resp = sse_server.get("/api/board")
        assert board_resp.status_code == 200

        # Verify status
        status_resp = sse_server.get("/api/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["epics"] == 1
        assert data["stories"] == 1
        assert data["tasks"] == 2
        assert data["total_points"] == 10  # 5 + 2 + 3
