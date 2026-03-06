"""Tests for config discovery and loading."""

import pytest
from pathlib import Path

from projectman.config import find_project_root, load_config, save_config, project_dir
from projectman.models import ProjectConfig


def test_find_project_root(tmp_project):
    root = find_project_root(tmp_project)
    assert root == tmp_project


def test_find_project_root_from_subdir(tmp_project):
    subdir = tmp_project / "src" / "deep"
    subdir.mkdir(parents=True)
    root = find_project_root(subdir)
    assert root == tmp_project


def test_find_project_root_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_project_root(tmp_path)


def test_load_config(tmp_project):
    config = load_config(tmp_project)
    assert config.name == "test-project"
    assert config.prefix == "TST"


def test_save_config(tmp_project):
    config = load_config(tmp_project)
    config.next_story_id = 5
    save_config(config, tmp_project)
    reloaded = load_config(tmp_project)
    assert reloaded.next_story_id == 5


def test_project_dir(tmp_project):
    pdir = project_dir(tmp_project)
    assert pdir == tmp_project / ".project"


def test_auto_commit_config_default(tmp_project):
    """auto_commit defaults to False when not in config.yaml."""
    config = load_config(tmp_project)
    assert config.auto_commit is False


def test_auto_commit_config_roundtrip(tmp_project):
    """auto_commit can be enabled and persists through save/load."""
    config = load_config(tmp_project)
    assert config.auto_commit is False

    config.auto_commit = True
    save_config(config, tmp_project)

    reloaded = load_config(tmp_project)
    assert reloaded.auto_commit is True


def test_auto_commit_config_disable_roundtrip(tmp_project):
    """auto_commit can be toggled back to False."""
    config = load_config(tmp_project)
    config.auto_commit = True
    save_config(config, tmp_project)

    config = load_config(tmp_project)
    config.auto_commit = False
    save_config(config, tmp_project)

    reloaded = load_config(tmp_project)
    assert reloaded.auto_commit is False
