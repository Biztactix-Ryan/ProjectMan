"""Test: PR workflow end-to-end (US-PRJ-7-11).

Tests the full PR workflow using real git repos (tmp_hub fixtures):

1. Feature branch creation: create_feature_branch() produces correct naming,
   refuses to branch from non-deploy, refuses on dirty tree
2. PR creation: Mock gh CLI calls, verify correct --base and --head flags
3. Hub ref update: After simulated merge, update_hub_refs_after_merge() moves
   submodule ref forward.  With open PRs, ref stays put.
4. Deploy protection: validate_not_on_deploy_branch() catches direct commits
   to deploy, allows commits on feature branches
5. Multi-project: Simultaneous feature branches in 3 subprojects, PRs created
   for all, hub refs updated only for merged ones
6. Edge cases: No gh installed, subproject has no remote, deploy branch doesn't
   exist on remote
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from projectman.hub.registry import (
    create_feature_branch,
    create_pr,
    update_hub_refs_after_merge,
    validate_not_on_deploy_branch,
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


def _branch(cwd):
    """Get the current branch name."""
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def _remote_sha(bare_repo, branch="main"):
    """Get the tip SHA of a branch in a bare repo."""
    result = _git(["rev-parse", branch], bare_repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _merge_feature_into_main(bare_repo, feature_branch, tmp_path, name):
    """Simulate a PR merge by merging a feature branch into main in a bare repo."""
    merge_work = tmp_path / f"{name}-merge-work"
    _git(["clone", str(bare_repo), str(merge_work)], tmp_path)
    _git(["config", "user.email", "merge@test.com"], merge_work)
    _git(["config", "user.name", "Merge"], merge_work)
    _git(["checkout", "main"], merge_work)
    _git(
        ["merge", f"origin/{feature_branch}", "--no-ff", "-m",
         f"Merge {feature_branch} into main"],
        merge_work,
    )
    _git(["push", "origin", "main"], merge_work)
    return _sha(merge_work)


def _mock_gh(open_prs=None, merged_prs=None):
    """Build a subprocess side_effect that mocks gh but delegates real git calls.

    Args:
        open_prs: List of dicts for ``gh pr list --state open`` response.
        merged_prs: List of dicts for ``gh pr list --state merged`` response.
    """
    real_run = subprocess.run
    open_prs = open_prs or []
    merged_prs = merged_prs or []

    def _side_effect(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            result = MagicMock()
            result.returncode = 0
            # Determine which state is being queried
            if "--state" in cmd:
                idx = cmd.index("--state")
                state = cmd[idx + 1]
                if state == "open":
                    result.stdout = json.dumps(open_prs)
                elif state == "merged":
                    result.stdout = json.dumps(merged_prs)
                else:
                    result.stdout = "[]"
            else:
                result.stdout = "[]"
            result.stderr = ""
            return result
        if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "push":
            push_result = MagicMock(returncode=0, stdout="", stderr="")
            return push_result
        return real_run(cmd, *args, **kwargs)

    return _side_effect


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def hub_two_projects(tmp_path):
    """Hub with two subprojects (api, web), all on main, with bare remotes.

    Feature branches are NOT created — tests do that themselves.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/ submodule on main
                projects/web/ submodule on main
                .project/     PM metadata
    """
    env = {"tmp": tmp_path}

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

    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

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

    # Per-project PM config with deploy_branch
    for name in ("api", "web"):
        pm = proj / "projects" / name
        pm.mkdir()
        (pm / "config.yaml").write_text(yaml.dump({"deploy_branch": "main"}))

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

    # Allow file:// protocol for submodule update
    for name in ("api", "web"):
        _git(["config", "protocol.file.allow", "always"], hub / "projects" / name)

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    env["hub"] = hub
    return env


@pytest.fixture
def hub_three_projects(tmp_path):
    """Hub with three subprojects (api, web, mobile) for multi-project tests."""
    env = {"tmp": tmp_path}

    for name in ("api", "web", "mobile"):
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

    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

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
        "projects": ["api", "web", "mobile"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    for name in ("api", "web", "mobile"):
        pm = proj / "projects" / name
        pm.mkdir()
        (pm / "config.yaml").write_text(yaml.dump({"deploy_branch": "main"}))

    for name in ("api", "web", "mobile"):
        _git(
            ["submodule", "add", str(env[f"{name}_bare"]), f"projects/{name}"],
            hub,
        )
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )

    for name in ("api", "web", "mobile"):
        _git(["config", "protocol.file.allow", "always"], hub / "projects" / name)

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    env["hub"] = hub
    return env


# ─── 1. Feature branch creation ──────────────────────────────────


class TestFeatureBranchCreation:
    """create_feature_branch() produces correct naming and validates preconditions."""

    def test_correct_branch_naming(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        result = create_feature_branch("api", "US-API-1-1", "add auth endpoint", root=hub)

        assert result == "pm/US-API-1-1/add-auth-endpoint"
        assert _branch(hub / "projects" / "api") == "pm/US-API-1-1/add-auth-endpoint"

    def test_refuses_dirty_tree(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        (api_sub / "dirty.txt").write_text("uncommitted\n")

        result = create_feature_branch("api", "US-API-1-1", "test", root=hub)

        assert result.startswith("error:")
        assert "uncommitted" in result
        assert _branch(api_sub) == "main"

    def test_refuses_non_deploy_branch(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "some-other-branch"], api_sub)

        result = create_feature_branch("api", "US-API-1-1", "test", root=hub)

        assert result.startswith("error:")
        assert "deploy branch" in result


# ─── 2. PR creation (mocked gh CLI) ──────────────────────────────


def _mock_subprocess_for_pr(push_result=None, gh_result=None):
    """Build a side_effect that delegates real git calls but mocks push/gh."""
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


class TestPRCreation:
    """create_pr() mocks/stubs gh CLI and verifies --base and --head flags."""

    def test_pr_targets_deploy_branch_as_base(self, hub_two_projects):
        """--base flag is the deploy branch (main)."""
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "pm/US-API-1-1/add-auth"], api_sub)
        (api_sub / "auth.py").write_text("class Auth: pass\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "add auth"], api_sub)

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/api/pull/42\n",
            stderr="",
        )

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_subprocess_for_pr(push_ok, pr_ok),
        ) as mock_run:
            result = create_pr("api", "Add auth", "Auth impl", root=hub)

        assert result["url"] == "https://github.com/owner/api/pull/42"
        assert result["number"] == 42

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        assert len(gh_calls) == 1
        cmd = gh_calls[0][0][0]
        base_idx = cmd.index("--base")
        assert cmd[base_idx + 1] == "main"

    def test_pr_uses_feature_branch_as_head(self, hub_two_projects):
        """--head flag matches the current pm/* branch."""
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "pm/US-API-2-1/fix-bug"], api_sub)
        (api_sub / "fix.py").write_text("# fix\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "fix bug"], api_sub)

        push_ok = MagicMock(returncode=0, stdout="", stderr="")
        pr_ok = MagicMock(returncode=0, stdout="https://github.com/owner/api/pull/1\n")

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_subprocess_for_pr(push_ok, pr_ok),
        ) as mock_run:
            create_pr("api", "Fix bug", "body", root=hub)

        gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
        cmd = gh_calls[0][0][0]
        head_idx = cmd.index("--head")
        assert cmd[head_idx + 1] == "pm/US-API-2-1/fix-bug"


# ─── 3. Hub ref update after merge ───────────────────────────────


class TestHubRefUpdateAfterMerge:
    """update_hub_refs_after_merge() advances submodule refs only when all PRs merged."""

    def test_advances_ref_when_no_open_prs_and_merged_prs_exist(self, hub_two_projects):
        """With merged PRs and no open PRs, submodule ref moves forward."""
        hub = hub_two_projects["hub"]
        tmp = hub_two_projects["tmp"]

        # Create feature branch, push, and simulate merge
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/add-auth"], api_sub)
        (api_sub / "auth.py").write_text("class Auth: pass\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add auth"], api_sub)
        _git(["push", "-u", "origin", "feature/add-auth"], api_sub)
        _git(["checkout", "main"], api_sub)

        # Simulate PR merge on remote
        _merge_feature_into_main(
            hub_two_projects["api_bare"], "feature/add-auth", tmp, "api",
        )

        old_ref = _sha(api_sub)

        merged_prs = [{"number": 42, "title": "Add auth", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            result = update_hub_refs_after_merge(["api"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 1
        assert result["updated"][0]["project"] == "api"
        assert result["updated"][0]["old_ref"] == old_ref
        assert result["updated"][0]["new_ref"] != old_ref
        assert result["updated"][0]["merged_prs"] == merged_prs

    def test_skips_project_with_open_prs(self, hub_two_projects):
        """With open PRs remaining, the submodule ref stays put."""
        hub = hub_two_projects["hub"]
        tmp = hub_two_projects["tmp"]

        # Push and merge a feature
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/add-auth"], api_sub)
        (api_sub / "auth.py").write_text("class Auth: pass\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add auth"], api_sub)
        _git(["push", "-u", "origin", "feature/add-auth"], api_sub)
        _git(["checkout", "main"], api_sub)

        _merge_feature_into_main(
            hub_two_projects["api_bare"], "feature/add-auth", tmp, "api",
        )

        old_ref = _sha(api_sub)
        open_prs = [{"number": 99, "title": "WIP feature", "headRefName": "pm/US-1-1/wip"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=open_prs, merged_prs=[]),
        ):
            result = update_hub_refs_after_merge(["api"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["project"] == "api"
        assert "1 open PR(s)" in result["skipped"][0]["reason"]
        # Ref unchanged
        assert _sha(api_sub) == old_ref

    def test_unchanged_when_no_merged_prs(self, hub_two_projects):
        """With no open and no merged PRs, project goes to unchanged list."""
        hub = hub_two_projects["hub"]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=[]),
        ):
            result = update_hub_refs_after_merge(["api"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 0
        assert len(result["skipped"]) == 0
        assert "api" in result["unchanged"]

    def test_commits_hub_with_descriptive_message(self, hub_two_projects):
        """A hub commit is created with a descriptive message referencing the project."""
        hub = hub_two_projects["hub"]
        tmp = hub_two_projects["tmp"]

        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/new-api"], api_sub)
        (api_sub / "new.py").write_text("# new\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: new"], api_sub)
        _git(["push", "-u", "origin", "feature/new-api"], api_sub)
        _git(["checkout", "main"], api_sub)

        _merge_feature_into_main(
            hub_two_projects["api_bare"], "feature/new-api", tmp, "api",
        )

        merged_prs = [{"number": 1, "title": "New API", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            update_hub_refs_after_merge(["api"], root=hub)

        commit_msg = _git(["log", "-1", "--format=%s"], hub).stdout.strip()
        assert "hub: update refs after merge" in commit_msg
        assert "api" in commit_msg

    def test_records_ref_log_with_pr_merge_source(self, hub_two_projects):
        """After update, ref-log.yaml contains entries with source='pr_merge'."""
        hub = hub_two_projects["hub"]
        tmp = hub_two_projects["tmp"]

        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/log-test"], api_sub)
        (api_sub / "log.py").write_text("# log test\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: log test"], api_sub)
        _git(["push", "-u", "origin", "feature/log-test"], api_sub)
        _git(["checkout", "main"], api_sub)

        _merge_feature_into_main(
            hub_two_projects["api_bare"], "feature/log-test", tmp, "api",
        )

        merged_prs = [{"number": 7, "title": "Log test", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            update_hub_refs_after_merge(["api"], root=hub)

        ref_log_path = hub / ".project" / "ref-log.yaml"
        assert ref_log_path.exists()

        entries = yaml.safe_load(ref_log_path.read_text())
        assert len(entries) >= 1
        api_entry = [e for e in entries if e["project"] == "api"][0]
        assert api_entry["source"] == "pr_merge"
        assert api_entry["old_ref"]
        assert api_entry["new_ref"]
        assert api_entry["old_ref"] != api_entry["new_ref"]

    def test_updates_multiple_projects_in_single_commit(self, hub_two_projects):
        """When both api and web have merged PRs, both refs update in one commit."""
        hub = hub_two_projects["hub"]
        tmp = hub_two_projects["tmp"]

        for name, branch in [("api", "feature/auth"), ("web", "feature/ui")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", branch], sub)
            (sub / "feature.py").write_text(f"# {name}\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature"], sub)
            _git(["push", "-u", "origin", branch], sub)
            _git(["checkout", "main"], sub)

        _merge_feature_into_main(hub_two_projects["api_bare"], "feature/auth", tmp, "api")
        _merge_feature_into_main(hub_two_projects["web_bare"], "feature/ui", tmp, "web")

        merged_prs = [{"number": 1, "title": "Feature", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            result = update_hub_refs_after_merge(["api", "web"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 2
        updated_names = {u["project"] for u in result["updated"]}
        assert updated_names == {"api", "web"}

        commit_msg = _git(["log", "-1", "--format=%s"], hub).stdout.strip()
        assert "api" in commit_msg
        assert "web" in commit_msg


# ─── 4. Deploy protection ────────────────────────────────────────


class TestDeployProtection:
    """validate_not_on_deploy_branch() catches direct commits, allows feature branches."""

    def test_blocks_dirty_deploy_branch(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        (api_sub / "README.md").write_text("# modified on deploy\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result != ""
        assert "uncommitted changes" in result
        assert "deploy branch" in result

    def test_allows_feature_branch_work(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/work"], api_sub)
        (api_sub / "work.py").write_text("# work\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""

    def test_allows_clean_deploy_branch(self, hub_two_projects):
        hub = hub_two_projects["hub"]

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""

    def test_allows_untracked_files_on_deploy(self, hub_two_projects):
        hub = hub_two_projects["hub"]
        api_sub = hub / "projects" / "api"
        (api_sub / "scratch.txt").write_text("scratch\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""


# ─── 5. Multi-project: 3 subprojects, selective hub ref updates ──


class TestMultiProjectPRWorkflow:
    """Simultaneous feature branches in 3 subprojects; hub refs update selectively."""

    def test_updates_only_merged_projects_skips_open(self, hub_three_projects):
        """3 subprojects: api merged, web has open PRs, mobile no PRs."""
        hub = hub_three_projects["hub"]
        tmp = hub_three_projects["tmp"]

        # Feature branch + merge for api
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/api-work"], api_sub)
        (api_sub / "api.py").write_text("# api\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: work"], api_sub)
        _git(["push", "-u", "origin", "feature/api-work"], api_sub)
        _git(["checkout", "main"], api_sub)
        _merge_feature_into_main(
            hub_three_projects["api_bare"], "feature/api-work", tmp, "api",
        )

        # Feature branch for web (pushed but not merged — open PR)
        web_sub = hub / "projects" / "web"
        _git(["checkout", "-b", "feature/web-work"], web_sub)
        (web_sub / "web.py").write_text("# web\n")
        _git(["add", "."], web_sub)
        _git(["commit", "-m", "web: work"], web_sub)
        _git(["push", "-u", "origin", "feature/web-work"], web_sub)
        _git(["checkout", "main"], web_sub)

        # Per-project gh mock responses
        real_run = subprocess.run

        def per_project_gh(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                cwd = kwargs.get("cwd", "")
                result = MagicMock(returncode=0, stderr="")
                state_idx = cmd.index("--state") if "--state" in cmd else -1
                state = cmd[state_idx + 1] if state_idx >= 0 else ""

                if "api" in str(cwd):
                    if state == "open":
                        result.stdout = "[]"
                    elif state == "merged":
                        result.stdout = json.dumps([
                            {"number": 10, "title": "API work", "mergedAt": "2026-02-28T12:00:00Z"},
                        ])
                    else:
                        result.stdout = "[]"
                elif "web" in str(cwd):
                    if state == "open":
                        result.stdout = json.dumps([
                            {"number": 20, "title": "Web WIP", "headRefName": "feature/web-work"},
                        ])
                    else:
                        result.stdout = "[]"
                else:
                    # mobile — no PRs at all
                    result.stdout = "[]"
                return result
            return real_run(cmd, *args, **kwargs)

        with patch("projectman.hub.registry.subprocess.run", side_effect=per_project_gh):
            result = update_hub_refs_after_merge(["api", "web", "mobile"], root=hub)

        assert result["error"] is None
        # api: updated (merged, no open)
        assert len(result["updated"]) == 1
        assert result["updated"][0]["project"] == "api"
        # web: skipped (has open PR)
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["project"] == "web"
        # mobile: unchanged (no merged PRs)
        assert "mobile" in result["unchanged"]

    def test_all_three_merged_updates_all(self, hub_three_projects):
        """When all 3 subprojects' PRs are merged, all refs update in one commit."""
        hub = hub_three_projects["hub"]
        tmp = hub_three_projects["tmp"]

        for name in ("api", "web", "mobile"):
            sub = hub / "projects" / name
            branch = f"feature/{name}-work"
            _git(["checkout", "-b", branch], sub)
            (sub / "feature.py").write_text(f"# {name}\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature"], sub)
            _git(["push", "-u", "origin", branch], sub)
            _git(["checkout", "main"], sub)
            _merge_feature_into_main(
                hub_three_projects[f"{name}_bare"], branch, tmp, name,
            )

        merged_prs = [{"number": 1, "title": "Work", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            result = update_hub_refs_after_merge(["api", "web", "mobile"], root=hub)

        assert result["error"] is None
        assert len(result["updated"]) == 3
        updated_names = {u["project"] for u in result["updated"]}
        assert updated_names == {"api", "web", "mobile"}


# ─── 6. Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: no gh, no remote, deploy branch doesn't exist, non-hub, bad project."""

    def test_gh_not_installed_treated_as_no_prs(self, hub_two_projects):
        """When gh raises FileNotFoundError, treat as no PRs (unchanged)."""
        hub = hub_two_projects["hub"]
        real_run = subprocess.run

        def gh_missing(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                raise FileNotFoundError("gh")
            return real_run(cmd, *args, **kwargs)

        with patch("projectman.hub.registry.subprocess.run", side_effect=gh_missing):
            result = update_hub_refs_after_merge(["api"], root=hub)

        # No crash — gh failure is handled gracefully
        assert result["error"] is None
        assert "api" in result["unchanged"]
        assert len(result["updated"]) == 0
        assert len(result["skipped"]) == 0

    def test_non_hub_project_returns_error(self, tmp_path):
        """Non-hub project returns an error dict."""
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

        result = update_hub_refs_after_merge(["api"], root=tmp_path)

        assert result["error"] == "not a hub project"

    def test_unregistered_project_returns_error(self, hub_two_projects):
        """Querying a project not in config.projects returns an error."""
        hub = hub_two_projects["hub"]

        result = update_hub_refs_after_merge(["nonexistent"], root=hub)

        assert result["error"] is not None
        assert "not registered" in result["error"]

    def test_missing_project_directory_goes_to_unchanged(self, hub_two_projects):
        """A registered project with no directory on disk goes to unchanged."""
        hub = hub_two_projects["hub"]

        # Register a ghost project
        config_path = hub / ".project" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["projects"].append("ghost")
        config_path.write_text(yaml.dump(config))

        merged_prs = [{"number": 1, "title": "Work", "mergedAt": "2026-02-28T12:00:00Z"}]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=merged_prs),
        ):
            result = update_hub_refs_after_merge(["ghost"], root=hub)

        assert result["error"] is None
        assert "ghost" in result["unchanged"]

    def test_defaults_to_all_projects_when_none(self, hub_two_projects):
        """When projects=None, all registered projects are checked."""
        hub = hub_two_projects["hub"]

        with patch(
            "projectman.hub.registry.subprocess.run",
            side_effect=_mock_gh(open_prs=[], merged_prs=[]),
        ):
            result = update_hub_refs_after_merge(projects=None, root=hub)

        assert result["error"] is None
        # Both api and web should appear (unchanged, since no merged PRs)
        assert set(result["unchanged"]) == {"api", "web"}

    def test_gh_returns_malformed_json(self, hub_two_projects):
        """Malformed JSON from gh is handled gracefully (treated as no PRs)."""
        hub = hub_two_projects["hub"]
        real_run = subprocess.run

        def gh_bad_json(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                result = MagicMock(returncode=0, stderr="")
                result.stdout = "not valid json{{"
                return result
            return real_run(cmd, *args, **kwargs)

        with patch("projectman.hub.registry.subprocess.run", side_effect=gh_bad_json):
            result = update_hub_refs_after_merge(["api"], root=hub)

        # No crash
        assert result["error"] is None
        assert "api" in result["unchanged"]

    def test_gh_returns_nonzero_exit(self, hub_two_projects):
        """Non-zero exit from gh is handled gracefully (treated as no PRs)."""
        hub = hub_two_projects["hub"]
        real_run = subprocess.run

        def gh_error(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                result = MagicMock(returncode=1, stderr="some error")
                result.stdout = ""
                return result
            return real_run(cmd, *args, **kwargs)

        with patch("projectman.hub.registry.subprocess.run", side_effect=gh_error):
            result = update_hub_refs_after_merge(["api"], root=hub)

        assert result["error"] is None
        assert "api" in result["unchanged"]
