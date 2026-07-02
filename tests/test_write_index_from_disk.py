"""Tests for write_index always reading from disk (BUG 2 fix)."""

import pytest
import time

from projectman.indexer import write_index, build_index
from projectman.store import Store, _cache, clear_all_caches


class TestWriteIndexReadsFromDisk:
    """write_index must always read from disk, not from cache."""

    def test_write_index_ignores_stale_cache(self, store):
        """write_index builds index from disk even when cache is stale."""
        store.create_story("Story 1", "Desc", points=3)
        store.list_stories()  # populate cache

        # Externally add Story 2
        (store.stories_dir / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\ntitle: External Story\nstatus: backlog\npriority: should\npoints: 5\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        # Verify cache is stale
        assert store._is_cache_stale("stories") is True

        # write_index should include the externally-added story
        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        entry_ids = [e["id"] for e in index_data["entries"]]
        assert "US-TST-1" in entry_ids
        assert "US-TST-2" in entry_ids
        assert index_data["total_points"] == 8  # 3 + 5

    def test_write_index_ignores_stale_cache_for_tasks(self, store):
        """write_index includes externally-added tasks even when cache is stale."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc", points=2)
        store.list_tasks()  # populate cache

        # Externally add Task 2 (points must be a valid Fibonacci value)
        (store.tasks_dir / "US-TST-1-2.md").write_text(
            "---\nid: US-TST-1-2\nstory_id: US-TST-1\ntitle: External Task\nstatus: todo\npoints: 8\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        entry_ids = [e["id"] for e in index_data["entries"]]
        assert "US-TST-1-1" in entry_ids
        assert "US-TST-1-2" in entry_ids
        # Points: task1=2, task2=8, story=0
        assert index_data["total_points"] == 10

    def test_write_index_ignores_stale_cache_for_epics(self, store):
        """write_index includes externally-added epics even when cache is stale."""
        store.create_epic("Epic 1", "Desc")
        store.list_epics()  # populate cache

        # Externally add Epic 2
        (store.epics_dir / "EPIC-TST-2.md").write_text(
            "---\nid: EPIC-TST-2\ntitle: External Epic\nstatus: draft\npriority: must\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        entry_ids = [e["id"] for e in index_data["entries"]]
        assert "EPIC-TST-1" in entry_ids
        assert "EPIC-TST-2" in entry_ids

    def test_write_index_reflects_external_file_deletion(self, store):
        """write_index does not include externally-deleted items."""
        store.create_story("Story 1", "Desc", points=3)
        store.create_story("Story 2", "Desc", points=5)
        store.list_stories()  # populate cache

        # Externally delete Story 2
        (store.stories_dir / "US-TST-2.md").unlink()

        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        entry_ids = [e["id"] for e in index_data["entries"]]
        assert "US-TST-1" in entry_ids
        assert "US-TST-2" not in entry_ids
        assert index_data["total_points"] == 3

    def test_write_index_reflects_external_status_change(self, store):
        """write_index picks up externally-changed status fields."""
        store.create_story("Story", "Desc", points=5)
        store.list_stories()  # populate cache

        # Externally change status to done
        story_path = store.stories_dir / "US-TST-1.md"
        content = story_path.read_text().replace("status: backlog", "status: done")
        story_path.write_text(content)

        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        # Story should now be done and points should count as completed
        story_entry = next(e for e in index_data["entries"] if e["id"] == "US-TST-1")
        assert story_entry["status"] == "done"
        assert index_data["completed_points"] == 5

    def test_write_index_does_not_use_cache_for_counting(self, store):
        """write_index counts all items on disk, not just cached items."""
        store.create_story("Story 1", "Desc", points=3)
        store.create_story("Story 2", "Desc", points=5)
        # Only populate cache with Story 1 (don't call list_stories yet)
        # But we can populate by reading just one
        story1 = store.get_story("US-TST-1")
        assert story1[0].id == "US-TST-1"

        # Externally add Story 3 (won't be in cache)
        (store.stories_dir / "US-TST-3.md").write_text(
            "---\nid: US-TST-3\ntitle: External Story\nstatus: backlog\npriority: should\npoints: 8\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        # write_index should still pick up all 3 stories
        write_index(store)

        import yaml

        index_path = store.project_dir / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())

        assert index_data["story_count"] == 3
        assert index_data["total_points"] == 16  # 3 + 5 + 8


class TestReadTasksFromDisk:
    """_read_tasks_from_disk always reads from disk, bypassing cache."""

    def test_read_tasks_from_disk_returns_all_tasks(self, store):
        """_read_tasks_from_disk returns all tasks in directory."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.create_task("US-TST-1", "Task 2", "Desc")

        entries = store._read_tasks_from_disk()
        assert len(entries) == 2

    def test_read_tasks_from_disk_filters_by_story_id(self, store):
        """_read_tasks_from_disk can filter by story_id."""
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-2", "Task B", "Desc")

        entries = store._read_tasks_from_disk(story_id="US-TST-1")
        assert len(entries) == 1
        assert entries[0][0].id == "US-TST-1-1"

    def test_read_tasks_from_disk_filters_by_status(self, store):
        """_read_tasks_from_disk can filter by status."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.create_task("US-TST-1", "Task 2", "Desc")
        store.update("US-TST-1-1", status="in-progress")

        entries = store._read_tasks_from_disk(status_filter="in-progress")
        assert len(entries) == 1
        assert entries[0][0].id == "US-TST-1-1"

    def test_read_tasks_from_disk_bypasses_cache(self, store):
        """_read_tasks_from_disk does not use cache at all."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.list_tasks()  # populate cache

        # Externally add a task
        (store.tasks_dir / "US-TST-1-2.md").write_text(
            "---\nid: US-TST-1-2\nstory_id: US-TST-1\ntitle: External Task\nstatus: todo\npoints: null\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        # _read_tasks_from_disk should see both tasks
        entries = store._read_tasks_from_disk(story_id="US-TST-1")
        assert len(entries) == 2
