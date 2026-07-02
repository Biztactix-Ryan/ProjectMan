"""Tests for cache staleness detection (BUG 1 fix)."""

import pytest
import time

from projectman.store import Store, _cache, _cache_mtimes, clear_all_caches


class TestCacheStaleness:
    """Tests for mtime-based cache staleness detection."""

    def test_is_cache_stale_returns_false_when_fresh(self, store):
        """Newly populated cache is not stale."""
        store.create_story("Story", "Desc")
        store.list_stories()  # populate cache
        assert store._is_cache_stale("stories") is False

    def test_is_cache_stale_returns_true_when_dir_does_not_exist(self, store):
        """Cache is considered stale if the directory doesn't exist yet."""
        # Cache not populated, should return True
        assert store._is_cache_stale("stories") is True

    def test_is_cache_stale_detects_new_file_in_empty_dir(self, store):
        """Cache becomes stale when a new file appears in an empty directory."""
        store.create_story("Story", "Desc")
        store.list_stories()  # populate cache with 1 story
        mtime = _cache_mtimes.get(store._cache_key("stories"))
        assert mtime is not None

        # Simulate external file creation by touching a new file
        (store.stories_dir / "EXTERNAL-1.md").write_text(
            "---\nid: EXTERNAL-1\ntitle: External\nstatus: backlog\npriority: should\npoints: null\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nExternal story\n"
        )
        assert store._is_cache_stale("stories") is True

    def test_is_cache_stale_detects_modified_file(self, store):
        """Cache becomes stale when an existing file is modified externally."""
        store.create_story("Story", "Desc")
        store.list_stories()  # populate cache

        # Simulate external modification by updating file mtime
        story_path = store.stories_dir / "US-TST-1.md"
        time.sleep(0.01)  # ensure mtime differs
        story_path.touch()
        assert store._is_cache_stale("stories") is True

    def test_is_cache_stale_returns_false_for_untracked_item_type(self, store):
        """Unknown item types are considered stale (safe default)."""
        store.list_stories()
        assert store._is_cache_stale("unknown") is True

    def test_get_dir_mtime_returns_zero_for_missing_dir(self, store):
        """_get_dir_mtime returns (0.0, 0) for non-existent directory."""
        # Create store without creating the stories dir via create_story
        assert store._get_dir_mtime(store.stories_dir) == (0.0, 0)

    def test_get_dir_mtime_returns_max_of_files(self, store):
        """_get_dir_mtime returns the newest file's mtime and file count."""
        store.create_story("Story 1", "Desc")
        time.sleep(0.01)
        store.create_story("Story 2", "Desc")
        mtime, count = store._get_dir_mtime(store.stories_dir)
        newest = max(f.stat().st_mtime for f in store.stories_dir.glob("*.md"))
        assert mtime == newest
        assert count == 2

    def test_cache_mtimes_updated_on_list_stories(self, store):
        """_cache_mtimes is populated when list_stories populates cache."""
        store.create_story("Story", "Desc")
        store.list_stories()
        key = store._cache_key("stories")
        assert key in _cache_mtimes
        assert _cache_mtimes[key][0] > 0

    def test_cache_mtimes_updated_on_list_epics(self, store):
        """_cache_mtimes is populated when list_epics populates cache."""
        store.create_epic("Epic", "Desc")
        store.list_epics()
        key = store._cache_key("epics")
        assert key in _cache_mtimes
        assert _cache_mtimes[key][0] > 0

    def test_cache_mtimes_updated_on_list_tasks(self, store):
        """_cache_mtimes is populated when list_tasks populates cache."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.list_tasks()
        key = store._cache_key("tasks")
        assert key in _cache_mtimes
        assert _cache_mtimes[key][0] > 0


class TestCacheStalenessIntegration:
    """Staleness causes list/get to re-read from disk."""

    def test_list_stories_repopulates_on_stale_cache(self, store):
        """list_stories re-reads from disk when cache is stale."""
        store.create_story("Story", "Desc")
        store.list_stories()  # populate

        # Externally add a new story
        (store.stories_dir / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\ntitle: External Story\nstatus: backlog\npriority: should\npoints: null\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        # Cache should be stale now
        assert store._is_cache_stale("stories") is True

        # list_stories should re-read and include the external story
        stories = store.list_stories()
        titles = [s.title for s in stories]
        assert "External Story" in titles

    def test_list_tasks_repopulates_on_stale_cache(self, store):
        """list_tasks re-reads from disk when cache is stale."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.list_tasks()  # populate

        # Externally add a new task
        (store.tasks_dir / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\nstory_id: US-TST-1\ntitle: External Task\nstatus: todo\npoints: null\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
        )

        tasks = store.list_tasks()
        titles = [t.title for t in tasks]
        assert "External Task" in titles

    def test_get_story_re_reads_from_disk_when_stale(self, store):
        """get_story bypasses stale cache and reads from disk."""
        store.create_story("Story", "Original")
        store.list_stories()  # populate cache

        # Externally modify the story
        story_path = store.stories_dir / "US-TST-1.md"
        content = story_path.read_text().replace("Original", "Modified Exterally")
        story_path.write_text(content)
        time.sleep(0.01)
        story_path.touch()

        assert store._is_cache_stale("stories") is True

        # get_story should return the modified content
        _, body = store.get_story("US-TST-1")
        assert body == "Modified Exterally"

    def test_get_task_re_reads_from_disk_when_stale(self, store):
        """get_task bypasses stale cache and reads from disk."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Original body")
        store.list_tasks()  # populate cache

        # Externally modify the task
        task_path = store.tasks_dir / "US-TST-1-1.md"
        content = task_path.read_text().replace("Original body", "Modified externally")
        task_path.write_text(content)
        time.sleep(0.01)
        task_path.touch()

        assert store._is_cache_stale("tasks") is True

        _, body = store.get_task("US-TST-1-1")
        assert body == "Modified externally"

    def test_get_epic_re_reads_from_disk_when_stale(self, store):
        """get_epic bypasses stale cache and reads from disk."""
        store.create_epic("Epic", "Original desc")
        store.list_epics()  # populate cache

        # Externally modify
        epic_path = store.epics_dir / "EPIC-TST-1.md"
        content = epic_path.read_text().replace("Original desc", "Modified externally")
        epic_path.write_text(content)
        time.sleep(0.01)
        epic_path.touch()

        assert store._is_cache_stale("epics") is True

        _, body = store.get_epic("EPIC-TST-1")
        assert body == "Modified externally"


class TestClearAllCachesClearsMtimes:
    """clear_all_caches also clears _cache_mtimes."""

    def test_clear_all_caches_clears_mtimes(self, store):
        """clear_all_caches resets _cache_mtimes along with _cache."""
        store.create_story("Story", "Desc")
        store.list_stories()
        assert len(_cache_mtimes) > 0

        clear_all_caches()
        assert len(_cache_mtimes) == 0
