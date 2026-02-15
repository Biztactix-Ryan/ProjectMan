"""Tests for Store CRUD operations."""

import pytest

from projectman.store import Store


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
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        store.archive("US-TST-1-1")
        meta, _ = store.get_task("US-TST-1-1")
        assert meta.status.value == "done"

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


class TestStoreCustomProjectDir:
    def test_store_with_custom_project_dir(self, tmp_path):
        """Store reads/writes to a custom project_dir instead of root/.project/."""
        import yaml

        # Set up a hub root with its own config
        hub_root = tmp_path / "hub"
        hub_proj = hub_root / ".project"
        hub_proj.mkdir(parents=True)
        hub_config = {
            "name": "hub",
            "prefix": "HUB",
            "description": "",
            "hub": True,
            "next_story_id": 1,
            "projects": ["api"],
        }
        with open(hub_proj / "config.yaml", "w") as f:
            yaml.dump(hub_config, f)

        # Set up PM data dir for the "api" project under the hub
        pm_dir = hub_proj / "projects" / "api"
        pm_dir.mkdir(parents=True)
        (pm_dir / "stories").mkdir()
        (pm_dir / "tasks").mkdir()
        api_config = {
            "name": "api",
            "prefix": "API",
            "description": "",
            "hub": False,
            "next_story_id": 1,
            "projects": [],
        }
        with open(pm_dir / "config.yaml", "w") as f:
            yaml.dump(api_config, f)

        # Create a store pointing at the custom project_dir
        store = Store(hub_root, project_dir=pm_dir)
        assert store.config.name == "api"
        assert store.config.prefix == "API"
        assert store.project_dir == pm_dir

        # Create a story — files should land in pm_dir
        meta, _ = store.create_story("API Story", "Desc", points=5)
        assert meta.id == "US-API-1"
        assert (pm_dir / "stories" / "US-API-1.md").exists()

        # Config counter should be saved to pm_dir, not hub root
        with open(pm_dir / "config.yaml") as f:
            saved = yaml.safe_load(f)
        assert saved["next_story_id"] == 2
