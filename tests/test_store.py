"""Tests for Store CRUD operations."""

import pytest
from pydantic import ValidationError

from projectman.models import TASK_ID
from projectman.store import Store, clear_all_caches, get_cache_stats, _cache, _cache_stats, _cache_debug
import projectman.store as store_module


class TestStoreStories:
    def test_create_story(self, store):
        meta, test_tasks = store.create_story("My Story", "As a user, I want things")
        assert meta.id == "US-TST-1"
        assert meta.title == "My Story"
        assert test_tasks == []

    def test_create_story_with_options(self, store):
        meta, _ = store.create_story(
            "Story", "Description",
            priority="must", points=5, tags=["backend"]
        )
        assert meta.priority.value == "must"
        assert meta.points == 5
        assert meta.tags == ["backend"]

    def test_create_story_tags_persisted_on_disk(self, store):
        """Tags passed to create_story are written to frontmatter and survive a round-trip."""
        store.create_story(
            "Tagged Story", "Description",
            tags=["security", "mvp", "backend"],
        )
        meta, _ = store.get_story("US-TST-1")
        assert meta.tags == ["security", "mvp", "backend"]

    def test_get_story(self, store):
        store.create_story("My Story", "Body text here")
        meta, body = store.get_story("US-TST-1")
        assert meta.title == "My Story"
        assert "Body text here" in body

    def test_get_story_not_found(self, store):
        with pytest.raises(FileNotFoundError):
            store.get_story("TST-999")

    def test_list_stories(self, store):
        store.create_story("Story 1", "Desc 1")
        store.create_story("Story 2", "Desc 2")
        stories = store.list_stories()
        assert len(stories) == 2

    def test_list_stories_filter_status(self, store):
        store.create_story("Story 1", "Desc 1")
        stories = store.list_stories(status="backlog")
        assert len(stories) == 1
        stories = store.list_stories(status="active")
        assert len(stories) == 0

    def test_sequential_ids(self, store):
        s1, _ = store.create_story("First", "Desc")
        s2, _ = store.create_story("Second", "Desc")
        assert s1.id == "US-TST-1"
        assert s2.id == "US-TST-2"


class TestStoreAcceptanceCriteria:
    def test_create_story_with_acceptance_criteria(self, store):
        meta, test_tasks = store.create_story(
            "Story with ACs",
            "Description",
            acceptance_criteria=["Users can log in", "Error shown on invalid password"],
        )
        assert meta.acceptance_criteria == ["Users can log in", "Error shown on invalid password"]
        assert len(test_tasks) == 2
        assert test_tasks[0].title == "Test: Users can log in"
        assert test_tasks[1].title == "Test: Error shown on invalid password"
        # Verify tasks exist on disk
        tasks = store.list_tasks(story_id=meta.id)
        assert len(tasks) == 2

    def test_create_story_no_acceptance_criteria(self, store):
        meta, test_tasks = store.create_story("Story", "Desc")
        assert meta.acceptance_criteria == []
        assert test_tasks == []
        tasks = store.list_tasks(story_id=meta.id)
        assert len(tasks) == 0

    def test_create_story_empty_acceptance_criteria(self, store):
        meta, test_tasks = store.create_story("Story", "Desc", acceptance_criteria=[])
        assert meta.acceptance_criteria == []
        assert test_tasks == []

    def test_test_task_description_references_story(self, store):
        meta, test_tasks = store.create_story(
            "Story", "Desc",
            acceptance_criteria=["Feature works"],
        )
        _, task_body = store.get_task(test_tasks[0].id)
        assert meta.id in task_body
        assert "Feature works" in task_body

    def test_test_task_has_no_points(self, store):
        _, test_tasks = store.create_story(
            "Story", "Desc",
            acceptance_criteria=["Feature works"],
        )
        assert test_tasks[0].points is None

    def test_acceptance_criteria_persisted_on_disk(self, store):
        store.create_story(
            "Story", "Desc",
            acceptance_criteria=["AC one", "AC two"],
        )
        meta, _ = store.get_story("US-TST-1")
        assert meta.acceptance_criteria == ["AC one", "AC two"]


class TestStoreTasks:
    def test_create_task(self, store):
        store.create_story("Story", "Desc")
        task = store.create_task("US-TST-1", "Task 1", "Do something")
        assert task.id == "US-TST-1-1"
        assert task.story_id == "US-TST-1"

    def test_create_task_tags_persisted_on_disk(self, store):
        """Tags passed to create_task are written to frontmatter and survive a round-trip."""
        store.create_story("Story", "Desc")
        task = store.create_task(
            "US-TST-1", "Tagged Task", "Do something",
            tags=["backend", "urgent"],
        )
        assert task.tags == ["backend", "urgent"]
        # Round-trip: re-read from disk
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.tags == ["backend", "urgent"]

    def test_create_tasks_tags_persisted_on_disk(self, store):
        """Tags passed via create_tasks entries are written to frontmatter and survive a round-trip."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "Desc A", "tags": ["security"]},
            {"title": "Task B", "description": "Desc B", "tags": ["mvp", "frontend"]},
            {"title": "Task C", "description": "Desc C"},  # no tags
        ])
        assert results[0].tags == ["security"]
        assert results[1].tags == ["mvp", "frontend"]
        assert results[2].tags == []
        # Round-trip: re-read from disk
        meta_a, _ = store.get_task("US-TST-1-1")
        assert meta_a.tags == ["security"]
        meta_b, _ = store.get_task("US-TST-1-2")
        assert meta_b.tags == ["mvp", "frontend"]
        meta_c, _ = store.get_task("US-TST-1-3")
        assert meta_c.tags == []

    def test_create_task_no_story(self, store):
        with pytest.raises(FileNotFoundError):
            store.create_task("TST-999", "Task", "Desc")

    def test_get_task(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Task body")
        meta, body = store.get_task("US-TST-1-1")
        assert meta.title == "Task 1"
        assert "Task body" in body

    def test_list_tasks_by_story(self, store):
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-1", "Task B", "Desc")
        store.create_task("US-TST-2", "Task C", "Desc")

        tasks = store.list_tasks(story_id="US-TST-1")
        assert len(tasks) == 2
        tasks = store.list_tasks(story_id="US-TST-2")
        assert len(tasks) == 1


class TestStoreUpdate:
    def test_update_story(self, store):
        store.create_story("Story", "Desc")
        updated = store.update("US-TST-1", status="active")
        assert updated.status.value == "active"

    def test_update_task(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        updated = store.update("US-TST-1-1", status="in-progress", assignee="alice")
        assert updated.status.value == "in-progress"
        assert updated.assignee == "alice"

    def test_update_not_found(self, store):
        with pytest.raises(FileNotFoundError):
            store.update("TST-999", status="active")

    def test_archive_story(self, store):
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        meta, _ = store.get_story("US-TST-1")
        assert meta.status.value == "archived"

    def test_archive_task(self, store):
        """Archiving a task sets ``archived``; it must not claim the task is done."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.archived is True
        assert meta.status.value == "todo"

    def test_update_body(self, store):
        store.create_story("Story", "Original body")
        store.update("US-TST-1", body="Updated body content")
        _, body = store.get_story("US-TST-1")
        assert body == "Updated body content"

    def test_update_body_preserves_frontmatter(self, store):
        store.create_story("Story", "Original", priority="must", points=5)
        store.update("US-TST-1", body="New body")
        meta, body = store.get_story("US-TST-1")
        assert body == "New body"
        assert meta.priority.value == "must"
        assert meta.points == 5

    def test_update_body_and_fields(self, store):
        store.create_story("Story", "Original")
        store.update("US-TST-1", body="New body", status="active")
        meta, body = store.get_story("US-TST-1")
        assert body == "New body"
        assert meta.status.value == "active"

    def test_update_acceptance_criteria(self, store):
        store.create_story("Story", "Desc")
        store.update("US-TST-1", acceptance_criteria=["AC one", "AC two"])
        meta, _ = store.get_story("US-TST-1")
        assert meta.acceptance_criteria == ["AC one", "AC two"]


