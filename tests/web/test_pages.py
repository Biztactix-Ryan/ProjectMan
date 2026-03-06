"""Tests for HTML page routes."""

import json


def test_dashboard_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ProjectMan" in r.text


def test_dashboard_has_activity_feed(client):
    """Dashboard page includes the activity feed section."""
    r = client.get("/")
    assert r.status_code == 200
    assert "activity-feed" in r.text
    assert "Recent Activity" in r.text
    assert "activity-list" in r.text
    assert "/api/activity" in r.text


def test_activity_api_empty(client):
    """Activity API returns empty list when no log exists."""
    r = client.get("/api/activity")
    assert r.status_code == 200
    data = r.json()
    assert data["entries"] == []
    assert data["total"] == 0


def test_activity_api_returns_entries(client, tmp_project):
    """Activity API returns log entries from activity.jsonl."""
    from datetime import datetime, timezone

    proj_dir = tmp_project / ".project"
    entry = {
        "event_type": "create",
        "item_id": "US-TST-1",
        "item_type": "story",
        "changes": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": "test-user",
        "source": "web",
    }
    log_path = proj_dir / "activity.jsonl"
    log_path.write_text(json.dumps(entry) + "\n")

    r = client.get("/api/activity")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["entries"]) == 1
    assert data["entries"][0]["item_id"] == "US-TST-1"
    assert data["entries"][0]["event_type"] == "create"
    assert data["entries"][0]["actor"] == "test-user"


def test_activity_entries_show_event_icon_and_linked_item(client, tmp_project):
    """Entries show event type icon and item ID linked to detail view."""
    import json
    from datetime import datetime, timezone

    # -- Dashboard JS contains icon mapping for all event types --
    r = client.get("/")
    assert r.status_code == 200
    for event_type in ("create", "update", "delete", "archive"):
        assert event_type in r.text, f"Dashboard missing event type '{event_type}'"
    assert "EVENT_ICONS" in r.text

    # -- Dashboard JS contains link generation for each item type --
    assert "/stories/" in r.text
    assert "/tasks/" in r.text
    assert "/epics/" in r.text

    # -- API returns correct fields for icon + link rendering --
    proj_dir = tmp_project / ".project"
    log_path = proj_dir / "activity.jsonl"
    now = datetime.now(timezone.utc).isoformat()

    entries = [
        {
            "event_type": "create",
            "item_id": "US-TST-1",
            "item_type": "story",
            "changes": {},
            "timestamp": now,
            "actor": "alice",
            "source": "mcp",
        },
        {
            "event_type": "update",
            "item_id": "US-TST-1-1",
            "item_type": "task",
            "changes": {"status": ["todo", "in-progress"]},
            "timestamp": now,
            "actor": "bob",
            "source": "web",
        },
        {
            "event_type": "archive",
            "item_id": "EPIC-TST-1",
            "item_type": "epic",
            "changes": {},
            "timestamp": now,
            "actor": "carol",
            "source": "cli",
        },
    ]
    log_path.write_text("".join(json.dumps(e) + "\n" for e in entries))

    r = client.get("/api/activity")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3

    # Each entry has event_type (for icon) and item_id + item_type (for link)
    for entry in data["entries"]:
        assert "event_type" in entry
        assert "item_id" in entry
        assert "item_type" in entry
        assert entry["item_type"] in ("story", "task", "epic")

    # Verify specific entries by item_id
    by_id = {e["item_id"]: e for e in data["entries"]}
    assert by_id["US-TST-1"]["event_type"] == "create"
    assert by_id["US-TST-1"]["item_type"] == "story"
    assert by_id["US-TST-1-1"]["event_type"] == "update"
    assert by_id["US-TST-1-1"]["item_type"] == "task"
    assert by_id["EPIC-TST-1"]["event_type"] == "archive"
    assert by_id["EPIC-TST-1"]["item_type"] == "epic"


