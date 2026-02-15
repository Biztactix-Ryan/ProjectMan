"""Tests for MCP server tool functions."""

import pytest
import os
import yaml

from projectman.store import Store
from projectman.indexer import write_index


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Change to the project directory so server tools can find it."""
    monkeypatch.chdir(tmp_project)


def test_pm_status(tmp_project):
    from projectman.server import pm_status
    result = pm_status()
    data = yaml.safe_load(result)
    assert data["project"] == "test-project"
    assert data["stories"] == 0


def test_pm_create_story(tmp_project):
    from projectman.server import pm_create_story
    result = pm_create_story("My Story", "Description here")
    data = yaml.safe_load(result)
    assert data["created"]["id"] == "US-TST-1"


def test_pm_get(tmp_project):
    from projectman.server import pm_create_story, pm_get
    pm_create_story("My Story", "Body text")
    result = pm_get("US-TST-1")
    data = yaml.safe_load(result)
    assert data["title"] == "My Story"
    assert "Body text" in data["body"]


def test_pm_create_task(tmp_project):
    from projectman.server import pm_create_story, pm_create_task
    pm_create_story("Story", "Desc")
    result = pm_create_task("US-TST-1", "Task 1", "Task desc")
    data = yaml.safe_load(result)
    assert data["created"]["id"] == "US-TST-1-1"


def test_pm_update(tmp_project):
    from projectman.server import pm_create_story, pm_update
    pm_create_story("Story", "Desc")
    result = pm_update("US-TST-1", status="active")
    data = yaml.safe_load(result)
    assert data["updated"]["status"] == "active"


def test_pm_archive(tmp_project):
    from projectman.server import pm_create_story, pm_archive
    pm_create_story("Story", "Desc")
    result = pm_archive("US-TST-1")
    assert "archived" in result


def test_pm_active(tmp_project):
    from projectman.server import pm_create_story, pm_update, pm_active
    pm_create_story("Story", "Desc")
    pm_update("US-TST-1", status="active")
    result = pm_active()
    data = yaml.safe_load(result)
    assert len(data["active_stories"]) == 1


def test_pm_burndown(tmp_project):
    from projectman.server import pm_create_story, pm_burndown
    pm_create_story("Story", "Desc", points=5)
    result = pm_burndown()
    data = yaml.safe_load(result)
    assert data["total_points"] == 5


def test_pm_search(tmp_project):
    from projectman.server import pm_create_story, pm_search
    pm_create_story("Authentication system", "Login and signup flow")
    result = pm_search("auth")
    data = yaml.safe_load(result)
    assert len(data) >= 1
