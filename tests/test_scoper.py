"""Tests for scoping support."""

import yaml
from projectman.store import Store
from projectman.scoper import scope


def test_scope_story(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "As a user, I want authentication")
    result = scope(store, "TST-1")
    data = yaml.safe_load(result)
    assert "decomposition_guidance" in data
    assert data["task_count"] == 0


def test_scope_with_existing_tasks(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.create_task("TST-1", "Task 1", "Desc")
    result = scope(store, "TST-1")
    data = yaml.safe_load(result)
    assert data["task_count"] == 1
    assert len(data["existing_tasks"]) == 1
