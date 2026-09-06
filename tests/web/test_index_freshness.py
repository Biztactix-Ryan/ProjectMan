"""The dashboard writes no indexes, and never reads a stale one.

Two halves of story US-PM-29 ("A write leaves only the item file and the
activity log dirty"), seen from the web app:

* the mutating ``/api/*`` routes used to call ``indexer.write_index`` after
  every create, update, archive and grab — ten sites — which is the same
  churn the MCP tools shed in US-PM-29-4;
* with those gone, the read routes carry the freshness check instead:
  ``/api/status`` and ``/api/burndown`` call ``indexer.ensure_fresh`` first,
  so a dashboard read that follows *any* write — through the web, through the
  MCP server, through a bare Store — reports the current numbers and leaves
  the derived files agreeing with the item files.

Timestamps are set with ``os.utime`` rather than waited for: a write and the
rebuild that preceded it can land inside one mtime tick, and the property
under test is an ordering of timestamps.
"""

import os
from pathlib import Path

import yaml

from projectman.indexer import write_index

INDEX_FILES = (
    "index.yaml",
    "INDEX.md",
    "INDEX-EPICS.md",
    "INDEX-STORIES.md",
    "INDEX-TASKS.md",
)


# ─── Helpers ──────────────────────────────────────────────────────


def _store(client):
    return client.app.state.store


def _project_dir(client) -> Path:
    return _store(client).project_dir


def _index_stamps(client) -> dict[str, tuple[bytes, int]]:
    return {
        name: (path.read_bytes(), path.stat().st_mtime_ns)
        for name in INDEX_FILES
        for path in [_project_dir(client) / name]
    }


def _index_data(client) -> dict:
    return yaml.safe_load((_project_dir(client) / "index.yaml").read_text())


def _index_ids(client) -> set[str]:
    return {entry["id"] for entry in _index_data(client)["entries"]}


def _seed_indexes(client) -> None:
    """Write the five derived files, as ``pm_reindex`` would have."""
    write_index(_store(client))


def _age_indexes(client, seconds: float = 10.0) -> None:
    """Backdate the derived files behind every item file.

    Makes the lag deterministic: without it a write landing in the same mtime
    tick as the seed rebuild would read as "written together", which
    ``ensure_fresh`` correctly treats as fresh.
    """
    store = _store(client)
    newest_ns = max(
        (
            p.stat().st_mtime_ns
            for directory in (store.epics_dir, store.stories_dir, store.tasks_dir)
            if directory.is_dir()
            for p in directory.glob("*.md")
        ),
        default=0,
    )
    when_ns = newest_ns - int(seconds * 1_000_000_000)
    for name in INDEX_FILES:
        path = _project_dir(client) / name
        if path.exists():
            os.utime(path, ns=(when_ns, when_ns))


def _create_story(client, **extra) -> str:
    payload = {"title": "A dashboard story", "description": "Written over HTTP."}
    payload.update(extra)
    r = client.post("/api/stories", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─── Writes no longer rebuild ─────────────────────────────────────


def test_creating_a_story_over_the_api_rewrites_no_index(client):
    _seed_indexes(client)
    before = _index_stamps(client)

    _create_story(client)

    assert _index_stamps(client) == before


def test_updating_a_task_over_the_api_rewrites_no_index(client):
    story_id = _create_story(client)
    r = client.post(
        "/api/tasks",
        json={
            "story_id": story_id,
            "title": "A task",
            "description": "Do the thing.",
            "points": 2,
        },
    )
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]
    _seed_indexes(client)
    before = _index_stamps(client)

    r = client.patch(f"/api/tasks/{task_id}", json={"status": "in-progress"})
    assert r.status_code == 200, r.text

    assert _index_stamps(client) == before


def test_archiving_a_story_over_the_api_rewrites_no_index(client):
    story_id = _create_story(client)
    _seed_indexes(client)
    before = _index_stamps(client)

    r = client.delete(f"/api/stories/{story_id}")
    assert r.status_code == 200, r.text

    assert _index_stamps(client) == before


# ─── Reads refresh a lagging index ────────────────────────────────


def test_status_reports_a_write_the_index_has_not_caught_up_with(client):
    _seed_indexes(client)
    story_id = _create_story(client)
    _age_indexes(client)
    assert story_id not in _index_ids(client), "precondition: the index lags"

    data = client.get("/api/status").json()

    assert data["stories"] == 1
    # And the file the dashboard derives from was brought up to date, so the
    # next reader of it — a human, a git diff, another process — agrees.
    assert story_id in _index_ids(client)


def test_status_catches_up_with_a_write_made_outside_the_web_app(client):
    """The write need not have come through the dashboard at all."""
    _seed_indexes(client)
    store = _store(client)
    story, _ = store.create_story("Written by the Store", "Not over HTTP.\n")
    _age_indexes(client)

    data = client.get("/api/status").json()

    assert data["stories"] == 1
    assert story.id in _index_ids(client)


def test_burndown_refreshes_an_index_left_behind_by_a_write(client):
    _seed_indexes(client)
    _create_story(client, points=5)
    _age_indexes(client)
    assert _index_data(client)["total_points"] == 0, "precondition: the index lags"

    data = client.get("/api/burndown").json()

    assert data["total_points"] == 5
    assert data["remaining_points"] == 5
    assert _index_data(client)["total_points"] == 5


def test_a_read_of_a_current_index_rewrites_nothing(client):
    """``ensure_fresh`` is a stat, not a rebuild, when nothing has changed.

    Otherwise every dashboard poll would dirty five files, which is the churn
    this story removed from the write path.
    """
    _seed_indexes(client)
    _create_story(client)
    _age_indexes(client)

    assert client.get("/api/status").status_code == 200
    after_first_read = _index_stamps(client)
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/burndown").status_code == 200

    assert _index_stamps(client) == after_first_read
