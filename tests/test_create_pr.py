"""Test: create_pr() and get_pr_status() in hub/registry.py (US-PRJ-7-8).

Verifies that:
1. create_pr() validates pm/* branch, pushes, and calls gh pr create
2. create_pr() blocks direct push from deploy branch
3. create_pr() handles gh CLI errors (not installed, not authenticated, no remote)
4. get_pr_status() lists open PRs targeting the deploy branch via gh pr list
5. get_pr_status() handles gh CLI errors gracefully
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

from projectman.hub.registry import create_pr, get_pr_status


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


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_with_pm_branch(tmp_path):
    """Hub with a subproject on a pm/* feature branch, ready for PR creation.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            hub/              hub working copy
                projects/api/ submodule on pm/US-TST-1-1/add-auth
                .project/     PM metadata
    """
    # Create subproject bare repo with initial commit
    bare = tmp_path / "api.git"
    bare.mkdir()
    _git(["init", "--bare", "-b", "main"], bare)

    work = tmp_path / "api-work"
    _git(["clone", str(bare), str(work)], tmp_path)
    (work / "README.md").write_text("# api\n")
    _git(["add", "."], work)
    _git(["commit", "-m", "initial api"], work)
    _git(["push", "-u", "origin", "main"], work)

    # Create hub (not bare — just a working copy with .project)
    hub = tmp_path / "hub"
    hub.mkdir()
    _git(["init", "-b", "main"], hub)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # Set up PM structure
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects"):
        (proj / d).mkdir()

    # Per-project PM config with deploy_branch
    api_pm = proj / "projects" / "api"
    api_pm.mkdir()
    (api_pm / "config.yaml").write_text(yaml.dump({"deploy_branch": "main"}))

    config = {
        "name": "test-hub",
        "prefix": "TST",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "projects": ["api"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    # Add submodule
    _git(
        ["submodule", "add", str(bare), "projects/api"],
        hub,
    )
    _git(
        ["config", "-f", ".gitmodules",
         "submodule.projects/api.branch", "main"],
        hub,
    )
    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodule"], hub)

    # Create pm/* feature branch in the subproject with a change
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "pm/US-TST-1-1/add-auth"], api_sub)
    (api_sub / "auth.py").write_text("class AuthService: pass\n")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "add auth service"], api_sub)

    return {
        "tmp": tmp_path,
        "hub": hub,
        "bare": bare,
        "branch": "pm/US-TST-1-1/add-auth",
    }


# ─── Tests: create_pr() ──────────────────────────────────────────


def _mock_subprocess(push_result=None, gh_result=None):
    """Build a side_effect that delegates real git calls but mocks push/gh.

    Any call starting with ``["git", "push", ...]`` returns *push_result*.
    Any call starting with ``["gh", ...]`` returns *gh_result*.
    All other calls (e.g. ``git rev-parse``) pass through to real subprocess.
    """
    real_run = subprocess.run

    def _side_effect(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            if gh_result is None:
                raise FileNotFoundError("gh")
            return gh_result
        if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "push":
            if push_result is None:
                raise FileNotFoundError("git")
            return push_result
        return real_run(cmd, *args, **kwargs)

    return _side_effect


class TestCreatePr:
    """create_pr() pushes a pm/* branch and creates a PR via gh CLI."""

    def test_success_returns_url_and_number(self, hub_with_pm_branch):
        """On success, create_pr returns the PR URL and number."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/api/pull/42\n",
            stderr="",
        )

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, pr_ok)):
            result = create_pr("api", "Add auth", "Auth service implementation", root=hub)

        assert "error" not in result
        assert result["url"] == "https://github.com/owner/api/pull/42"
        assert result["number"] == 42

    def test_pushes_feature_branch_before_pr(self, hub_with_pm_branch):
        """create_pr pushes the feature branch to origin before creating the PR."""
        hub = hub_with_pm_branch["hub"]
        branch = hub_with_pm_branch["branch"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(returncode=0, stdout="https://github.com/owner/api/pull/1\n")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, pr_ok)) as mock_run:
            create_pr("api", "title", "body", root=hub)

        # Find the push call
        push_calls = [c for c in mock_run.call_args_list
                      if c[0][0][0] == "git" and c[0][0][1] == "push"]
        assert len(push_calls) == 1
        assert branch in push_calls[0][0][0]

    def test_creates_pr_targeting_deploy_branch(self, hub_with_pm_branch):
        """The gh pr create command targets the deploy branch as --base."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(returncode=0, stdout="https://github.com/owner/api/pull/1\n")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, pr_ok)) as mock_run:
            create_pr("api", "title", "body", root=hub)

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        assert len(gh_calls) == 1
        cmd = gh_calls[0][0][0]
        assert cmd[0:3] == ["gh", "pr", "create"]
        base_idx = cmd.index("--base")
        assert cmd[base_idx + 1] == "main"

    def test_draft_flag_adds_draft_option(self, hub_with_pm_branch):
        """When draft=True, --draft is passed to gh pr create."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(returncode=0, stdout="https://github.com/owner/api/pull/1\n")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, pr_ok)) as mock_run:
            create_pr("api", "title", "body", root=hub, draft=True)

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        assert "--draft" in gh_calls[0][0][0]

    def test_no_draft_flag_by_default(self, hub_with_pm_branch):
        """Without draft=True, --draft is not passed."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(returncode=0, stdout="https://github.com/owner/api/pull/1\n")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, pr_ok)) as mock_run:
            create_pr("api", "title", "body", root=hub)

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        assert "--draft" not in gh_calls[0][0][0]


class TestCreatePrValidation:
    """create_pr() validates branch and project before proceeding."""

    def test_blocks_non_pm_branch(self, hub_with_pm_branch):
        """create_pr refuses if the current branch is not a pm/* branch."""
        hub = hub_with_pm_branch["hub"]
        api_sub = hub / "projects" / "api"

        # Switch to deploy branch (not a pm/* branch)
        _git(["checkout", "main"], api_sub)

        result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "not a pm/* feature branch" in result["error"]

    def test_blocks_deploy_branch(self, hub_with_pm_branch):
        """create_pr refuses if on the deploy branch directly."""
        hub = hub_with_pm_branch["hub"]
        api_sub = hub / "projects" / "api"
        _git(["checkout", "main"], api_sub)

        result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "not a pm/* feature branch" in result["error"]

    def test_error_on_unknown_project(self, hub_with_pm_branch):
        """create_pr returns error for unregistered project."""
        hub = hub_with_pm_branch["hub"]

        result = create_pr("nonexistent", "title", "body", root=hub)

        assert "error" in result
        assert "not registered" in result["error"]

    def test_error_on_non_hub(self, tmp_project):
        """create_pr returns error if not a hub project."""
        result = create_pr("api", "title", "body", root=tmp_project)

        assert "error" in result
        assert "not a hub project" in result["error"]

    def test_error_on_missing_project_dir(self, hub_with_pm_branch):
        """create_pr returns error if project directory doesn't exist."""
        hub = hub_with_pm_branch["hub"]

        # Register a project that doesn't have a directory
        config_path = hub / ".project" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["projects"].append("ghost")
        config_path.write_text(yaml.dump(config))

        result = create_pr("ghost", "title", "body", root=hub)

        assert "error" in result
        assert "directory not found" in result["error"]

    def test_error_on_detached_head(self, hub_with_pm_branch):
        """create_pr returns error when subproject is in detached HEAD."""
        hub = hub_with_pm_branch["hub"]
        api_sub = hub / "projects" / "api"

        # Detach HEAD
        sha = _git(["rev-parse", "HEAD"], api_sub).stdout.strip()
        _git(["checkout", sha], api_sub)

        result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "detached HEAD" in result["error"]


class TestCreatePrErrorHandling:
    """create_pr() handles gh CLI errors gracefully."""

    def test_gh_not_installed(self, hub_with_pm_branch):
        """create_pr returns clear error when gh is not found."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, None)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "not installed" in result["error"]

    def test_gh_not_authenticated(self, hub_with_pm_branch):
        """create_pr returns clear error when gh is not authenticated."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        gh_fail = MagicMock(returncode=1, stderr="gh auth login required")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, gh_fail)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "not authenticated" in result["error"]

    def test_push_failure(self, hub_with_pm_branch):
        """create_pr returns error when git push fails."""
        hub = hub_with_pm_branch["hub"]

        push_fail = MagicMock(returncode=1, stderr="remote: Permission denied")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_fail, None)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "failed to push" in result["error"]

    def test_git_push_not_installed(self, hub_with_pm_branch):
        """create_pr returns error when git push raises FileNotFoundError."""
        hub = hub_with_pm_branch["hub"]

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, None)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "not installed" in result["error"]

    def test_no_remote(self, hub_with_pm_branch):
        """create_pr returns error when push fails due to no remote."""
        hub = hub_with_pm_branch["hub"]

        push_fail = MagicMock(
            returncode=1,
            stderr="fatal: 'origin' does not appear to be a git repository",
        )

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_fail, None)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "failed to push" in result["error"]

    def test_gh_generic_error(self, hub_with_pm_branch):
        """create_pr returns the gh stderr on generic failure."""
        hub = hub_with_pm_branch["hub"]

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        gh_fail = MagicMock(returncode=1, stderr="some unexpected error")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(push_ok, gh_fail)):
            result = create_pr("api", "title", "body", root=hub)

        assert "error" in result
        assert "gh pr create failed" in result["error"]
        assert "unexpected error" in result["error"]


# ─── Tests: get_pr_status() ──────────────────────────────────────


class TestGetPrStatus:
    """get_pr_status() checks open PRs targeting the deploy branch."""

    def test_returns_open_prs(self, hub_with_pm_branch):
        """get_pr_status returns a list of open PRs."""
        hub = hub_with_pm_branch["hub"]

        prs_data = [
            {
                "number": 42,
                "title": "Add auth",
                "state": "OPEN",
                "headRefName": "pm/US-TST-1-1/add-auth",
            },
            {
                "number": 43,
                "title": "Add logging",
                "state": "OPEN",
                "headRefName": "pm/US-TST-1-2/add-logging",
            },
        ]

        gh_ok = MagicMock(returncode=0, stdout=json.dumps(prs_data))

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_ok)):
            result = get_pr_status("api", root=hub)

        assert "error" not in result
        assert result["deploy_branch"] == "main"
        assert len(result["prs"]) == 2
        assert result["prs"][0]["number"] == 42
        assert result["prs"][1]["headRefName"] == "pm/US-TST-1-2/add-logging"

    def test_uses_correct_base_branch(self, hub_with_pm_branch):
        """get_pr_status uses the deploy branch as --base in gh pr list."""
        hub = hub_with_pm_branch["hub"]

        gh_ok = MagicMock(returncode=0, stdout="[]")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_ok)) as mock_run:
            get_pr_status("api", root=hub)

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        assert len(gh_calls) == 1
        cmd = gh_calls[0][0][0]
        assert cmd[0:3] == ["gh", "pr", "list"]
        base_idx = cmd.index("--base")
        assert cmd[base_idx + 1] == "main"

    def test_empty_pr_list(self, hub_with_pm_branch):
        """get_pr_status returns empty list when no PRs exist."""
        hub = hub_with_pm_branch["hub"]

        gh_ok = MagicMock(returncode=0, stdout="[]")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_ok)):
            result = get_pr_status("api", root=hub)

        assert "error" not in result
        assert result["prs"] == []

    def test_empty_stdout(self, hub_with_pm_branch):
        """get_pr_status handles empty stdout gracefully."""
        hub = hub_with_pm_branch["hub"]

        gh_ok = MagicMock(returncode=0, stdout="")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_ok)):
            result = get_pr_status("api", root=hub)

        assert "error" not in result
        assert result["prs"] == []


class TestGetPrStatusValidation:
    """get_pr_status() validates project and hub context."""

    def test_error_on_non_hub(self, tmp_project):
        """get_pr_status returns error if not a hub project."""
        result = get_pr_status("api", root=tmp_project)

        assert "error" in result
        assert "not a hub project" in result["error"]

    def test_error_on_unknown_project(self, hub_with_pm_branch):
        """get_pr_status returns error for unregistered project."""
        hub = hub_with_pm_branch["hub"]

        result = get_pr_status("nonexistent", root=hub)

        assert "error" in result
        assert "not registered" in result["error"]

    def test_error_on_missing_dir(self, hub_with_pm_branch):
        """get_pr_status returns error if project directory is missing."""
        hub = hub_with_pm_branch["hub"]

        config_path = hub / ".project" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["projects"].append("ghost")
        config_path.write_text(yaml.dump(config))

        result = get_pr_status("ghost", root=hub)

        assert "error" in result
        assert "directory not found" in result["error"]


class TestGetPrStatusErrorHandling:
    """get_pr_status() handles gh CLI errors gracefully."""

    def test_gh_not_installed(self, hub_with_pm_branch):
        """get_pr_status returns clear error when gh is not found."""
        hub = hub_with_pm_branch["hub"]

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, None)):
            result = get_pr_status("api", root=hub)

        assert "error" in result
        assert "not installed" in result["error"]

    def test_gh_not_authenticated(self, hub_with_pm_branch):
        """get_pr_status returns clear error when gh is not authenticated."""
        hub = hub_with_pm_branch["hub"]

        gh_fail = MagicMock(returncode=1, stderr="gh auth login required")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_fail)):
            result = get_pr_status("api", root=hub)

        assert "error" in result
        assert "not authenticated" in result["error"]

    def test_gh_generic_error(self, hub_with_pm_branch):
        """get_pr_status returns the gh stderr on generic failure."""
        hub = hub_with_pm_branch["hub"]

        gh_fail = MagicMock(returncode=1, stderr="something went wrong")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_fail)):
            result = get_pr_status("api", root=hub)

        assert "error" in result
        assert "gh pr list failed" in result["error"]

    def test_malformed_json_returns_empty_prs(self, hub_with_pm_branch):
        """get_pr_status returns empty list when gh output is malformed JSON."""
        hub = hub_with_pm_branch["hub"]

        gh_ok = MagicMock(returncode=0, stdout="not valid json{{")

        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_subprocess(None, gh_ok)):
            result = get_pr_status("api", root=hub)

        assert "error" not in result
        assert result["prs"] == []
