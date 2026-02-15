"""Tests for hub mode -- registry and rollup."""

import shutil

import pytest
import yaml
from pathlib import Path

from projectman.hub.registry import list_projects, repair, _init_subproject
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
    # Manually create a subproject's source dir and PM data in hub
    sub_path = tmp_hub / "projects" / "sub1"
    sub_path.mkdir(parents=True)

    pm_dir = tmp_hub / ".project" / "projects" / "sub1"
    pm_dir.mkdir(parents=True)
    (pm_dir / "stories").mkdir()
    (pm_dir / "tasks").mkdir()

    config = {
        "name": "sub1",
        "prefix": "SUB",
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Register in hub config
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("sub1")
    save_config(hub_config, tmp_hub)

    # Create a story in subproject using hub root + project_dir
    sub_store = Store(tmp_hub, project_dir=pm_dir)
    sub_store.create_story("Sub Story", "Desc", points=3)

    # Rollup
    data = rollup(tmp_hub)
    assert data["total_stories"] == 1
    assert data["total_points"] == 3


# ─── Helper ──────────────────────────────────────────────────────


def _register_subproject(hub_root, name, prefix="SUB"):
    """Set up a subproject with source dir, PM data dir, and hub config entry."""
    sub_path = hub_root / "projects" / name
    sub_path.mkdir(parents=True, exist_ok=True)

    pm_dir = hub_root / ".project" / "projects" / name
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "stories").mkdir(exist_ok=True)
    (pm_dir / "tasks").mkdir(exist_ok=True)
    (pm_dir / "epics").mkdir(exist_ok=True)

    config = {
        "name": name,
        "prefix": prefix,
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    from projectman.config import load_config, save_config
    hub_config = load_config(hub_root)
    if name not in hub_config.projects:
        hub_config.projects.append(name)
        save_config(hub_config, hub_root)

    return pm_dir


# ─── list_projects with new layout ──────────────────────────────


def test_list_projects_with_registered_projects(tmp_hub):
    """list_projects returns correct info for projects at new hub layout."""
    _register_subproject(tmp_hub, "api", prefix="API")

    projects = list_projects(tmp_hub)
    assert len(projects) == 1
    assert projects[0]["name"] == "api"
    assert projects[0]["exists"] is True
    assert projects[0]["initialized"] is True


def test_list_projects_missing_source_dir(tmp_hub):
    """Project registered but source dir deleted -- exists=False, initialized=True."""
    _register_subproject(tmp_hub, "gone")
    # Remove the source directory but keep PM data
    shutil.rmtree(tmp_hub / "projects" / "gone")

    projects = list_projects(tmp_hub)
    assert len(projects) == 1
    assert projects[0]["exists"] is False
    assert projects[0]["initialized"] is True


# ─── Migration path in repair() ─────────────────────────────────


def test_repair_migrates_old_style_data(tmp_hub):
    """repair() moves PM data from projects/{name}/.project/ to hub .project/projects/{name}/."""
    from projectman.config import load_config, save_config

    # Register a project in the hub config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("legacy")
    save_config(hub_config, tmp_hub)

    # Create old-style layout: projects/legacy/.project/ with config + a story
    sub_path = tmp_hub / "projects" / "legacy"
    old_pm = sub_path / ".project"
    old_pm.mkdir(parents=True)
    (old_pm / "stories").mkdir()
    (old_pm / "tasks").mkdir()

    old_config = {
        "name": "legacy",
        "prefix": "LEG",
        "description": "",
        "hub": False,
        "next_story_id": 2,
        "projects": [],
    }
    with open(old_pm / "config.yaml", "w") as f:
        yaml.dump(old_config, f)
    (old_pm / "stories" / "US-LEG-1.md").write_text(
        "---\nid: US-LEG-1\ntitle: Old Story\nstatus: backlog\n"
        "priority: should\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\nOld story body\n"
    )

    # New-style PM dir should NOT exist yet
    new_pm = tmp_hub / ".project" / "projects" / "legacy"
    assert not (new_pm / "config.yaml").exists()

    # Run repair
    report = repair(tmp_hub)

    # Migration should have happened
    assert "migrated PM data" in report
    assert (new_pm / "config.yaml").exists()
    assert (new_pm / "stories" / "US-LEG-1.md").exists()

    # Verify migrated config is intact
    with open(new_pm / "config.yaml") as f:
        migrated = yaml.safe_load(f)
    assert migrated["prefix"] == "LEG"
    assert migrated["next_story_id"] == 2


def test_repair_discovers_unregistered_projects(tmp_hub):
    """repair() auto-registers directories in projects/ not in hub config."""
    # Create a project dir that is NOT in the hub config
    (tmp_hub / "projects" / "new-thing").mkdir(parents=True)

    report = repair(tmp_hub)

    assert "new-thing" in report
    assert "Discovered" in report

    # Verify it was registered
    from projectman.config import load_config
    hub_config = load_config(tmp_hub)
    assert "new-thing" in hub_config.projects


def test_repair_initializes_pm_data_for_new_projects(tmp_hub):
    """repair() creates PM data structure at hub .project/projects/{name}/."""
    (tmp_hub / "projects" / "fresh").mkdir(parents=True)

    repair(tmp_hub)

    pm_dir = tmp_hub / ".project" / "projects" / "fresh"
    assert (pm_dir / "config.yaml").exists()
    assert (pm_dir / "stories").is_dir()
    assert (pm_dir / "tasks").is_dir()


# ─── _init_subproject ────────────────────────────────────────────


def test_init_subproject_creates_structure(tmp_path):
    """_init_subproject creates config, stories/, tasks/, epics/ at target."""
    target = tmp_path / "pm_data" / "myproj"
    _init_subproject(target, "myproj")

    assert target.is_dir()
    assert (target / "config.yaml").exists()
    assert (target / "stories").is_dir()
    assert (target / "tasks").is_dir()
    assert (target / "epics").is_dir()
    assert (target / "index.yaml").exists()

    with open(target / "config.yaml") as f:
        config = yaml.safe_load(f)
    assert config["name"] == "myproj"
    assert config["hub"] is False
    assert config["next_story_id"] == 1