class TestStoreGet:
    def test_get_story_by_id(self, store):
        store.create_story("Story", "Desc")
        meta, body = store.get("US-TST-1")
        assert meta.title == "Story"

    def test_get_task_by_id(self, store):
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        meta, body = store.get("US-TST-1-1")
        assert meta.title == "Task"


class TestStoreBackwardCompatibility:
    def test_task_without_tags_loads(self, store):
        """Existing task files without a tags field still load without errors."""
        store.create_story("Story", "Desc")
        # Write a task file manually WITHOUT the tags field (pre-tags format)
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "A task created before tags existed.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        # Should load without error
        meta, body = store.get_task("US-TST-1-1")
        assert meta.id == "US-TST-1-1"
        assert meta.title == "Legacy task"
        assert meta.tags == []
        assert "before tags existed" in body

    def test_task_without_tags_appears_in_list(self, store):
        """Legacy task files without tags appear in list_tasks."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "Legacy body.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        tasks = store.list_tasks(story_id="US-TST-1")
        assert len(tasks) == 1
        assert tasks[0].tags == []

    def test_task_without_tags_can_be_updated(self, store):
        """Legacy task files without tags can be updated without errors."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "Legacy body.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        updated = store.update("US-TST-1-1", status="in-progress")
        assert updated.status.value == "in-progress"
        assert updated.tags == []

    def test_task_without_depends_on_loads(self, store):
        """Existing task files without a depends_on field still load without errors."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "tags: []\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "A task created before depends_on existed.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        meta, body = store.get_task("US-TST-1-1")
        assert meta.id == "US-TST-1-1"
        assert meta.depends_on == []
        assert "before depends_on existed" in body

    def test_task_without_depends_on_appears_in_list(self, store):
        """Legacy task files without depends_on appear in list_tasks."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "tags: []\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "Legacy body.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        tasks = store.list_tasks(story_id="US-TST-1")
        assert len(tasks) == 1
        assert tasks[0].depends_on == []

    def test_task_without_depends_on_can_be_updated(self, store):
        """Legacy task files without depends_on can be updated without errors."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Legacy task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "tags: []\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "Legacy body.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        updated = store.update("US-TST-1-1", status="in-progress")
        assert updated.status.value == "in-progress"
        assert updated.depends_on == []

    def test_task_without_tags_or_depends_on_loads(self, store):
        """Task files missing both tags and depends_on still load correctly."""
        store.create_story("Story", "Desc")
        task_content = (
            "---\n"
            "id: US-TST-1-1\n"
            "story_id: US-TST-1\n"
            "title: Very old task\n"
            "status: todo\n"
            "points: null\n"
            "assignee: null\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "A task from before tags and depends_on existed.\n"
        )
        (store.tasks_dir / "US-TST-1-1.md").write_text(task_content)

        meta, body = store.get_task("US-TST-1-1")
        assert meta.tags == []
        assert meta.depends_on == []


class TestCreateTaskDependsOn:
    """Tests for create_task depends_on parameter and validation."""

    def test_create_task_with_depends_on(self, store):
        """create_task accepts depends_on and persists it to frontmatter."""
        store.create_story("Story", "Desc")
        t1 = store.create_task("US-TST-1", "Task 1", "Desc")
        t2 = store.create_task("US-TST-1", "Task 2", "Desc", depends_on=["US-TST-1-1"])
        assert t2.depends_on == ["US-TST-1-1"]
        # Round-trip: re-read from disk
        meta, _ = store.get_task("US-TST-1-2")
        assert meta.depends_on == ["US-TST-1-1"]

    def test_create_task_with_multiple_depends_on(self, store):
        """create_task accepts multiple depends_on entries."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.create_task("US-TST-1", "Task 2", "Desc")
        t3 = store.create_task(
            "US-TST-1", "Task 3", "Desc",
            depends_on=["US-TST-1-1", "US-TST-1-2"],
        )
        assert t3.depends_on == ["US-TST-1-1", "US-TST-1-2"]

    def test_create_task_without_depends_on(self, store):
        """create_task without depends_on defaults to empty list."""
        store.create_story("Story", "Desc")
        task = store.create_task("US-TST-1", "Task 1", "Desc")
        assert task.depends_on == []

    def test_create_task_self_ref_raises(self, store):
        """create_task rejects self-referencing depends_on."""
        store.create_story("Story", "Desc")
        # US-TST-1-1 will be the generated ID
        with pytest.raises(ValueError, match="cannot depend on itself"):
            store.create_task("US-TST-1", "Task 1", "Desc", depends_on=["US-TST-1-1"])

    def test_create_task_nonexistent_dep_raises(self, store):
        """create_task rejects depends_on referencing a task that doesn't exist."""
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError, match="does not exist"):
            store.create_task("US-TST-1", "Task 1", "Desc", depends_on=["US-TST-1-99"])

    def test_create_task_cross_story_dep_allowed(self, store):
        """create_task accepts depends_on referencing a task from a different story."""
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        store.create_task("US-TST-2", "Other task", "Desc")
        # Cross-story dependencies are now allowed
        task = store.create_task("US-TST-1", "Task 1", "Desc", depends_on=["US-TST-2-1"])
        assert task.depends_on == ["US-TST-2-1"]

    def test_create_task_empty_depends_on(self, store):
        """create_task with empty depends_on list works fine."""
        store.create_story("Story", "Desc")
        task = store.create_task("US-TST-1", "Task 1", "Desc", depends_on=[])
        assert task.depends_on == []


