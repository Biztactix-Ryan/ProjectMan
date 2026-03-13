"""Tests for the orchestrator REST API and SSE event stream."""

import asyncio
import json
import pytest
import time

from projectman.event_bus import EventBus, NoOpEventBus


# ── EventBus tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    bus = EventBus()
    queue = bus.subscribe()
    await bus.publish("task.created", {"taskId": "T-1"})
    event = queue.get_nowait()
    assert event.type == "task.created"
    assert event.data == {"taskId": "T-1"}
    assert event.id == 1


@pytest.mark.asyncio
async def test_event_bus_increments_ids():
    bus = EventBus()
    queue = bus.subscribe()
    await bus.publish("a", {})
    await bus.publish("b", {})
    e1 = queue.get_nowait()
    e2 = queue.get_nowait()
    assert e1.id == 1
    assert e2.id == 2


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.publish("x", {"v": 1})
    assert q1.get_nowait().type == "x"
    assert q2.get_nowait().type == "x"


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    await bus.publish("x", {})
    assert queue.empty()


@pytest.mark.asyncio
async def test_noop_event_bus():
    bus = NoOpEventBus()
    await bus.publish("x", {"a": 1})  # should not raise
    assert bus.subscribe() is None
    bus.unsubscribe(None)  # should not raise


@pytest.mark.asyncio
async def test_event_bus_drops_on_full_queue():
    bus = EventBus()
    queue = bus.subscribe()
    # Fill the queue (maxsize=256)
    for i in range(256):
        await bus.publish("fill", {"i": i})
    # This should not raise — event is silently dropped
    await bus.publish("overflow", {})
    assert queue.qsize() == 256


# ── Orchestrator API endpoint tests ────────────────────────────

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project structure for testing."""
    from projectman.store import Store

    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()
    config = {
        "name": "test-project",
        "prefix": "TST",
        "description": "Test",
    }
    import yaml
    (proj / "config.yaml").write_text(yaml.dump(config))

    store = Store(tmp_path)
    store.create_story("Story One", "A test story")
    store.create_task("US-TST-1", "Task A", "Do thing A")
    store.create_task("US-TST-1", "Task B", "Do thing B")
    store.update("US-TST-1-1", status="in-progress")

    return tmp_path, store


@pytest.fixture
def api_client(tmp_project):
    """Set up a Starlette test client with the orchestrator routes."""
    from unittest.mock import patch
    from mcp.server.fastmcp import FastMCP
    from starlette.testclient import TestClient

    tmp_path, store = tmp_project
    test_mcp = FastMCP("test")
    event_bus = EventBus()

    from projectman.orchestrator_api import register_routes
    register_routes(test_mcp, event_bus, lambda: store)

    app = test_mcp.sse_app()
    client = TestClient(app)
    return client, event_bus, store


def test_api_health(api_client):
    client, _, store = api_client
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["projectId"] == "test-project"
    assert "uptime" in data


def test_api_project(api_client):
    client, _, _ = api_client
    resp = client.get("/api/project")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "test-project"
    assert data["stories"] >= 1
    assert data["tasks"] >= 2


def test_api_tasks_current(api_client):
    client, _, _ = api_client
    resp = client.get("/api/tasks/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is not None
    assert data["active"]["id"] == "US-TST-1-1"
    assert isinstance(data["queued"], list)


def test_api_task_detail(api_client):
    client, _, _ = api_client
    resp = client.get("/api/tasks/US-TST-1-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "US-TST-1-1"
    assert "body" in data


def test_api_task_not_found(api_client):
    client, _, _ = api_client
    resp = client.get("/api/tasks/US-TST-99-99")
    assert resp.status_code == 404


def test_events_endpoint_registered(api_client):
    """Verify the /events SSE endpoint is registered and routable."""
    client, event_bus, _ = api_client

    # The SSE endpoint is a long-lived stream, so we can't easily test it
    # with a synchronous test client. Instead, verify it's registered by
    # checking the app's routes.
    app = client.app
    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/events" in route_paths


@pytest.mark.asyncio
async def test_event_bus_event_format():
    """Verify event fields match what SSE endpoint would serialize."""
    bus = EventBus()
    queue = bus.subscribe()
    await bus.publish("task.created", {"taskId": "T-1", "storyId": "S-1", "title": "Test"})
    event = queue.get_nowait()
    assert event.id == 1
    assert event.type == "task.created"
    assert event.data["taskId"] == "T-1"
    assert event.timestamp > 0
