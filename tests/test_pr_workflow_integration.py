"""Test: PR creation integrated into workflow (gh cli) (US-PRJ-7-2).

Verifies acceptance criterion for story US-PRJ-7:
    > PR creation integrated into workflow (gh cli)

Tests that the PR workflow is properly integrated end-to-end:
1. Changesets generate correct `gh pr create` commands with cross-references
2. PR commands target the correct feature branches (--head)
3. PR numbers can be tracked on changeset entries after creation
4. PR status checking via `gh pr view` drives changeset lifecycle
5. The full workflow (branch → changeset → PR → merge → hub update) is cohesive
"""

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import frontmatter
import pytest
import yaml

from projectman.changesets import (
    changeset_check_status,
    changeset_create_prs,
    create_changeset,
    update_changeset_status,
)
from projectman.hub.registry import push_subprojects
from projectman.models import ChangesetEntry, ChangesetStatus
from projectman.store import Store


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


def _persist_changeset(store: Store, meta, body: str) -> None:
    """Write updated changeset metadata back to disk."""
    post = frontmatter.Post(content=body, **meta.model_dump(mode="json"))
    store._changeset_path(meta.id).write_text(frontmatter.dumps(post))


def _gh_pr_response(state: str, merged_at=None):
    """Build a mock subprocess result for a gh pr view call."""
    data = {"state": state, "mergedAt": merged_at}
    result = MagicMock()
    result.stdout = json.dumps(data)
    result.returncode = 0
    return result


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_with_feature_branches(tmp_path):
    """Real git hub with subprojects on feature branches, ready for PR creation.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub/              hub working copy
                projects/api/ submodule on feature/add-auth
                projects/web/ submodule on feature/add-auth-ui
                .project/     PM metadata with changeset support
    """
    # Create subproject bare repos and seed with initial commits
    for name in ("api", "web"):
        bare = tmp_path / f"{name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)

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

    # Clone hub and configure
    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev@test.com"], hub)
    _git(["config", "user.name", "Dev"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # Set up PM structure with changeset support
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects", "dashboards", "changesets"):
        (proj / d).mkdir()
    config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "next_changeset_id": 1,
        "projects": ["api", "web"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    # Add submodules
    for name in ("api", "web"):
        _git(
            ["submodule", "add", str(tmp_path / f"{name}.git"), f"projects/{name}"],
            hub,
        )
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    # Create feature branches in subprojects with changes
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "feature/add-auth"], api_sub)
    (api_sub / "auth.py").write_text("class AuthService: pass\n")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: add auth service"], api_sub)

    web_sub = hub / "projects" / "web"
    _git(["checkout", "-b", "feature/add-auth-ui"], web_sub)
    (web_sub / "login.html").write_text("<form>login</form>\n")
    _git(["add", "."], web_sub)
    _git(["commit", "-m", "web: add login page"], web_sub)

    return {
        "tmp": tmp_path,
        "hub": hub,
        "hub_bare": hub_bare,
        "api_bare": tmp_path / "api.git",
        "web_bare": tmp_path / "web.git",
    }


# ─── Tests: PR creation integrated into workflow ─────────────────


class TestPRCreationWorkflowIntegration:
    """End-to-end: feature branch → changeset → gh pr create commands."""

    def test_changeset_generates_gh_pr_create_commands(self, hub_with_feature_branches):
        """A changeset with feature branch refs generates gh pr create commands."""
        hub = hub_with_feature_branches["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])

        # Set feature branch refs on entries
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/add-auth"
        meta.entries[1].ref = "feature/add-auth-ui"
        _persist_changeset(store, meta, body)

        result = changeset_create_prs(store, cs.id)

        assert result["changeset"] == cs.id
        assert result["title"] == "add-auth"
        assert len(result["pr_commands"]) == 2

        # Each command uses gh pr create
        for cmd in result["pr_commands"]:
            assert "gh pr create" in cmd["command"]

    def test_pr_commands_use_feature_branch_as_head(self, hub_with_feature_branches):
        """Each PR command's --head flag matches the entry's feature branch ref."""
        hub = hub_with_feature_branches["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/add-auth"
        meta.entries[1].ref = "feature/add-auth-ui"
        _persist_changeset(store, meta, body)

        result = changeset_create_prs(store, cs.id)

        assert "--head feature/add-auth" in result["pr_commands"][0]["command"]
        assert "--head feature/add-auth-ui" in result["pr_commands"][1]["command"]

    def test_pr_commands_cd_into_correct_project_dir(self, hub_with_feature_branches):
        """Each PR command cd's into the correct project directory."""
        hub = hub_with_feature_branches["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/add-auth"
        meta.entries[1].ref = "feature/add-auth-ui"
        _persist_changeset(store, meta, body)

        result = changeset_create_prs(store, cs.id)

        assert result["pr_commands"][0]["command"].startswith("cd api &&")
        assert result["pr_commands"][1]["command"].startswith("cd web &&")

    def test_pr_body_cross_references_sibling_projects(self, hub_with_feature_branches):
        """Each PR body contains cross-references to all sibling projects."""
        hub = hub_with_feature_branches["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/add-auth"
        meta.entries[1].ref = "feature/add-auth-ui"
        _persist_changeset(store, meta, body)

        result = changeset_create_prs(store, cs.id)

        # The api PR body should mention both api and web
        api_cmd = result["pr_commands"][0]["command"]
        assert "api" in api_cmd
        assert "web" in api_cmd
        assert "Cross-references" in api_cmd

    def test_full_workflow_branch_push_then_pr_generation(self, hub_with_feature_branches):
        """Full integration: push feature branches, then generate PR commands.

        This is the intended developer workflow:
        1. Create feature branches and commit changes (done in fixture)
        2. Push feature branches to remotes
        3. Create a changeset tracking the branches
        4. Generate gh pr create commands
        """
        hub = hub_with_feature_branches["hub"]
        store = Store(hub)

        # Step 2: Push feature branches
        result = push_subprojects(["api", "web"], root=hub)
        assert result["all_ok"] is True
        pushed_branches = {p["name"]: p["branch"] for p in result["pushed"]}
        assert pushed_branches["api"] == "feature/add-auth"
        assert pushed_branches["web"] == "feature/add-auth-ui"

        # Step 3: Create changeset with the pushed branch refs
        cs = create_changeset(store, "add-auth-feature", ["api", "web"])
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = pushed_branches["api"]
        meta.entries[1].ref = pushed_branches["web"]
        _persist_changeset(store, meta, body)

        # Step 4: Generate PR commands
        pr_result = changeset_create_prs(store, cs.id)

        assert len(pr_result["pr_commands"]) == 2
        # Commands reference the actual pushed branches
        assert "--head feature/add-auth" in pr_result["pr_commands"][0]["command"]
        assert "--head feature/add-auth-ui" in pr_result["pr_commands"][1]["command"]
        # Commands are valid gh cli invocations
        for cmd in pr_result["pr_commands"]:
            assert "gh pr create" in cmd["command"]
            assert "--title" in cmd["command"]
            assert "--body" in cmd["command"]


class TestPRNumberTrackingInWorkflow:
    """After PR creation, PR numbers are tracked on changeset entries."""

    def test_pr_number_persists_on_entry(self, tmp_project):
        """PR numbers set on entries survive round-trip to disk."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        meta2, _ = store.get_changeset(cs.id)
        assert meta2.entries[0].pr_number == 42
        assert meta2.entries[1].pr_number == 43

    def test_pr_number_enables_status_checking(self, tmp_project):
        """Entries with PR numbers can have their status checked via gh pr view."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "web").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("OPEN")
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "open"
        assert len(result["entries"]) == 2
        # gh pr view was called for each entry with a pr_number
        assert mock_run.call_count == 2

    def test_entries_without_pr_number_skipped_in_status_check(self, tmp_project):
        """Entries without PR numbers are skipped during status checking."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])
        # No PR numbers set

        result = changeset_check_status(store, cs.id, root=tmp_project)

        assert all(e["status"] == "no-pr" for e in result["entries"])


class TestPRStatusDrivesChangesetLifecycle:
    """gh pr view results drive the changeset from open → partial → merged."""

    def test_all_prs_open_keeps_changeset_open(self, tmp_project):
        """When all PRs are still open, changeset stays open."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "web").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("OPEN")
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "open"

    def test_some_merged_sets_changeset_partial(self, tmp_project):
        """When some PRs merge but not all, changeset becomes partial."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "web").mkdir(parents=True)

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pr_num = cmd[3]
            if pr_num == "10":
                return _gh_pr_response("MERGED", "2026-02-28T12:00:00Z")
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "partial"

    def test_all_merged_sets_changeset_merged(self, tmp_project):
        """When all PRs merge, changeset becomes merged — ready for hub ref update."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "web").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("MERGED", "2026-02-28T12:00:00Z")
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "merged"
        assert result["needs_review"] is False

        # Verify persisted to disk
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.merged

    def test_closed_pr_flags_changeset_for_review(self, tmp_project):
        """A closed (not merged) PR flags the changeset for human review."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("CLOSED")
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "closed"
        assert result["needs_review"] is True

    def test_gh_cli_error_recorded_gracefully(self, tmp_project):
        """If gh pr view fails, the error is recorded without crashing."""
        store = Store(tmp_project)
        cs = create_changeset(store, "feature-x", ["api"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh", stderr="Could not resolve to a PullRequest"
            )
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["entries"][0]["status"] == "error"
        assert "PullRequest" in result["entries"][0]["message"]


class TestMCPServerPRIntegration:
    """The MCP server exposes PR creation as a tool for agent/CLI use."""

    def test_pm_changeset_create_prs_returns_yaml(self, tmp_project, monkeypatch):
        """pm_changeset_create_prs MCP tool returns YAML with gh commands."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "web"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/x-api"
        meta.entries[1].ref = "feature/x-web"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        raw = pm_changeset_create_prs(cs.id)
        result = yaml.safe_load(raw)

        assert result["changeset"] == cs.id
        assert len(result["pr_commands"]) == 2
        assert "gh pr create" in result["pr_commands"][0]["command"]
        assert "gh pr create" in result["pr_commands"][1]["command"]

    def test_pm_changeset_create_prs_error_on_missing(self, tmp_project, monkeypatch):
        """MCP tool returns error string for non-existent changeset."""
        monkeypatch.chdir(tmp_project)

        from projectman.server import pm_changeset_create_prs

        result = pm_changeset_create_prs("CS-TST-999")
        assert "error" in result

    def test_pm_changeset_create_prs_error_on_empty(self, tmp_project, monkeypatch):
        """MCP tool returns error for changeset with no entries."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("empty", [])

        from projectman.server import pm_changeset_create_prs

        result = pm_changeset_create_prs(cs.id)
        assert "error" in result