class TestCreateTasksBatchDependsOn:
    """Tests for create_tasks batch depends_on support with cycle check."""

    def test_create_tasks_with_depends_on_per_entry(self, store):
        """create_tasks accepts depends_on per entry and persists to frontmatter."""
        store.create_story("Story", "Desc")
        # Create a pre-existing task to depend on
        store.create_task("US-TST-1", "Existing", "Desc")

        results = store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "A", "depends_on": ["US-TST-1-1"]},
            {"title": "Task B", "description": "B"},
        ])
        assert results[0].depends_on == ["US-TST-1-1"]
        assert results[1].depends_on == []
        # Round-trip
        meta_a, _ = store.get_task("US-TST-1-2")
        assert meta_a.depends_on == ["US-TST-1-1"]

    def test_create_tasks_intra_batch_dependency(self, store):
        """A later entry can depend on a task created earlier in the same batch."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "A"},
            {"title": "Task B", "description": "B", "depends_on": ["US-TST-1-1"]},
        ])
        assert results[1].depends_on == ["US-TST-1-1"]
        meta_b, _ = store.get_task("US-TST-1-2")
        assert meta_b.depends_on == ["US-TST-1-1"]

    def test_create_tasks_cycle_detected_and_rolled_back(self, store):
        """Intra-batch cycle (X->Y, Y->X) raises ValueError and rolls back all tasks."""
        store.create_story("Story", "Desc")

        # Batch with a mutual dependency cycle:
        # US-TST-1-1 (X) depends on US-TST-1-2 (Y), Y depends on X
        with pytest.raises(ValueError, match=r"US-TST-1-1 -> US-TST-1-2 -> US-TST-1-1"):
            store.create_tasks("US-TST-1", [
                {"title": "X", "description": "X", "depends_on": ["US-TST-1-2"]},
                {"title": "Y", "description": "Y", "depends_on": ["US-TST-1-1"]},
            ])

        # Rolled back: neither task should exist
        with pytest.raises(FileNotFoundError):
            store.get_task("US-TST-1-1")

    def test_create_tasks_cycle_rollback_cleans_all_batch_files(self, store):
        """On cycle detection, ALL files from the batch are removed."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Pre-existing", "Desc")

        # Pre-existing is US-TST-1-1. Batch creates:
        #   A = US-TST-1-2 (no deps)
        #   B = US-TST-1-3 (depends on US-TST-1-4 = C)
        #   C = US-TST-1-4 (depends on US-TST-1-3 = B) → cycle B<->C
        with pytest.raises(ValueError, match="cycle"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A"},
                {"title": "B", "description": "B", "depends_on": ["US-TST-1-4"]},
                {"title": "C", "description": "C", "depends_on": ["US-TST-1-3"]},
            ])

        # Only the pre-existing task should remain
        tasks = store.list_tasks(story_id="US-TST-1")
        assert len(tasks) == 1
        assert tasks[0].id == "US-TST-1-1"

    def test_create_tasks_no_depends_on_still_works(self, store):
        """Batch without any depends_on works as before."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A"},
            {"title": "B", "description": "B"},
        ])
        assert results[0].depends_on == []
        assert results[1].depends_on == []

    def test_create_tasks_self_ref_in_batch_raises(self, store):
        """Self-referencing depends_on within a batch entry is rejected."""
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A", "depends_on": ["US-TST-1-1"]},
            ])

    def test_create_tasks_nonexistent_dep_in_batch_raises(self, store):
        """depends_on referencing a non-existent task is rejected."""
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError, match="does not exist"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A", "depends_on": ["US-TST-1-99"]},
            ])

    def test_create_tasks_cross_story_dep_allowed(self, store):
        """depends_on referencing a task from a different story is allowed."""
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        store.create_task("US-TST-2", "Other task", "Desc")
        # Cross-story dependencies are now allowed
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A", "depends_on": ["US-TST-2-1"]},
        ])
        assert results[0].depends_on == ["US-TST-2-1"]

    def test_create_tasks_chain_no_cycle(self, store):
        """Linear chain A->B->C is valid (no cycle)."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A"},
            {"title": "B", "description": "B", "depends_on": ["US-TST-1-1"]},
            {"title": "C", "description": "C", "depends_on": ["US-TST-1-2"]},
        ])
        assert results[0].depends_on == []
        assert results[1].depends_on == ["US-TST-1-1"]
        assert results[2].depends_on == ["US-TST-1-2"]


class TestUpdateDependsOn:
    """Tests for update() depends_on validation and cycle rejection."""

    def test_update_depends_on_valid(self, store):
        """update() accepts valid depends_on for a task."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.create_task("US-TST-1", "Task 2", "Desc")
        meta = store.update("US-TST-1-2", depends_on=["US-TST-1-1"])
        assert meta.depends_on == ["US-TST-1-1"]
        # Round-trip
        reloaded, _ = store.get_task("US-TST-1-2")
        assert reloaded.depends_on == ["US-TST-1-1"]

    def test_update_depends_on_self_ref_raises(self, store):
        """update() rejects self-referencing depends_on."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            store.update("US-TST-1-1", depends_on=["US-TST-1-1"])

    def test_update_depends_on_nonexistent_raises(self, store):
        """update() rejects depends_on referencing a non-existent task."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        with pytest.raises(ValueError, match="does not exist"):
            store.update("US-TST-1-1", depends_on=["US-TST-1-99"])

    def test_update_depends_on_cross_story_allowed(self, store):
        """update() accepts depends_on referencing a task from a different story."""
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        store.create_task("US-TST-1", "Task in S1", "Desc")
        store.create_task("US-TST-2", "Task in S2", "Desc")
        # Cross-story dependencies are now allowed
        meta = store.update("US-TST-1-1", depends_on=["US-TST-2-1"])
        assert meta.depends_on == ["US-TST-2-1"]

    def test_update_depends_on_cycle_raises_and_rolls_back(self, store):
        """update() rejects depends_on that would create a cycle and rolls back."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-1", "Task B", "Desc", depends_on=["US-TST-1-1"])
        # B already depends on A; making A depend on B creates A->B->A cycle
        with pytest.raises(ValueError, match="cycle"):
            store.update("US-TST-1-1", depends_on=["US-TST-1-2"])
        # Rolled back: A should still have no depends_on
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.depends_on == []

    def test_update_depends_on_empty_clears(self, store):
        """update() with empty depends_on list clears existing dependencies."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        store.create_task("US-TST-1", "Task 2", "Desc", depends_on=["US-TST-1-1"])
        meta = store.update("US-TST-1-2", depends_on=[])
        assert meta.depends_on == []


class TestDependsOnEdgeCases:
    """Edge-case validation tests for depends_on across create_task, create_tasks, and update."""

    def test_transitive_cycle_in_batch_raises(self, store):
        """3-node cycle (A→B→C→A) in a batch is detected and rolled back."""
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError, match=r"US-TST-1-1 -> US-TST-1-3 -> US-TST-1-2 -> US-TST-1-1"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A", "depends_on": ["US-TST-1-3"]},
                {"title": "B", "description": "B", "depends_on": ["US-TST-1-1"]},
                {"title": "C", "description": "C", "depends_on": ["US-TST-1-2"]},
            ])
        # All rolled back
        assert store.list_tasks(story_id="US-TST-1") == []

    def test_transitive_cycle_via_update_raises(self, store):
        """3-node cycle introduced via update is detected and rolled back."""
        store.create_story("Story", "Desc")
        store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A"},
            {"title": "B", "description": "B", "depends_on": ["US-TST-1-1"]},
            {"title": "C", "description": "C", "depends_on": ["US-TST-1-2"]},
        ])
        # C→B→A; making A depend on C creates A→C→B→A
        with pytest.raises(ValueError, match=r"US-TST-1-1 -> US-TST-1-3 -> US-TST-1-2 -> US-TST-1-1"):
            store.update("US-TST-1-1", depends_on=["US-TST-1-3"])
        # Rolled back: A should still have no deps
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.depends_on == []

    def test_update_cycle_rollback_preserves_body(self, store):
        """Cycle rollback in update restores body and other fields."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task A", "Original body A")
        store.create_task("US-TST-1", "Task B", "Desc", depends_on=["US-TST-1-1"])
        # Try to create A→B cycle by updating A
        with pytest.raises(ValueError, match=r"US-TST-1-1 -> US-TST-1-2 -> US-TST-1-1"):
            store.update("US-TST-1-1", depends_on=["US-TST-1-2"])
        # Body and title should be preserved
        meta, body = store.get_task("US-TST-1-1")
        assert "Original body A" in body
        assert meta.title == "Task A"
        assert meta.depends_on == []

    def test_diamond_dependency_valid(self, store):
        """Diamond pattern (B→A, C→A, D→B+C) is valid — no cycle."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A"},
            {"title": "B", "description": "B", "depends_on": ["US-TST-1-1"]},
            {"title": "C", "description": "C", "depends_on": ["US-TST-1-1"]},
            {"title": "D", "description": "D", "depends_on": ["US-TST-1-2", "US-TST-1-3"]},
        ])
        assert results[3].depends_on == ["US-TST-1-2", "US-TST-1-3"]

    def test_multiple_deps_one_invalid_raises(self, store):
        """If any dep in the list is invalid, the whole call fails."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        with pytest.raises(ValueError, match="does not exist"):
            store.create_task(
                "US-TST-1", "Task 2", "Desc",
                depends_on=["US-TST-1-1", "US-TST-1-99"],
            )

    def test_forward_reference_in_batch_valid(self, store):
        """Earlier batch entry can depend on a later entry (forward ref, no cycle)."""
        store.create_story("Story", "Desc")
        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A", "depends_on": ["US-TST-1-2"]},
            {"title": "B", "description": "B"},
        ])
        assert results[0].depends_on == ["US-TST-1-2"]
        assert results[1].depends_on == []

    def test_duplicate_deps_accepted(self, store):
        """Duplicate entries in depends_on are accepted (no dedup in store layer)."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        t2 = store.create_task(
            "US-TST-1", "Task 2", "Desc",
            depends_on=["US-TST-1-1", "US-TST-1-1"],
        )
        assert t2.depends_on == ["US-TST-1-1", "US-TST-1-1"]

    def test_create_tasks_no_story_raises(self, store):
        """create_tasks for a non-existent story raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            store.create_tasks("US-TST-999", [
                {"title": "A", "description": "A"},
            ])


