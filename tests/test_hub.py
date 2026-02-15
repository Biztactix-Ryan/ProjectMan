"""Tests for hub mode -- registry and rollup."""

import pytest
import yaml
from pathlib import Path

from projectman.hub.registry import list_projects
from projectman.hub.rollup import rollup
from projectman.store import Store


def test_list_projects_empty(tmp_hub):
    projects = list_projects(tmp_hub)
    assert projects == []


def test_rollup_empty(tmp_hub):
    data = rollup(tmp_hub)
    assert data["total_stories"] == 0
    assert data["total_points"] == 0


def test_rollup_with_subproject(tmp_hub):
    # Manually create a subproject
    sub_path = tmp_hub / "projects" / "sub1"
    sub_proj = sub_path / ".project"
    sub_proj.mkdir(parents=True)
    (sub_proj / "stories").mkdir()
    (sub_proj / "tasks").mkdir()

    config = {
        "name": "sub1",
        "prefix": "SUB",
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "projects": [],
    }
    with open(sub_proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Register in hub config
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("sub1")
    save_config(hub_config, tmp_hub)

    # Create a story in subproject
    sub_store = Store(sub_path)
    sub_store.create_story("Sub Story", "Desc", points=3)

    # Rollup
    data = rollup(tmp_hub)
    assert data["total_stories"] == 1
    assert data["total_points"] == 3
