"""Test: update_hub_refs_after_merge() — PR-based hub ref sync (US-PRJ-7-9).

Verifies that hub submodule refs only advance when gh reports all PRs
targeting the deploy branch are merged (no open PRs remain).

Scenarios:
1. All PRs merged, no open PRs → refs updated
2. Open PRs pending → project skipped
3. No merged PRs → project unchanged
4. Mixed: some projects updated, some skipped
5. Ref log records updates with source='pr_merge'
6. Non-hub project → error
7. Unknown project name → error
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from projectman.hub.registry import update_hub_refs_after_merge


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


def _merge_feature_into_main(bare_repo, feature_branch, tmp_path, name):
    """Simulate a PR merge by merging a feature branch into main in a bare repo."""
    merge_work = tmp_path / f"{name}-merge-work"
    _git(["clone", str(bare_repo), str(merge_work)], tmp_path)
    _git(["config", "user.email", "merge@test.com"], merge_work)
    _git(["config", "user.name", "Merge"], merge_work)
    _git(["checkout", "main"], merge_work)
    _git(["merge", f"origin/{feature_branch}", "--no-ff", "-m",
          f"Merge {feature_branch} into main"], merge_work)
    _git(["push", "origin", "main"], merge_work)
    return _sha(merge_work)


def _mock_gh_for_projects(gh_responses: dict):
    """Build a side_effect that delegates git calls but mocks gh pr list.

    gh_responses maps (project_name, state) to a list of PR dicts, e.g.:
        {("api", "open"): [], ("api", "merged"): [{"number": 1, ...}]}

    The project is identified by the cwd of the subprocess call.
    """
    real_run = subprocess.run

    def _side_effect(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            cwd = kwargs.get("cwd", "")
            project_name = Path(cwd).name if cwd else ""
            # Extract --state value from command
            state = "open"
            for i, arg in enumerate(cmd):
                if arg == "--state" and i + 1 < len(cmd):
                    state = cmd[i + 1]
                    break

            key = (project_name, state)
            prs = gh_responses.get(key, [])
            return MagicMock(
                returncode=0,
                stdout=json.dumps(prs),
                stderr="",
            )
        return real_run(cmd, *args, **kwargs)

    return _side_effect


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_env(tmp_path):
    """Real git hub with subprojects, feature branches pushed.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/ submodule (feature branch pushed)
                projects/web/ submodule (feature branch pushed)
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

    # Create hub bare repo
    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    # Clone hub and configure
    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # Set up PM structure
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects", "dashboards"):
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

    # Add submodules tracking main
    for name in ("api", "web"):
        _git(
            ["submodule", "add", str(env[f"{name}_bare"]), f"projects/{name}"],
            hub,
        )
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
        _git(["config", "protocol.file.allow", "always"], hub / "projects" / name)

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    # Record initial submodule SHAs
    env["api_sha_before"] = _sha(hub / "projects" / "api")
    env["web_sha_before"] = _sha(hub / "projects" / "web")

    # Create feature branches in subprojects and push
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "feature/add-auth"], api_sub)
    (api_sub / "auth.py").write_text("class AuthService: pass\n")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: add auth service"], api_sub)
    _git(["push", "-u", "origin", "feature/add-auth"], api_sub)

    web_sub = hub / "projects" / "web"
    _git(["checkout", "-b", "feature/add-login"], web_sub)
    (web_sub / "login.html").write_text("<form>login</form>\n")
    _git(["add", "."], web_sub)
    _git(["commit", "-m", "web: add login page"], web_sub)
    _git(["push", "-u", "origin", "feature/add-login"], web_sub)

    env["hub"] = hub
    return env


# ─── Tests: Refs updated when all PRs merged ─────────────────────