class TestCheckDependencyCyclesUsesDetectCycle:
    """Verify store._check_dependency_cycles delegates to deps.detect_cycle."""

    def test_delegates_to_deps_detect_cycle(self, store):
        """_check_dependency_cycles calls deps.detect_cycle with the task graph."""
        from unittest.mock import patch

        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-1", "Task B", "Desc")

        with patch("projectman.store.detect_cycle", return_value=None) as mock_dc:
            store._check_dependency_cycles("US-TST-1")
            mock_dc.assert_called_once()
            graph_arg = mock_dc.call_args[0][0]
            assert "US-TST-1-1" in graph_arg
            assert "US-TST-1-2" in graph_arg

    def test_raises_when_detect_cycle_finds_cycle(self, store):
        """_check_dependency_cycles raises ValueError when detect_cycle returns a cycle."""
        from unittest.mock import patch

        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task A", "Desc")
        store.create_task("US-TST-1", "Task B", "Desc")

        fake_cycle = ["US-TST-1-1", "US-TST-1-2", "US-TST-1-1"]
        with patch("projectman.store.detect_cycle", return_value=fake_cycle):
            with pytest.raises(ValueError, match="US-TST-1-1 -> US-TST-1-2 -> US-TST-1-1"):
                store._check_dependency_cycles("US-TST-1")


class TestStoreCustomProjectDir:

    @staticmethod
    def _make_hub(tmp_path):
        """Create a hub root and sub-project PM dir for reuse across tests."""
        import yaml

        hub_root = tmp_path / "hub"
        hub_proj = hub_root / ".project"
        hub_proj.mkdir(parents=True)
        hub_config = {
            "name": "hub",
            "prefix": "HUB",
            "description": "",
            "hub": True,
            "next_story_id": 1,
            "next_epic_id": 1,
            "projects": ["api"],
        }
        with open(hub_proj / "config.yaml", "w") as f:
            yaml.dump(hub_config, f)

        pm_dir = hub_proj / "projects" / "api"
        pm_dir.mkdir(parents=True)
        (pm_dir / "stories").mkdir()
        (pm_dir / "tasks").mkdir()
        (pm_dir / "epics").mkdir()
        api_config = {
            "name": "api",
            "prefix": "API",
            "description": "",
            "hub": False,
            "next_story_id": 1,
            "next_epic_id": 1,
            "projects": [],
        }
        with open(pm_dir / "config.yaml", "w") as f:
            yaml.dump(api_config, f)

        return hub_root, pm_dir

    def test_store_with_custom_project_dir(self, tmp_path):
        """Store reads/writes to a custom project_dir instead of root/.project/."""
        import yaml

        hub_root, pm_dir = self._make_hub(tmp_path)

        # Create a store pointing at the custom project_dir
        store = Store(hub_root, project_dir=pm_dir)
        assert store.config.name == "api"
        assert store.config.prefix == "API"
        assert store.project_dir == pm_dir

        # Create a story -- files should land in pm_dir
        meta, _ = store.create_story("API Story", "Desc", points=5)
        assert meta.id == "US-API-1"
        assert (pm_dir / "stories" / "US-API-1.md").exists()

        # Config counter should be saved to pm_dir, not hub root
        with open(pm_dir / "config.yaml") as f:
            saved = yaml.safe_load(f)
        assert saved["next_story_id"] == 2

    def test_epic_creation_with_custom_project_dir(self, tmp_path):
        """Epic counter is saved to project_dir, not hub root."""
        import yaml

        hub_root, pm_dir = self._make_hub(tmp_path)
        store = Store(hub_root, project_dir=pm_dir)

        epic = store.create_epic("API Epic", "Epic description", priority="must")
        assert epic.id == "EPIC-API-1"
        assert (pm_dir / "epics" / "EPIC-API-1.md").exists()

        # Counter persisted to pm_dir config, not hub root
        with open(pm_dir / "config.yaml") as f:
            saved = yaml.safe_load(f)
        assert saved["next_epic_id"] == 2

        # Hub config should be untouched
        with open(hub_root / ".project" / "config.yaml") as f:
            hub_saved = yaml.safe_load(f)
        assert hub_saved.get("next_epic_id", 1) == 1


