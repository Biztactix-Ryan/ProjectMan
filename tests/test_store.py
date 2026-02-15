"""Tests for Store CRUD operations."""

import pytest

from projectman.store import Store


class TestStoreStories:
    def test_create_story(self, store):
        meta = store.create_story("My Story", "As a user, I want things")
        assert meta.id == "US-TST-1"
        assert meta.title == "My Story"

    def test_create_story_with_options(self, store):
        meta = store.create_story(
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
        s1 = store.create_story("First", "Desc")
        s2 = store.create_story("Second", "Desc")
        assert s1.id == "US-TST-1"
        assert s2.id == "US-TST-2"


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
