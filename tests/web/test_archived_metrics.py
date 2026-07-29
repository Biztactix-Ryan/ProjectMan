"""The web dashboard must not report abandoned work as delivered (US-PM-16-2).

``/api/status`` and ``/api/burndown`` do not call the MCP tools — they carry
their own copy of the completion arithmetic in ``web/routes/api.py``.  The
shared piece is ``build_index``, and these tests pin that the routes keep
taking their numbers from it, so the browser view cannot drift away from what
``pm_status`` and ``pm_burndown`` report.

As elsewhere in US-PM-16, the half-fix under test is excluding archived work
from the denominator only; a genuinely done task is the control.

These tests use their own client fixture rather than the package one: the
shared fixture reaches ``get_store``'s ``from .app import app`` branch, which
raises ``ModuleNotFoundError`` on an unrelated pre-existing import bug in
``web/routes/api.py`` (the relative import resolves to
``projectman.web.routes.app``).  Overriding the dependency injects the same
``Store`` the shared fixture intends to supply, so the routes' arithmetic is
exercised for real without riding on that broken branch.
"""

from pathlib import Path
from unittest.mock import patch

import frontmatter
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client(tmp_project: Path):
    from projectman.store import Store, _cache
    from projectman.web.app import app
    from projectman.web.routes.api import get_store

    _cache.clear()
    store = Store(tmp_project)

    with (
        patch("projectman.web.routes.api.find_project_root", return_value=tmp_project),
        patch("projectman.config.find_project_root", return_value=tmp_project),
    ):
        app.state.root = tmp_project
        app.state.store = store
        app.dependency_overrides[get_store] = lambda: store
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_store, None)


def _project_with(client, *, delivered=0, outstanding=0, abandoned=0, abandoned_done=0):
    """Build a story whose tasks cover the requested shapes of work."""
    client.post("/api/stories", json={"title": "Story", "description": "Desc"})
    n = 0

    def _task(title, points):
        nonlocal n
        n += 1
        client.post(
            "/api/tasks",
            json={
                "story_id": "US-TST-1",
                "title": title,
                "description": "A" * 80,
                "points": points,
            },
        )
        return f"US-TST-1-{n}"

    ids = {}
    if delivered:
        ids["delivered"] = _task("Delivered", delivered)
        client.patch(f"/api/tasks/{ids['delivered']}", json={"status": "done"})
    if outstanding:
        ids["outstanding"] = _task("Outstanding", outstanding)
    if abandoned:
        ids["abandoned"] = _task("Abandoned", abandoned)
        client.delete(f"/api/tasks/{ids['abandoned']}")
    if abandoned_done:
        ids["abandoned_done"] = _task("Abandoned after done", abandoned_done)
        client.patch(f"/api/tasks/{ids['abandoned_done']}", json={"status": "done"})
        client.delete(f"/api/tasks/{ids['abandoned_done']}")
    return ids


# ─── /api/status ─────────────────────────────────────────────────


def test_status_completion_ignores_archived_work(client):
    _project_with(client, delivered=5, outstanding=3, abandoned=2, abandoned_done=8)

    data = client.get("/api/status").json()
    assert data["total_points"] == 8
    assert data["completed_points"] == 5
    assert data["completion"] == "62%"


def test_status_files_archived_work_under_archived_not_done(client):
    """An archived task keeps its last real status on disk, so the route has
    to consult the flag rather than the status to group it."""
    _project_with(client, delivered=5, abandoned_done=8)

    by_status = client.get("/api/status").json()["by_status"]
    assert by_status.get("done", 0) == 1  # the genuinely delivered one only
    assert by_status.get("archived") == 1


def test_status_counts_genuinely_done_work(client):
    _project_with(client, delivered=5, outstanding=3)

    data = client.get("/api/status").json()
    assert data["total_points"] == 8
    assert data["completed_points"] == 5
    assert data["completion"] == "62%"


def test_status_survives_a_wholly_archived_project(client):
    _project_with(client, abandoned=3, abandoned_done=5)

    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["total_points"] == 0
    assert data["completed_points"] == 0
    assert data["completion"] == "0%"


# ─── /api/burndown ───────────────────────────────────────────────


def test_burndown_excludes_archived_from_both_sides(client):
    _project_with(client, delivered=5, outstanding=3, abandoned=2, abandoned_done=8)

    data = client.get("/api/burndown").json()
    assert data["total_points"] == 8
    assert data["completed_points"] == 5
    assert data["remaining_points"] == 3
    assert data["remaining_points"] == data["total_points"] - data["completed_points"]
    assert data["completion"] == "62%"


def test_burndown_remaining_never_goes_negative(client):
    """Crediting archived-after-done work against a denominator it has left
    would report -8 points remaining here."""
    _project_with(client, delivered=5, outstanding=3, abandoned_done=8)

    data = client.get("/api/burndown").json()
    assert data["remaining_points"] >= 0
    assert data["completed_points"] <= data["total_points"]


def test_burndown_still_burns_down_real_delivery(client):
    _project_with(client, delivered=5, outstanding=3)

    data = client.get("/api/burndown").json()
    assert data["total_points"] == 8
    assert data["completed_points"] == 5
    assert data["remaining_points"] == 3


def test_burndown_survives_a_wholly_archived_project(client):
    _project_with(client, abandoned=3, abandoned_done=5)

    r = client.get("/api/burndown")
    assert r.status_code == 200
    data = r.json()
    assert data["total_points"] == 0
    assert data["completed_points"] == 0
    assert data["remaining_points"] == 0
    assert data["completion"] == "0%"


def test_status_and_burndown_routes_agree(client):
    _project_with(client, delivered=5, outstanding=3, abandoned=2, abandoned_done=8)

    status = client.get("/api/status").json()
    burndown = client.get("/api/burndown").json()
    assert status["total_points"] == burndown["total_points"]
    assert status["completed_points"] == burndown["completed_points"]
    assert status["completion"] == burndown["completion"]


# ─── DELETE /api/tasks/{id} — the dashboard's archive button ──────


@pytest.mark.parametrize("status", ["in-progress", "done"])
def test_archive_route_leaves_the_task_status_alone_on_disk(
    client, tmp_project, status
):
    """The browser archives over HTTP, not through ``pm_archive``.

    The routes above group by the ``archived`` flag, so they read the same
    either way — only the file on disk shows whether this route still rewrites
    ``status``.  ``done`` is the subtle case: it has to survive as genuinely
    reached work rather than being indistinguishable from a rewrite.
    """
    client.post("/api/stories", json={"title": "Story", "description": "Desc"})
    client.post(
        "/api/tasks",
        json={
            "story_id": "US-TST-1",
            "title": "Abandoned",
            "description": "A" * 80,
            "points": 2,
        },
    )
    client.patch("/api/tasks/US-TST-1-1", json={"status": status})

    assert client.delete("/api/tasks/US-TST-1-1").status_code == 200

    post = frontmatter.load(str(tmp_project / ".project" / "tasks" / "US-TST-1-1.md"))
    assert post.metadata["archived"] is True
    assert post.metadata["status"] == status
