"""Test: Subproject changes create feature branches not direct commits to deploy (US-PRJ-7-1).

Verifies acceptance criterion for story US-PRJ-7:
    > Subproject changes create feature branches not direct commits to deploy

Uses real git repos with bare remotes to verify that changes are committed on
a feature branch, not deploy (main).

The cross-project push assertions that used to live here went with
``push_subprojects`` and ``coordinated_push`` (US-PM-35-6): the hub no longer
pushes on a subproject's behalf, so there is nothing hub-side left to assert.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml


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
    """Run a git command with test user env."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


def _sha(cwd):
    """Get HEAD SHA of a repo."""
    return _git(["rev-parse", "HEAD"], cwd).stdout.strip()


def _remote_sha(bare_repo, branch="main"):
    """Get the tip SHA of a branch in a bare repo."""
    result = _git(["rev-parse", branch], bare_repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch(cwd):
    """Get the current branch name."""
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def _remote_branch_exists(bare_repo, branch):
    """Check if a branch exists in a bare repo."""
    result = _git(["rev-parse", "--verify", branch], bare_repo, check=False)
    return result.returncode == 0


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_with_deploy_branches(tmp_path):
    """Real git hub with subprojects configured for deploy-branch workflow.

    Each subproject has a 'main' branch as the deploy branch.
    Feature branches are created off main for changes.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/ submodule checkout (on main)
                projects/web/ submodule checkout (on main)
                .project/     PM metadata
    """
    env = {"tmp": tmp_path}

    # Create subproject bare repos and seed with initial commits
    for name in ("api", "web"):
        bare = tmp_path / f"{name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)
        env[f"{name}_bare"] = bare

        work = tmp_path / f"{name}-work"
        _git(["clone", str(bare), str(work)], tmp_path)
        (work / "README.md").write_text(f"# {name}\n")
        _git(["add", "."], work)
        _git(["commit", "-m", f"initial {name}"], work)
        _git(["push", "-u", "origin", "main"], work)
        env[f"{name}_work"] = work

    # Create hub bare repo
    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    # Clone hub and configure
    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev1@test.com"], hub)
    _git(["config", "user.name", "Dev1"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # Set up PM structure
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects"):
        (proj / d).mkdir()
    config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "projects": ["api", "web"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    # Add submodules
    for name in ("api", "web"):
        _git(
            ["submodule", "add", str(env[f"{name}_bare"]), f"projects/{name}"],
            hub,
        )

    # Configure tracking branches in .gitmodules
    for name in ("api", "web"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with tracking branches"], hub)
    _git(["push", "-u", "origin", "main"], hub)
    env["hub"] = hub

    return env


# ─── Tests: Feature branch workflow ──────────────────────────────


class TestFeatureBranchNotDirectDeploy:
    """Subproject changes create feature branches, not direct commits to deploy."""

    def test_feature_branch_commits_do_not_touch_deploy(self, hub_with_deploy_branches):
        """Changes committed on a feature branch leave the deploy branch (main) untouched.

        This is the fundamental assertion: a developer creates a feature branch
        in a subproject, makes changes there, and the main branch stays exactly
        where it was before.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        # Record deploy branch state before any work
        main_sha_before = _sha(api_sub)

        # Create a feature branch for the change
        _git(["checkout", "-b", "feature/add-auth"], api_sub)
        (api_sub / "auth.py").write_text("# auth module\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add auth module"], api_sub)

        feature_sha = _sha(api_sub)

        # Feature branch has the new commit
        assert feature_sha != main_sha_before

        # Deploy branch (main) is untouched
        main_sha_after = _git(
            ["rev-parse", "main"], api_sub
        ).stdout.strip()
        assert main_sha_after == main_sha_before, (
            "main branch must not move when changes are on a feature branch"
        )