def test_activity_feed_loads_recent_entries_with_pagination(client, tmp_project):
    """Feed loads recent entries with scroll/pagination via limit & offset."""
    from datetime import datetime, timedelta, timezone

    proj_dir = tmp_project / ".project"
    log_path = proj_dir / "activity.jsonl"

    # Seed 15 entries with sequential timestamps
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lines = []
    for i in range(1, 16):
        entry = {
            "event_type": "create",
            "item_id": f"US-TST-{i}",
            "item_type": "story",
            "changes": {},
            "timestamp": (base + timedelta(hours=i)).isoformat(),
            "actor": "test-user",
            "source": "mcp",
        }
        lines.append(json.dumps(entry))
    log_path.write_text("\n".join(lines) + "\n")

    # -- Full load returns all 15 entries --
    r = client.get("/api/activity")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 15
    assert len(data["entries"]) == 15

    # -- Entries are newest-first --
    assert data["entries"][0]["item_id"] == "US-TST-15"
    assert data["entries"][-1]["item_id"] == "US-TST-1"

    # -- Page 1: limit=5 returns first 5 (newest) --
    r = client.get("/api/activity", params={"limit": 5, "offset": 0})
    page1 = r.json()
    assert page1["total"] == 15
    assert len(page1["entries"]) == 5
    assert page1["entries"][0]["item_id"] == "US-TST-15"
    assert page1["entries"][-1]["item_id"] == "US-TST-11"

    # -- Page 2: offset=5 returns next 5 --
    r = client.get("/api/activity", params={"limit": 5, "offset": 5})
    page2 = r.json()
    assert len(page2["entries"]) == 5
    assert page2["entries"][0]["item_id"] == "US-TST-10"
    assert page2["entries"][-1]["item_id"] == "US-TST-6"

    # -- Page 3: offset=10 returns last 5 --
    r = client.get("/api/activity", params={"limit": 5, "offset": 10})
    page3 = r.json()
    assert len(page3["entries"]) == 5
    assert page3["entries"][0]["item_id"] == "US-TST-5"
    assert page3["entries"][-1]["item_id"] == "US-TST-1"

    # -- No overlap between pages --
    ids1 = {e["item_id"] for e in page1["entries"]}
    ids2 = {e["item_id"] for e in page2["entries"]}
    ids3 = {e["item_id"] for e in page3["entries"]}
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)
    assert ids1 | ids2 | ids3 == {f"US-TST-{i}" for i in range(1, 16)}

    # -- Offset beyond total returns empty --
    r = client.get("/api/activity", params={"limit": 5, "offset": 20})
    beyond = r.json()
    assert beyond["total"] == 15
    assert len(beyond["entries"]) == 0


def test_activity_feed_displays_relative_timestamps(client):
    """Dashboard JS contains relativeTime function for human-friendly timestamps."""
    r = client.get("/")
    assert r.status_code == 200
    # The relativeTime helper function exists
    assert "relativeTime" in r.text
    # It produces relative labels like "minute ago", "hour ago", "day ago"
    assert "minute ago" in r.text
    assert "hour ago" in r.text
    assert "day ago" in r.text
    # Timestamps are rendered via relativeTime() not raw
    assert "relativeTime(e.timestamp)" in r.text
    # Timestamps have a title attribute with the original ISO value for hover
    assert "relative-time" in r.text


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


def test_stories_page_has_tag_input_and_tags_column(client):
    """stories.html has tag input in create form and tags column in table."""
    r = client.get("/stories")
    assert r.status_code == 200
    # Create form has a tags input with comma-separated placeholder
    assert 'name="tags"' in r.text
    assert 'placeholder="comma-separated"' in r.text
    # Table header includes Tags column
    assert "<th>Tags</th>" in r.text


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


def test_story_detail_displays_and_edits_tags(client):
    """story_detail.html displays and allows editing tags."""
    r = client.post("/api/stories", json={
        "title": "Tagged Story",
        "description": "story with tags",
        "tags": ["mvp", "backend"],
    })
    story_id = r.json()["id"]

    r = client.get(f"/stories/{story_id}")
    assert r.status_code == 200

    # Template JS renders tags as badges in detail-tags div
    assert "detail-tags" in r.text
    # Template has a tag editing form with input and update button
    assert 'id="story-tags"' in r.text
    assert "Update Tags" in r.text
    assert "updateStoryTags" in r.text

    # Verify tags can be updated via PATCH API
    r = client.patch(f"/api/stories/{story_id}", json={"tags": ["frontend", "urgent"]})
    assert r.status_code == 200
    assert r.json()["tags"] == ["frontend", "urgent"]

    # Verify updated tags persist
    r = client.get(f"/api/stories/{story_id}")
    assert r.status_code == 200
    assert r.json()["tags"] == ["frontend", "urgent"]


def test_task_detail_displays_and_edits_tags(client):
    """task_detail.html displays and allows editing tags."""
    # Create story + task with tags
    r = client.post("/api/stories", json={"title": "S", "description": "d"})
    story_id = r.json()["id"]
    client.patch(f"/api/stories/{story_id}", json={"status": "active"})

    r = client.post("/api/tasks", json={
        "story_id": story_id, "title": "Tagged Task",
        "description": "task with tags", "tags": ["mvp", "backend"],
    })
    task_id = r.json()["id"]

    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200

    # Template JS renders tags as badges in detail-tags div
    assert "detail-tags" in r.text
    # Template has a tag editing form with input and update button
    assert 'id="task-tags"' in r.text
    assert "Update Tags" in r.text
    assert "updateTaskTags" in r.text

    # Verify tags can be updated via PATCH API
    r = client.patch(f"/api/tasks/{task_id}", json={"tags": ["frontend", "urgent"]})
    assert r.status_code == 200
    assert r.json()["tags"] == ["frontend", "urgent"]

    # Verify updated tags persist
    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["tags"] == ["frontend", "urgent"]


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