class TestClearCache:
    def test_clear_cache_instance(self, store):
        """clear_cache() removes all entries for this Store instance."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        # Populate cache
        store.list_stories()
        store.list_tasks()
        assert store._cache_key("stories") in _cache
        assert store._cache_key("tasks") in _cache

        store.clear_cache()
        assert store._cache_key("stories") not in _cache
        assert store._cache_key("tasks") not in _cache

    def test_clear_all_caches(self, store):
        """clear_all_caches() empties the entire module-level cache."""
        store.create_story("Story", "Desc")
        store.list_stories()
        assert len(_cache) > 0

        clear_all_caches()
        assert len(_cache) == 0

    def test_get_cache_stats_returns_copy(self, store):
        """get_cache_stats() returns a dict copy, not the internal object."""
        stats = get_cache_stats()
        assert isinstance(stats, dict)
        assert "hits" in stats and "misses" in stats and "invalidations" in stats
        stats["hits"] = 9999
        assert get_cache_stats()["hits"] != 9999

    def test_cache_stats_track_with_debug(self, store, monkeypatch):
        """With PROJECTMAN_CACHE_DEBUG, stats track hits/misses/invalidations."""
        monkeypatch.setattr(store_module, "_cache_debug", True)
        clear_all_caches()

        store.create_story("Story", "Desc")
        # First list_stories -> miss (populates cache)
        store.list_stories()
        assert get_cache_stats()["misses"] >= 1

        # Second list_stories -> hit
        store.list_stories()
        assert get_cache_stats()["hits"] >= 1

        # create_story appends to the stories cache rather than invalidating it,
        # so the invalidation counter is unchanged. The new file changes the
        # directory signature, so the next list_stories re-reads from disk and
        # includes the new story.
        before_inv = get_cache_stats()["invalidations"]
        store.create_story("Story 2", "Desc")
        assert get_cache_stats()["invalidations"] == before_inv
        stories = store.list_stories()
        assert any(s.title == "Story 2" for s in stories)

    def test_cache_stats_no_track_without_debug(self, store, monkeypatch):
        """Without PROJECTMAN_CACHE_DEBUG, stats stay at zero."""
        monkeypatch.setattr(store_module, "_cache_debug", False)
        clear_all_caches()

        store.create_story("Story", "Desc")
        store.list_stories()
        store.list_stories()
        stats = get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["invalidations"] == 0

    def test_clear_cache_after_list_repopulates(self, store):
        """After clear_cache, next list call re-reads from disk."""
        store.create_story("Story", "Desc")
        stories = store.list_stories()
        assert len(stories) == 1

        store.clear_cache()
        stories = store.list_stories()
        assert len(stories) == 1


class TestCacheHoldsInMemory:
    """Verify that after the first list call, subsequent calls return from cache not disk."""

    def test_cache_contains_frontmatter_after_first_load(self, store):
        """After the first list call, _cache holds parsed frontmatter objects."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Body")
        store.create_epic("Epic 1", "Desc")
        store.clear_cache()

        assert store._cache_key("stories") not in _cache
        assert store._cache_key("tasks") not in _cache
        assert store._cache_key("epics") not in _cache

        # First list call should populate the cache
        store.list_stories()
        store.list_tasks()
        store.list_epics()

        # Cache now holds parsed frontmatter tuples
        stories_key = store._cache_key("stories")
        tasks_key = store._cache_key("tasks")
        epics_key = store._cache_key("epics")

        assert stories_key in _cache
        assert tasks_key in _cache
        assert epics_key in _cache

        # Each entry is a (frontmatter_obj, body_str) tuple
        assert len(_cache[stories_key]) == 1
        meta, body = _cache[stories_key][0]
        assert meta.id == "US-TST-1"
        assert meta.title == "Story"
        assert isinstance(body, str)

        assert len(_cache[tasks_key]) == 1
        task_meta, task_body = _cache[tasks_key][0]
        assert task_meta.id == "US-TST-1-1"
        assert task_meta.story_id == "US-TST-1"

        assert len(_cache[epics_key]) == 1
        epic_meta, _ = _cache[epics_key][0]
        assert epic_meta.title == "Epic 1"

    def test_list_tasks_no_disk_read_on_second_call(self, store, monkeypatch):
        """After list_tasks populates cache, second call does not read from disk."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Do something")
        store.clear_cache()

        # First call — populates cache (reads disk)
        tasks1 = store.list_tasks(story_id="US-TST-1")
        assert len(tasks1) == 1

        # Patch frontmatter.load so any disk read raises
        import frontmatter as fm
        original_load = fm.load
        def fail_on_load(*args, **kwargs):
            raise AssertionError("Unexpected disk read via frontmatter.load")
        monkeypatch.setattr(fm, "load", fail_on_load)

        # Second call — must come from cache, no disk I/O
        tasks2 = store.list_tasks(story_id="US-TST-1")
        assert len(tasks2) == 1
        assert tasks2[0].id == "US-TST-1-1"

    def test_list_stories_no_disk_read_on_second_call(self, store, monkeypatch):
        """After list_stories populates cache, second call does not read from disk."""
        store.create_story("Story 1", "Desc 1")
        store.create_story("Story 2", "Desc 2")
        store.clear_cache()

        # First call — populates cache
        stories1 = store.list_stories()
        assert len(stories1) == 2

        # Patch frontmatter.load
        import frontmatter as fm
        monkeypatch.setattr(fm, "load", lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Unexpected disk read via frontmatter.load")))

        # Second call — from cache
        stories2 = store.list_stories()
        assert len(stories2) == 2

    def test_list_epics_no_disk_read_on_second_call(self, store, monkeypatch):
        """After list_epics populates cache, second call does not read from disk."""
        store.create_epic("Epic 1", "Desc")
        store.clear_cache()

        # First call — populates cache
        epics1 = store.list_epics()
        assert len(epics1) == 1

        # Patch frontmatter.load
        import frontmatter as fm
        monkeypatch.setattr(fm, "load", lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Unexpected disk read via frontmatter.load")))

        # Second call — from cache
        epics2 = store.list_epics()
        assert len(epics2) == 1

    def test_get_task_uses_cache_after_list(self, store, monkeypatch):
        """get_task returns from cache if list_tasks has been called."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", "Body text")
        store.clear_cache()

        # Populate cache via list
        store.list_tasks()

        # Patch disk I/O
        import frontmatter as fm
        monkeypatch.setattr(fm, "load", lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Unexpected disk read via frontmatter.load")))

        # get_task should use cached data
        meta, body = store.get_task("US-TST-1-1")
        assert meta.id == "US-TST-1-1"
        assert meta.title == "Task 1"

    def test_get_story_uses_cache_after_list(self, store, monkeypatch):
        """get_story returns from cache if list_stories has been called."""
        store.create_story("My Story", "Story body")
        store.clear_cache()

        # Populate cache via list
        store.list_stories()

        # Patch disk I/O
        import frontmatter as fm
        monkeypatch.setattr(fm, "load", lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Unexpected disk read via frontmatter.load")))

        # get_story should use cached data
        meta, body = store.get_story("US-TST-1")
        assert meta.id == "US-TST-1"
        assert meta.title == "My Story"


class TestCachePerInstanceSharedDict:
    """Cache is per-Store instance with a module-level shared dict."""

    def test_two_stores_same_base_dir_share_cache(self, tmp_project):
        """Two Store instances pointing to the same base_dir share the module-level cache."""
        _cache.clear()
        store_a = Store(tmp_project)
        store_b = Store(tmp_project)

        # Create data via store_a
        store_a.create_story("Shared Story", "Desc")
        store_a.create_task("US-TST-1", "Task 1", "Body")

        # Populate cache via store_a
        store_a.list_tasks()
        assert store_a._cache_key("tasks") in _cache

        # store_b should see the same cache entry (same key)
        assert store_b._cache_key("tasks") == store_a._cache_key("tasks")
        assert store_b._cache_key("tasks") in _cache

        # store_b.list_tasks should return from cache, not re-read disk
        tasks = store_b.list_tasks(story_id="US-TST-1")
        assert len(tasks) == 1
        assert tasks[0].id == "US-TST-1-1"

    def test_different_base_dir_isolated_cache(self, tmp_path):
        """A Store with a different base_dir has an isolated cache."""
        _cache.clear()

        # Set up two separate project directories
        for name, prefix in [("proj-a", "AAA"), ("proj-b", "BBB")]:
            proj = tmp_path / name / ".project"
            proj.mkdir(parents=True)
            (proj / "stories").mkdir()
            (proj / "tasks").mkdir()
            import yaml
            config = {
                "name": name,
                "prefix": prefix,
                "description": f"Project {name}",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            }
            with open(proj / "config.yaml", "w") as f:
                yaml.dump(config, f)

        store_a = Store(tmp_path / "proj-a")
        store_b = Store(tmp_path / "proj-b")

        # Create data in store_a only
        store_a.create_story("Story A", "Desc A")
        store_a.create_task("US-AAA-1", "Task A", "Body A")

        # Populate cache for store_a
        tasks_a = store_a.list_tasks()
        assert len(tasks_a) == 1

        # store_b cache key is different
        assert store_a._cache_key("tasks") != store_b._cache_key("tasks")

        # store_b should see no tasks (isolated)
        tasks_b = store_b.list_tasks()
        assert len(tasks_b) == 0


class TestStoryDependsOn:
    """Tests for story depends_on parameter and validation."""

    def test_create_story_with_depends_on(self, store):
        """create_story accepts depends_on and persists it to frontmatter."""
        store.create_story("Story 1", "Desc")
        meta, _ = store.create_story("Story 2", "Desc", depends_on=["US-TST-1"])
        assert meta.depends_on == ["US-TST-1"]
        reloaded, _ = store.get_story("US-TST-2")
        assert reloaded.depends_on == ["US-TST-1"]

    def test_create_story_without_depends_on(self, store):
        """create_story without depends_on defaults to empty list."""
        meta, _ = store.create_story("Story", "Desc")
        assert meta.depends_on == []

    def test_create_story_depends_on_task(self, store):
        """A story can depend on a specific task."""
        store.create_story("Story 1", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        meta, _ = store.create_story("Story 2", "Desc", depends_on=["US-TST-1-1"])
        assert meta.depends_on == ["US-TST-1-1"]

    def test_create_story_self_dep_raises(self, store):
        """create_story rejects self-referencing depends_on.

        Note: Since story IDs are auto-generated, self-reference check happens
        after ID generation but before writing to disk.
        """
        # Create first story to establish what the next ID will be
        store.create_story("Story 1", "Desc")
        # The next story will be US-TST-2, so trying to depend on it is self-ref
        with pytest.raises(ValueError, match="cannot depend on itself"):
            store.create_story("Story 2", "Desc", depends_on=["US-TST-2"])

    def test_create_story_nonexistent_dep_raises(self, store):
        """create_story rejects depends_on referencing a non-existent item."""
        with pytest.raises(ValueError, match="does not exist"):
            store.create_story("Story", "Desc", depends_on=["US-TST-999"])

    def test_update_story_depends_on(self, store):
        """update() accepts depends_on for a story."""
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        meta = store.update("US-TST-2", depends_on=["US-TST-1"])
        assert meta.depends_on == ["US-TST-1"]

    def test_update_story_depends_on_self_raises(self, store):
        """update() rejects self-referencing depends_on for a story."""
        store.create_story("Story 1", "Desc")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            store.update("US-TST-1", depends_on=["US-TST-1"])

    def test_update_story_depends_on_nonexistent_raises(self, store):
        """update() rejects depends_on referencing a non-existent item."""
        store.create_story("Story", "Desc")
        with pytest.raises(ValueError, match="does not exist"):
            store.update("US-TST-1", depends_on=["US-TST-999"])

    def test_task_depends_on_story_is_rejected(self, store):
        """A task may NOT depend on a story (contract change, US-PRJ-50).

        The dependency only ever resolves in one direction: a story may
        depend on a task (see ``test_create_story_depends_on_task`` above),
        but a task blocks on other tasks only -- a story is not a unit of
        work whose completion a task can observe.  Before US-PRJ-50 the
        permissive ID pattern let a story ID through here.
        """
        store.create_story("Story 1", "Desc")
        store.create_story("Story 2", "Desc")
        with pytest.raises(ValidationError) as exc:
            store.create_task("US-TST-2", "Task", "Desc", depends_on=["US-TST-1"])
        assert TASK_ID.pattern in str(exc.value)

    def test_task_depends_on_task_is_accepted(self, store):
        """The sibling of the above: a task may depend on another task."""
        store.create_story("Story 1", "Desc")
        store.create_task("US-TST-1", "Task 1", "Desc")
        task = store.create_task(
            "US-TST-1", "Task 2", "Desc", depends_on=["US-TST-1-1"]
        )
        assert task.depends_on == ["US-TST-1-1"]


class TestIdAllocationReconcilesWithDisk:
    """ID allocation is the max of the config counter and what is on disk.

    The in-memory ``next_story_id`` is a per-process snapshot.  Two live
    Stores on one project — two agent sessions, or a CLI run beside an MCP
    server — used to both start from the same number, so the second create
    handed out an ID the first had already written and overwrote it.
    """

    @staticmethod
    def _fresh_store(root):
        """A Store that loaded config.yaml independently, as a new process would."""
        from projectman.config import clear_config_cache

        clear_config_cache()
        return Store(root)

    def test_second_store_does_not_reuse_first_stores_story_id(self, tmp_project):
        """Two Stores create in turn; both stories survive with distinct IDs."""
        _cache.clear()
        store_a = self._fresh_store(tmp_project)
        store_b = self._fresh_store(tmp_project)
        assert store_a.config is not store_b.config, "fixture must model two processes"

        meta_a, _ = store_a.create_story("From A", "Body A")
        meta_b, _ = store_b.create_story("From B", "Body B")

        assert meta_a.id != meta_b.id
        assert {meta_a.id, meta_b.id} == {"US-TST-1", "US-TST-2"}

        stories_dir = tmp_project / ".project" / "stories"
        assert (stories_dir / f"{meta_a.id}.md").exists()
        assert (stories_dir / f"{meta_b.id}.md").exists()
        assert "From A" in (stories_dir / f"{meta_a.id}.md").read_text()
        assert "From B" in (stories_dir / f"{meta_b.id}.md").read_text()

        import yaml as _yaml

        persisted = _yaml.safe_load((tmp_project / ".project" / "config.yaml").read_text())
        assert persisted["next_story_id"] == 3

    def test_story_id_skips_past_a_higher_file_on_disk(self, tmp_project):
        """A story pulled in from git without a counter bump is not overwritten."""
        _cache.clear()
        store = self._fresh_store(tmp_project)
        pulled = tmp_project / ".project" / "stories" / "US-TST-7.md"
        pulled.parent.mkdir(parents=True, exist_ok=True)
        pulled.write_text("---\nid: US-TST-7\n---\nPulled from a teammate\n")

        meta, _ = store.create_story("After the pull", "Body")

        assert meta.id == "US-TST-8"
        assert "Pulled from a teammate" in pulled.read_text()

    def test_second_store_does_not_reuse_first_stores_epic_id(self, tmp_project):
        """Same reconciliation for epics."""
        _cache.clear()
        store_a = self._fresh_store(tmp_project)
        store_b = self._fresh_store(tmp_project)

        epic_a = store_a.create_epic("Epic A", "Body A")
        epic_b = store_b.create_epic("Epic B", "Body B")

        assert epic_a.id != epic_b.id
        assert {epic_a.id, epic_b.id} == {"EPIC-TST-1", "EPIC-TST-2"}

        epics_dir = tmp_project / ".project" / "epics"
        assert "Body A" in (epics_dir / f"{epic_a.id}.md").read_text()
        assert "Body B" in (epics_dir / f"{epic_b.id}.md").read_text()

    def test_epic_id_skips_past_a_higher_file_on_disk(self, tmp_project):
        _cache.clear()
        store = self._fresh_store(tmp_project)
        pulled = tmp_project / ".project" / "epics" / "EPIC-TST-4.md"
        pulled.parent.mkdir(parents=True, exist_ok=True)
        pulled.write_text("---\nid: EPIC-TST-4\n---\nPulled epic\n")

        epic = store.create_epic("After the pull", "Body")

        assert epic.id == "EPIC-TST-5"
        assert "Pulled epic" in pulled.read_text()

    def test_foreign_prefix_files_are_ignored(self, tmp_project):
        """Only the project's own prefix counts — US-PRJ-49.md must not move TST."""
        _cache.clear()
        store = self._fresh_store(tmp_project)
        stories_dir = tmp_project / ".project" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "US-PRJ-49.md").write_text("---\nid: US-PRJ-49\n---\nOther project\n")
        (stories_dir / "US-TSTX-12.md").write_text("---\nid: US-TSTX-12\n---\nNot our prefix\n")

        meta, _ = store.create_story("Ours", "Body")

        assert meta.id == "US-TST-1"

    def test_task_files_do_not_move_the_story_counter(self, tmp_project):
        """``US-TST-3-9.md`` is a task ID, not a story number."""
        _cache.clear()
        store = self._fresh_store(tmp_project)
        stories_dir = tmp_project / ".project" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "US-TST-3-9.md").write_text("---\nid: US-TST-3-9\n---\nA task\n")

        meta, _ = store.create_story("Ours", "Body")

        assert meta.id == "US-TST-1"

    def test_story_allocation_does_not_roll_back_the_epic_counter(self, tmp_project):
        """_save_config rewrites the whole file, so sibling counters carry forward."""
        _cache.clear()
        store_a = self._fresh_store(tmp_project)
        store_b = self._fresh_store(tmp_project)

        store_a.create_epic("Epic A", "Body")  # bumps next_epic_id on disk to 2
        store_b.create_story("Story B", "Body")  # store_b still remembers epic 1

        import yaml as _yaml

        persisted = _yaml.safe_load((tmp_project / ".project" / "config.yaml").read_text())
        assert persisted["next_epic_id"] == 2


class TestTaskIdAllocationScansDisk:
    """Task IDs come from the highest suffix on disk, not the task count.

    ``len(list_tasks(story)) + 1`` was only ever right while nothing had
    been removed.  Delete the middle of three tasks and the count says 3,
    so the next create reused ``-3`` and silently rewrote a live task.
    Scanning for the highest existing suffix makes IDs monotonic: a freed
    number stays free.
    """

    @staticmethod
    def _story_file(tmp_project, story_id: str) -> None:
        """Write a story file directly — create_task only checks it exists."""
        stories = tmp_project / ".project" / "stories"
        stories.mkdir(parents=True, exist_ok=True)
        (stories / f"{story_id}.md").write_text(
            f"---\nid: {story_id}\n---\nHand-written story\n"
        )

    def test_next_id_skips_a_deleted_middle_task(self, store, tmp_project):
        """Deleting -2 must not make the next create overwrite -3."""
        store.create_story("Story", "Desc")
        for title in ("One", "Two", "Three"):
            store.create_task("US-TST-1", title, f"Desc {title}")

        tasks_dir = tmp_project / ".project" / "tasks"
        (tasks_dir / "US-TST-1-2.md").unlink()
        survivor = (tasks_dir / "US-TST-1-3.md").read_text()

        meta = store.create_task("US-TST-1", "Four", "Desc Four")

        assert meta.id == "US-TST-1-4"
        assert (tasks_dir / "US-TST-1-3.md").read_text() == survivor
        assert not (tasks_dir / "US-TST-1-2.md").exists()

    def test_next_id_never_reuses_a_deleted_last_task(self, store, tmp_project):
        """The freed top number is gone for good, not handed out again."""
        store.create_story("Story", "Desc")
        for title in ("One", "Two", "Three"):
            store.create_task("US-TST-1", title, f"Desc {title}")

        (tmp_project / ".project" / "tasks" / "US-TST-1-3.md").unlink()

        meta = store.create_task("US-TST-1", "Four", "Desc Four")

        assert meta.id == "US-TST-1-4"

    def test_story_3_and_story_30_do_not_share_a_namespace(self, store, tmp_project):
        """``US-TST-3-`` must not match ``US-TST-30-1.md`` — prefix, not substring."""
        tasks_dir = tmp_project / ".project" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        self._story_file(tmp_project, "US-TST-3")
        self._story_file(tmp_project, "US-TST-30")
        (tasks_dir / "US-TST-3-1.md").write_text(
            "---\nid: US-TST-3-1\nstory_id: US-TST-3\n---\nOwned by story 3\n"
        )
        for n in (1, 9):
            (tasks_dir / f"US-TST-30-{n}.md").write_text(
                f"---\nid: US-TST-30-{n}\nstory_id: US-TST-30\n---\nOwned by story 30\n"
            )

        assert store.create_task("US-TST-3", "Next for 3", "Desc").id == "US-TST-3-2"
        assert store.create_task("US-TST-30", "Next for 30", "Desc").id == "US-TST-30-10"
        assert (tasks_dir / "US-TST-3-1.md").read_text().endswith("Owned by story 3\n")
        assert (tasks_dir / "US-TST-30-9.md").read_text().endswith("Owned by story 30\n")

    def test_batch_seeds_from_disk_and_keeps_forward_references(self, store, tmp_project):
        """A batch after a deletion allocates -4,-5,-6, forward refs intact."""
        store.create_story("Story", "Desc")
        for title in ("One", "Two", "Three"):
            store.create_task("US-TST-1", title, f"Desc {title}")
        (tmp_project / ".project" / "tasks" / "US-TST-1-2.md").unlink()

        results = store.create_tasks("US-TST-1", [
            {"title": "A", "description": "A", "depends_on": ["US-TST-1-6"]},
            {"title": "B", "description": "B"},
            {"title": "C", "description": "C"},
        ])

        assert [t.id for t in results] == ["US-TST-1-4", "US-TST-1-5", "US-TST-1-6"]
        assert results[0].depends_on == ["US-TST-1-6"]
        meta_a, _ = store.get_task("US-TST-1-4")
        assert meta_a.depends_on == ["US-TST-1-6"]


class TestCreateRefusesAnExistingTarget:
    """No create may write over a file that is already there.

    US-PM-24-5/-6 made ID allocation reconcile with disk, so a collision
    should now be unreachable through the allocators alone.  This class
    covers the case they cannot: a *second process* that wrote the file
    between our allocation and our write.  The allocator is stubbed to
    stand in for that race, because by construction it will no longer
    hand out a taken number on its own.  What is asserted is the
    consequence — the create raises and the bytes on disk are untouched.
    """

    SENTINEL = "---\nid: SENTINEL\n---\nDo not overwrite me.\n"

    @staticmethod
    def _story_file(tmp_project, story_id: str) -> None:
        stories = tmp_project / ".project" / "stories"
        stories.mkdir(parents=True, exist_ok=True)
        (stories / f"{story_id}.md").write_text(
            f"---\nid: {story_id}\n---\nHand-written story\n"
        )

    @staticmethod
    def _events(tmp_project) -> str:
        log = tmp_project / ".project" / "activity.jsonl"
        return log.read_text() if log.exists() else ""

    def test_create_story_refuses(self, store, tmp_project, monkeypatch):
        target = tmp_project / ".project" / "stories" / "US-TST-7.md"
        target.write_text(self.SENTINEL)
        before = self._events(tmp_project)
        monkeypatch.setattr(store, "_next_story_id", lambda: "US-TST-7")

        with pytest.raises(FileExistsError, match="US-TST-7 already exists"):
            store.create_story("Clobberer", "Body")

        assert target.read_text() == self.SENTINEL
        assert self._events(tmp_project) == before

    def test_create_epic_refuses(self, store, tmp_project, monkeypatch):
        epics = tmp_project / ".project" / "epics"
        epics.mkdir(parents=True, exist_ok=True)
        target = epics / "EPIC-TST-7.md"
        target.write_text(self.SENTINEL)
        before = self._events(tmp_project)
        monkeypatch.setattr(store, "_next_epic_id", lambda: "EPIC-TST-7")

        with pytest.raises(FileExistsError, match="EPIC-TST-7 already exists"):
            store.create_epic("Clobberer", "Body")

        assert target.read_text() == self.SENTINEL
        assert self._events(tmp_project) == before

    def test_create_task_refuses(self, store, tmp_project, monkeypatch):
        self._story_file(tmp_project, "US-TST-1")
        tasks = tmp_project / ".project" / "tasks"
        tasks.mkdir(parents=True, exist_ok=True)
        target = tasks / "US-TST-1-7.md"
        target.write_text(self.SENTINEL)
        before = self._events(tmp_project)
        monkeypatch.setattr(store, "_next_task_id", lambda story_id: "US-TST-1-7")

        with pytest.raises(FileExistsError, match="US-TST-1-7 already exists"):
            store.create_task("US-TST-1", "Clobberer", "Body")

        assert target.read_text() == self.SENTINEL
        assert self._events(tmp_project) == before

    def test_create_sprint_refuses(self, store, tmp_project):
        """Reachable without a stub: sprint IDs come from the counter alone."""
        sprints = tmp_project / ".project" / "sprints"
        sprints.mkdir(parents=True, exist_ok=True)
        target = sprints / "SPRINT-TST-1.md"
        target.write_text(self.SENTINEL)
        before = self._events(tmp_project)

        with pytest.raises(FileExistsError, match="SPRINT-TST-1 already exists"):
            store.create_sprint("Clobberer")

        assert target.read_text() == self.SENTINEL
        assert self._events(tmp_project) == before

    def test_create_tasks_refuses_the_whole_batch(self, store, tmp_project, monkeypatch):
        """The third ID is taken, so none of the batch lands — not even the first two.

        The allocator would step over the taken number by itself (that is
        US-PM-24-6), so it is stubbed back to the seed a racing process
        would have handed us: the point here is that the *batch* checks
        every ID before writing any file.
        """
        store.create_story("Story", "Desc")
        tasks = tmp_project / ".project" / "tasks"
        target = tasks / "US-TST-1-3.md"
        target.write_text(self.SENTINEL)
        before = self._events(tmp_project)
        monkeypatch.setattr(store, "_next_task_id", lambda story_id: "US-TST-1-1")

        with pytest.raises(FileExistsError, match="US-TST-1-3 already exists"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A"},
                {"title": "B", "description": "B"},
                {"title": "C", "description": "C"},
                {"title": "D", "description": "D"},
            ])

        assert target.read_text() == self.SENTINEL
        assert not (tasks / "US-TST-1-1.md").exists()
        assert not (tasks / "US-TST-1-2.md").exists()
        assert not (tasks / "US-TST-1-4.md").exists()
        assert self._events(tmp_project) == before
        assert [t.id for t in store.list_tasks("US-TST-1")] == []

    def test_batch_still_rolls_back_on_a_dependency_cycle(self, store, tmp_project):
        """The rollback path removes exactly the files the batch wrote."""
        store.create_story("Story", "Desc")
        tasks = tmp_project / ".project" / "tasks"
        survivor = tasks / "US-TST-1-1.md"
        store.create_task("US-TST-1", "Existing", "Body")
        kept = survivor.read_text()

        with pytest.raises(ValueError, match="Dependency cycle"):
            store.create_tasks("US-TST-1", [
                {"title": "A", "description": "A", "depends_on": ["US-TST-1-3"]},
                {"title": "B", "description": "B", "depends_on": ["US-TST-1-2"]},
            ])

        assert survivor.read_text() == kept
        assert not (tasks / "US-TST-1-2.md").exists()
        assert not (tasks / "US-TST-1-3.md").exists()


