"""The web create endpoints report coded errors, not 500s (US-PM-33).

Criterion under verification:

    POST create endpoints in the web API return 409 with the error code when
    the target ID already exists, and 422 on an invalid ID.

``Store.create_*`` refuses an occupied target with ``FileExistsError`` — the
contract ``tests/test_creates_never_overwrite.py`` pins — and the routes used
to catch nothing but ``FileNotFoundError``, so that refusal escaped as a 500.
Collisions are forced the same way that module forces them: the ID allocators
reconcile with disk since US-PM-24-5/-6, so they will not hand out a taken
number on their own, and the stub stands in for the case they cannot cover.

The invalid-ID half is not the store's answer: it only ever asks whether the
file exists, so a malformed ``story_id`` came back as "not found" alongside a
merely absent one.  The routes shape-check against ``models.py`` first, which
is what separates 422 from 404 here.
"""

import pytest

from projectman.models import EPIC_ID, STORY_ID


SENTINEL = "---\nid: SENTINEL\n---\nDo not overwrite me. Byte-exact.\n"


def _store():
    """The Store the app is serving (set by the ``client`` fixture)."""
    from projectman.web.app import app

    return app.state.store


def _make_story(client) -> str:
    r = client.post("/api/stories", json={"title": "Parent", "description": "body"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─── 409 on a taken target ID ────────────────────────────────────────


def test_create_epic_conflicts_with_an_existing_id(client, tmp_project, monkeypatch):
    target = tmp_project / ".project" / "epics" / "EPIC-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(_store(), "_next_epic_id", lambda: "EPIC-TST-77")

    r = client.post("/api/epics", json={"title": "Clobberer", "description": "d"})

    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "conflict"
    assert "EPIC-TST-77" in r.json()["detail"]["message"]
    assert target.read_text() == SENTINEL


def test_create_story_conflicts_with_an_existing_id(client, tmp_project, monkeypatch):
    target = tmp_project / ".project" / "stories" / "US-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(_store(), "_next_story_id", lambda: "US-TST-77")

    r = client.post("/api/stories", json={"title": "Clobberer", "description": "d"})

    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "conflict"
    assert "US-TST-77" in r.json()["detail"]["message"]
    assert target.read_text() == SENTINEL


def test_create_task_conflicts_with_an_existing_id(client, tmp_project, monkeypatch):
    story_id = _make_story(client)
    target = tmp_project / ".project" / "tasks" / f"{story_id}-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(_store(), "_next_task_id", lambda sid: f"{sid}-77")

    r = client.post(
        "/api/tasks",
        json={"story_id": story_id, "title": "Clobberer", "description": "d"},
    )

    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "conflict"
    assert target.read_text() == SENTINEL


# ─── 422 on a malformed ID ───────────────────────────────────────────


@pytest.mark.parametrize(
    "story_id",
    ["not-a-story", "us-tst-1", "US-TST", "US-TST-1-2", "", "EPIC-TST-1"],
)
def test_create_task_rejects_a_malformed_story_id(client, story_id):
    r = client.post(
        "/api/tasks",
        json={"story_id": story_id, "title": "T", "description": "d"},
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid"
    assert STORY_ID.pattern in r.json()["detail"]["message"]


def test_create_story_rejects_a_malformed_epic_id(client):
    r = client.post(
        "/api/stories",
        json={"title": "S", "description": "d", "epic_id": "not-an-epic"},
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid"
    assert EPIC_ID.pattern in r.json()["detail"]["message"]
    # Rejected before anything was written — no orphan story left behind.
    assert client.get("/api/stories").json() == []


# ─── the 404 path is unchanged ───────────────────────────────────────


def test_a_well_formed_but_absent_story_id_is_still_404(client):
    r = client.post(
        "/api/tasks",
        json={"story_id": "US-TST-99", "title": "T", "description": "d"},
    )

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Story not found: US-TST-99"


def test_creates_still_succeed(client):
    """The wrapper is transparent on the happy path."""
    story_id = _make_story(client)
    r = client.post(
        "/api/tasks",
        json={"story_id": story_id, "title": "T", "description": "d"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["story_id"] == story_id
