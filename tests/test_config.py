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