class TestCreatesWriteAtomically:
    """A create that dies mid-write leaves no half-item behind.

    ``_atomic_write_text`` writes a same-directory temp file and
    ``os.replace``s it into position, so the target either does not exist
    or is complete.  Each case here kills the write inside the helper and
    asserts the target never appeared — and that no ``.tmp`` debris was
    left in the directory either.
    """

    @staticmethod
    def _explode(monkeypatch):
        """Make every atomic write fail as if the disk went away mid-create."""
        def boom(path, text):
            raise OSError("disk went away")

        monkeypatch.setattr(store_module, "_atomic_write_text", boom)

    @staticmethod
    def _debris(directory):
        return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]

    def test_story_create_leaves_no_partial_file(self, store, tmp_project, monkeypatch):
        stories = tmp_project / ".project" / "stories"
        self._explode(monkeypatch)

        with pytest.raises(OSError, match="disk went away"):
            store.create_story("Doomed", "Body")

        assert not (stories / "US-TST-1.md").exists()
        assert self._debris(stories) == []

    def test_task_create_leaves_no_partial_file(self, store, tmp_project, monkeypatch):
        store.create_story("Story", "Desc")
        tasks = tmp_project / ".project" / "tasks"
        self._explode(monkeypatch)

        with pytest.raises(OSError, match="disk went away"):
            store.create_task("US-TST-1", "Doomed", "Body")

        assert not (tasks / "US-TST-1-1.md").exists()
        assert self._debris(tasks) == []

    def test_a_torn_write_inside_the_helper_never_becomes_the_target(
        self, store, tmp_project, monkeypatch
    ):
        """Fail after the temp file is written but before the rename."""
        import os as _os

        real_replace = _os.replace

        def fail_replace(src, dst):
            raise OSError("power cut before rename")

        store.create_story("Story", "Desc")
        tasks = tmp_project / ".project" / "tasks"
        monkeypatch.setattr(store_module.os, "replace", fail_replace)

        with pytest.raises(OSError, match="power cut before rename"):
            store.create_task("US-TST-1", "Doomed", "Body")

        monkeypatch.setattr(store_module.os, "replace", real_replace)
        assert not (tasks / "US-TST-1-1.md").exists()
        # The helper unlinks its own temp file on any failure.
        assert [p.name for p in tasks.iterdir()] == []

    def test_creates_go_through_the_atomic_helper(self, store, tmp_project, monkeypatch):
        """Named so a future refactor back to write_text fails here, loudly."""
        seen = []
        real = store_module._atomic_write_text

        def spy(path, text):
            seen.append(path.name)
            return real(path, text)

        monkeypatch.setattr(store_module, "_atomic_write_text", spy)
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "T", "Body")
        store.create_tasks("US-TST-1", [{"title": "B", "description": "B"}])
        store.create_epic("Epic", "Body")
        store.create_sprint("Sprint")

        assert seen == [
            "US-TST-1.md",
            "US-TST-1-1.md",
            "US-TST-1-2.md",
            "EPIC-TST-1.md",
            "SPRINT-TST-1.md",
        ]

    def test_a_created_file_is_readable_not_owner_only(self, store, tmp_project):
        """mkstemp makes 0600; a created item must not be stricter than a written one."""
        import os as _os

        store.create_story("Story", "Desc")
        mode = _os.stat(tmp_project / ".project" / "stories" / "US-TST-1.md").st_mode
        assert mode & 0o7777 == store_module._NEW_FILE_MODE