class TestRefsUpdatedAfterMerge:
    """update_hub_refs_after_merge() updates refs when PRs are merged."""

    def test_updates_refs_when_all_merged_no_open(self, hub_env):
        """All PRs merged, no open PRs → submodule refs advance."""
        hub = hub_env["hub"]
        tmp = hub_env["tmp"]

        # Simulate PR merges on remotes
        _merge_feature_into_main(hub_env["api_bare"], "feature/add-auth", tmp, "api")
        _merge_feature_into_main(hub_env["web_bare"], "feature/add-login", tmp, "web")

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
            ("web", "open"): [],
            ("web", "merged"): [{"number": 2, "title": "Add login", "mergedAt": "2026-02-28T12:00:00Z"}],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            result = update_hub_refs_after_merge(root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 2
        assert result["skipped"] == []
        assert result["unchanged"] == []

        updated_names = [u["project"] for u in result["updated"]]
        assert "api" in updated_names
        assert "web" in updated_names

    def test_single_project_updates_only_that_ref(self, hub_env):
        """Specifying a single project only updates that project's ref."""
        hub = hub_env["hub"]
        tmp = hub_env["tmp"]

        _merge_feature_into_main(hub_env["api_bare"], "feature/add-auth", tmp, "api")

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            result = update_hub_refs_after_merge(projects=["api"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 1
        assert result["updated"][0]["project"] == "api"

    def test_hub_commit_created_on_update(self, hub_env):
        """A hub commit is created when refs are updated."""
        hub = hub_env["hub"]
        tmp = hub_env["tmp"]

        _merge_feature_into_main(hub_env["api_bare"], "feature/add-auth", tmp, "api")

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            update_hub_refs_after_merge(projects=["api"], root=hub)

        commit_msg = _git(["log", "-1", "--format=%s"], hub).stdout.strip()
        assert "hub: update refs after merge" in commit_msg
        assert "api" in commit_msg

    def test_ref_log_records_pr_merge_source(self, hub_env):
        """Ref log entries have source='pr_merge'."""
        hub = hub_env["hub"]
        tmp = hub_env["tmp"]

        _merge_feature_into_main(hub_env["api_bare"], "feature/add-auth", tmp, "api")

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            update_hub_refs_after_merge(projects=["api"], root=hub)

        ref_log_path = hub / ".project" / "ref-log.yaml"
        assert ref_log_path.exists()

        entries = yaml.safe_load(ref_log_path.read_text())
        assert len(entries) == 1
        assert entries[0]["project"] == "api"
        assert entries[0]["source"] == "pr_merge"
        assert entries[0]["old_ref"] != entries[0]["new_ref"]
        assert entries[0]["commit"]  # hub commit SHA recorded


# ─── Tests: Skips when open PRs pending ──────────────────────────


class TestSkipsWithOpenPRs:
    """update_hub_refs_after_merge() skips projects with open PRs."""

    def test_skips_project_with_open_prs(self, hub_env):
        """Open PRs on deploy branch → project is skipped."""
        hub = hub_env["hub"]

        gh = {
            ("api", "open"): [{"number": 3, "title": "WIP: new feature", "headRefName": "feature/wip"}],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            result = update_hub_refs_after_merge(projects=["api"], root=hub)

        assert result["error"] is None
        assert result["updated"] == []
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["project"] == "api"
        assert "open PR" in result["skipped"][0]["reason"]

    def test_no_hub_commit_when_all_skipped(self, hub_env):
        """When all projects are skipped, no hub commit is created."""
        hub = hub_env["hub"]
        commit_before = _sha(hub)

        gh = {
            ("api", "open"): [{"number": 3, "title": "WIP", "headRefName": "feature/wip"}],
            ("api", "merged"): [],
            ("web", "open"): [{"number": 4, "title": "WIP2", "headRefName": "feature/wip2"}],
            ("web", "merged"): [],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            update_hub_refs_after_merge(root=hub)

        commit_after = _sha(hub)
        assert commit_before == commit_after, "no commit should be created when all skipped"


# ─── Tests: Unchanged when no merged PRs ─────────────────────────


class TestUnchangedWhenNoMergedPRs:
    """Projects with no merged PRs are reported as unchanged."""

    def test_no_merged_no_open_is_unchanged(self, hub_env):
        """No PRs at all → project is unchanged."""
        hub = hub_env["hub"]

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            result = update_hub_refs_after_merge(projects=["api"], root=hub)

        assert result["error"] is None
        assert result["updated"] == []
        assert result["skipped"] == []
        assert "api" in result["unchanged"]


# ─── Tests: Mixed results ────────────────────────────────────────


class TestMixedResults:
    """Some projects updated, some skipped, some unchanged."""

    def test_mixed_updated_skipped_unchanged(self, hub_env):
        """api: merged → updated, web: open PRs → skipped."""
        hub = hub_env["hub"]
        tmp = hub_env["tmp"]

        _merge_feature_into_main(hub_env["api_bare"], "feature/add-auth", tmp, "api")

        gh = {
            ("api", "open"): [],
            ("api", "merged"): [{"number": 1, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}],
            ("web", "open"): [{"number": 5, "title": "WIP", "headRefName": "feature/wip"}],
            ("web", "merged"): [],
        }

        from unittest.mock import patch
        with patch("projectman.hub.registry.subprocess.run",
                    side_effect=_mock_gh_for_projects(gh)):
            result = update_hub_refs_after_merge(root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 1
        assert result["updated"][0]["project"] == "api"
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["project"] == "web"


# ─── Tests: Error cases ──────────────────────────────────────────


class TestErrorCases:
    """Error handling for invalid inputs."""

    def test_not_a_hub_project(self, tmp_path):
        """Returns error when called on a non-hub project."""
        proj = tmp_path / ".project"
        proj.mkdir()
        config = {
            "name": "not-a-hub",
            "prefix": "NAH",
            "description": "test",
            "hub": False,
            "next_story_id": 1,
        }
        (proj / "config.yaml").write_text(yaml.dump(config))

        # Need a git repo for find_project_root fallback
        _git(["init"], tmp_path)

        result = update_hub_refs_after_merge(root=tmp_path)
        assert result["error"] == "not a hub project"

    def test_unknown_project_name(self, hub_env):
        """Returns error for unregistered project name."""
        hub = hub_env["hub"]

        result = update_hub_refs_after_merge(projects=["nonexistent"], root=hub)
        assert result["error"] is not None
        assert "nonexistent" in result["error"]
        assert "not registered" in result["error"]
