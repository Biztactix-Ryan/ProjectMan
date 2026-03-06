"""Tests for scoping support."""

import yaml
from projectman.store import Store
from projectman.scoper import scope, auto_scope


def test_scope_story(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "As a user, I want authentication")
    result = scope(store, "US-TST-1")
    data = yaml.safe_load(result)
    assert "decomposition_guidance" in data
    assert data["task_count"] == 0


def test_scope_with_existing_tasks(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.create_task("US-TST-1", "Task 1", "Desc")
    result = scope(store, "US-TST-1")
    data = yaml.safe_load(result)
    assert data["task_count"] == 1
    assert len(data["existing_tasks"]) == 1


def test_scope_guidance_includes_depends_on_in_rules(tmp_project):
    """Scoper guidance rules mention depends_on for task ordering."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    result = scope(store, "US-TST-1")
    data = yaml.safe_load(result)
    rules = data["decomposition_guidance"]["rules"]
    assert any("depends_on" in r for r in rules)


def test_scope_guidance_includes_depends_on_in_template(tmp_project):
    """Scoper task_template includes a depends_on field."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    result = scope(store, "US-TST-1")
    data = yaml.safe_load(result)
    template = data["decomposition_guidance"]["task_template"]
    assert "depends_on" in template


def test_auto_scope_full_guidance_includes_depends_on(tmp_project):
    """Full auto-scope guidance includes depends_on in rules and task template."""
    store = Store(tmp_project)
    # No epics or stories → full mode
    result = auto_scope(store, mode="full")
    data = yaml.safe_load(result)
    guidance = data["guidance"]
    assert any("depends_on" in r for r in guidance["rules"])
    assert "depends_on" in guidance["task_template"]


def test_auto_scope_incremental_guidance_includes_depends_on(tmp_project):
    """Incremental auto-scope guidance includes depends_on in rules and task template."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    result = auto_scope(store, mode="incremental")
    data = yaml.safe_load(result)
    guidance = data["decomposition_guidance"]
    assert any("depends_on" in r for r in guidance["rules"])
    assert "depends_on" in guidance["task_template"]
