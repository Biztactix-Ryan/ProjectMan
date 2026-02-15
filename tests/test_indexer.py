"""Tests for index generation."""

from projectman.indexer import build_index, write_index
from projectman.store import Store


def test_build_empty_index(store):
    index = build_index(store)
    assert index.story_count == 0
    assert index.task_count == 0
    assert index.total_points == 0


def test_build_index_with_stories(store):
    store.create_story("Story 1", "Desc", points=3)
    store.create_story("Story 2", "Desc", points=5)
    index = build_index(store)
    assert index.story_count == 2
    assert index.total_points == 8


def test_build_index_with_tasks(store):
    store.create_story("Story", "Desc", points=5)
    store.create_task("TST-1", "Task 1", "Desc", points=2)
    store.create_task("TST-1", "Task 2", "Desc", points=3)
    index = build_index(store)
    assert index.task_count == 2
    assert index.total_points == 10  # 5 + 2 + 3


def test_completed_points(store):
    store.create_story("Story", "Desc", points=5)
    store.update("TST-1", status="done")
    index = build_index(store)
    assert index.completed_points == 5


def test_write_index(store):
    store.create_story("Story", "Desc", points=3)
    write_index(store)
    index_path = store.project_dir / "index.yaml"
    assert index_path.exists()
