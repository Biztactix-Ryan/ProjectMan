"""Tests for create_feature_branch() and list_feature_branches() (US-PRJ-7-7).

Verifies task-linked feature branching in subprojects:
1. Branch naming convention: pm/{task_id}/{slugified-description}
2. Refuses to branch from dirty working tree
3. Refuses to branch from anything other than the deploy branch
4. list_feature_branches() returns all pm/* branches
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import (
    create_feature_branch,
    list_feature_branches,
    _slugify,
    _get_deploy_branch,
)


# ─── Helpers ──────────────────────────────────────────────────────

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
}


def _git(args, cwd, check=True):
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


def _branch(cwd):
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_env(tmp_path):
    """Hub with one subproject 'api' on its deploy branch (main).

    Layout::

        tmp_path/
            api.git/          bare remote
            hub/              hub working copy
                projects/api/ submodule checkout (on main)
                .project/     PM metadata
    """
    # Create subproject bare remote
    api_bare = tmp_path / "api.git"
    api_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], api_bare)

    api_work = tmp_path / "api-work"
    _git(["clone", str(api_bare), str(api_work)], tmp_path)
    (api_work / "README.md").write_text("# api\n")
    _git(["add", "."], api_work)
    _git(["commit", "-m", "initial api"], api_work)
    _git(["push", "-u", "origin", "main"], api_work)

    # Create hub
    hub = tmp_path / "hub"
    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # PM structure
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects", "dashboards"):
        (proj / d).mkdir()

    hub_config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "projects": ["api"],
    }
    (proj / "config.yaml").write_text(yaml.dump(hub_config))

    # Subproject PM config with deploy_branch
    api_pm = proj / "projects" / "api"
    api_pm.mkdir()
    api_pm_config = {
        "name": "api",
        "prefix": "API",
        "hub": False,
        "next_story_id": 1,
        "deploy_branch": "main",
        "projects": [],
    }
    (api_pm / "config.yaml").write_text(yaml.dump(api_pm_config))

    # Add submodule
    _git(
        ["submodule", "add", str(api_bare), "projects/api"],
        hub,
    )
    _git(
        ["config", "-f", ".gitmodules",
         "submodule.projects/api.branch", "main"],
        hub,
    )
    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    return {"hub": hub, "api_bare": api_bare}


# ─── Tests: _slugify ─────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert _slugify("add auth endpoint") == "add-auth-endpoint"

    def test_special_chars(self):
        assert _slugify("Fix bug #123!") == "fix-bug-123"

    def test_leading_trailing(self):
        assert _slugify("  --hello--  ") == "hello"

    def test_consecutive_separators(self):
        assert _slugify("a   b///c") == "a-b-c"

    def test_empty(self):
        assert _slugify("---") == ""


# ─── Tests: _get_deploy_branch ───────────────────────────────────


class TestGetDeployBranch:
    def test_reads_from_pm_config(self, hub_env):
        hub = hub_env["hub"]
        assert _get_deploy_branch("api", hub) == "main"

    def test_custom_deploy_branch(self, hub_env):
        hub = hub_env["hub"]
        pm_config = hub / ".project" / "projects" / "api" / "config.yaml"
        data = yaml.safe_load(pm_config.read_text())
        data["deploy_branch"] = "release"
        pm_config.write_text(yaml.dump(data))
        assert _get_deploy_branch("api", hub) == "release"

    def test_fallback_to_main(self, hub_env):
        """Falls back to 'main' when no deploy_branch in config."""
        hub = hub_env["hub"]
        pm_config = hub / ".project" / "projects" / "api" / "config.yaml"
        data = yaml.safe_load(pm_config.read_text())
        del data["deploy_branch"]
        pm_config.write_text(yaml.dump(data))
        # Should fall back to tracking branch from .gitmodules (also 'main')
        assert _get_deploy_branch("api", hub) == "main"


# ─── Tests: create_feature_branch ────────────────────────────────


class TestCreateFeatureBranch:
    def test_creates_branch_with_correct_name(self, hub_env):
        hub = hub_env["hub"]
        result = create_feature_branch("api", "US-API-3-1", "add auth endpoint", root=hub)
        assert result == "pm/US-API-3-1/add-auth-endpoint"
        # Verify we're actually on the new branch
        assert _branch(hub / "projects" / "api") == "pm/US-API-3-1/add-auth-endpoint"

    def test_rejects_dirty_working_tree(self, hub_env):
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        # Make the working tree dirty
        (api_sub / "dirty.txt").write_text("uncommitted\n")

        result = create_feature_branch("api", "US-API-1-1", "some work", root=hub)
        assert result.startswith("error:")
        assert "uncommitted" in result

        # Should still be on main
        assert _branch(api_sub) == "main"

    def test_rejects_not_on_deploy_branch(self, hub_env):
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        # Switch to a different branch first
        _git(["checkout", "-b", "other-branch"], api_sub)

        result = create_feature_branch("api", "US-API-1-1", "some work", root=hub)
        assert result.startswith("error:")
        assert "deploy branch" in result

    def test_rejects_unknown_project(self, hub_env):
        hub = hub_env["hub"]
        result = create_feature_branch("nonexistent", "US-X-1-1", "test", root=hub)
        assert result.startswith("error:")
        assert "not registered" in result

    def test_rejects_not_hub(self, tmp_path):
        """Non-hub project should fail."""
        proj = tmp_path / ".project"
        proj.mkdir()
        config = {
            "name": "solo",
            "prefix": "SOL",
            "hub": False,
            "next_story_id": 1,
            "projects": [],
        }
        (proj / "config.yaml").write_text(yaml.dump(config))

        result = create_feature_branch("api", "US-API-1-1", "test", root=tmp_path)
        assert result.startswith("error:")
        assert "not a hub" in result

    def test_rejects_empty_slug(self, hub_env):
        hub = hub_env["hub"]
        result = create_feature_branch("api", "US-API-1-1", "---", root=hub)
        assert result.startswith("error:")
        assert "empty slug" in result

    def test_multiple_branches_from_deploy(self, hub_env):
        """Can create a branch, return to deploy, and create another."""
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        b1 = create_feature_branch("api", "US-API-1-1", "first task", root=hub)
        assert b1 == "pm/US-API-1-1/first-task"

        # Go back to deploy branch
        _git(["checkout", "main"], api_sub)

        b2 = create_feature_branch("api", "US-API-1-2", "second task", root=hub)
        assert b2 == "pm/US-API-1-2/second-task"
        assert _branch(api_sub) == "pm/US-API-1-2/second-task"


# ─── Tests: list_feature_branches ────────────────────────────────


class TestListFeatureBranches:
    def test_no_branches(self, hub_env):
        hub = hub_env["hub"]
        assert list_feature_branches("api", root=hub) == []

    def test_lists_pm_branches(self, hub_env):
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        # Create a couple of feature branches
        create_feature_branch("api", "US-API-1-1", "first", root=hub)
        _git(["checkout", "main"], api_sub)
        create_feature_branch("api", "US-API-1-2", "second", root=hub)
        _git(["checkout", "main"], api_sub)

        branches = list_feature_branches("api", root=hub)
        assert len(branches) == 2
        assert "pm/US-API-1-1/first" in branches
        assert "pm/US-API-1-2/second" in branches

    def test_ignores_non_pm_branches(self, hub_env):
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        # Create a pm branch and a non-pm branch
        create_feature_branch("api", "US-API-1-1", "task", root=hub)
        _git(["checkout", "main"], api_sub)
        _git(["checkout", "-b", "feature/manual"], api_sub)
        _git(["checkout", "main"], api_sub)

        branches = list_feature_branches("api", root=hub)
        assert branches == ["pm/US-API-1-1/task"]

    def test_missing_project(self, hub_env):
        hub = hub_env["hub"]
        assert list_feature_branches("nonexistent", root=hub) == []

    def test_sorted_output(self, hub_env):
        hub = hub_env["hub"]
        api_sub = hub / "projects" / "api"

        create_feature_branch("api", "US-API-3-1", "zebra", root=hub)
        _git(["checkout", "main"], api_sub)
        create_feature_branch("api", "US-API-1-1", "alpha", root=hub)
        _git(["checkout", "main"], api_sub)

        branches = list_feature_branches("api", root=hub)
        assert branches == ["pm/US-API-1-1/alpha", "pm/US-API-3-1/zebra"]
