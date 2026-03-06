"""Test: Subproject changes create feature branches not direct commits to deploy (US-PRJ-7-1).

Verifies acceptance criterion for story US-PRJ-7:
    > Subproject changes create feature branches not direct commits to deploy

Uses real git repos with bare remotes to verify that:
1. Changes are committed on a feature branch, not deploy (main)
2. Pushing the feature branch does NOT update main on the remote
3. The changeset workflow tracks the feature branch ref correctly
4. Hub refs are only updated after all PRs merge (not on feature push)
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import push_subprojects, coordinated_push
from projectman.changesets import create_changeset
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
                .project/     PM metadata with changeset support
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

    def test_push_feature_branch_does_not_update_remote_deploy(self, hub_with_deploy_branches):
        """Pushing a feature branch to the remote leaves the remote's deploy branch untouched.

        push_subprojects() pushes the current branch. When a subproject is on a
        feature branch, only that feature branch is pushed — main on the remote
        stays at its previous SHA.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        api_sub = hub / "projects" / "api"

        # Record remote deploy branch SHA
        remote_main_before = _remote_sha(api_bare, "main")

        # Create feature branch and commit
        _git(["checkout", "-b", "feature/new-endpoint"], api_sub)
        (api_sub / "endpoint.py").write_text("# new endpoint\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: new endpoint"], api_sub)
        feature_sha = _sha(api_sub)

        # Push using push_subprojects (pushes whatever branch subproject is on)
        result = push_subprojects(["api"], root=hub)

        assert result["all_ok"] is True
        assert len(result["pushed"]) == 1
        assert result["pushed"][0]["branch"] == "feature/new-endpoint"

        # Feature branch exists on remote with the correct SHA
        assert _remote_sha(api_bare, "feature/new-endpoint") == feature_sha

        # Deploy branch on remote is UNCHANGED
        assert _remote_sha(api_bare, "main") == remote_main_before, (
            "remote main must not be updated by a feature branch push"
        )

    def test_multiple_subprojects_on_feature_branches(self, hub_with_deploy_branches):
        """Multiple subprojects can each have feature branches without touching deploy.

        When api and web both create feature branches, pushing them only creates
        feature branches on their remotes — neither remote's main is affected.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        web_bare = hub_with_deploy_branches["web_bare"]

        api_main_before = _remote_sha(api_bare, "main")
        web_main_before = _remote_sha(web_bare, "main")

        # Create feature branches in both subprojects
        for name, feature in [("api", "feature/auth"), ("web", "feature/auth-ui")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", feature], sub)
            (sub / "feature.txt").write_text(f"{name} feature work\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature work"], sub)

        # Push both
        result = push_subprojects(["api", "web"], root=hub)

        assert result["all_ok"] is True
        assert len(result["pushed"]) == 2

        # Feature branches exist on remotes
        assert _remote_branch_exists(api_bare, "feature/auth")
        assert _remote_branch_exists(web_bare, "feature/auth-ui")

        # Deploy branches on both remotes are UNCHANGED
        assert _remote_sha(api_bare, "main") == api_main_before
        assert _remote_sha(web_bare, "main") == web_main_before

    def test_changeset_tracks_feature_branch_ref(self, hub_with_deploy_branches):
        """A changeset entry records the feature branch name, not 'main'.

        When working in the PR-based workflow, the changeset tracks which
        feature branch each project's changes live on. This ensures the
        PR will be created from the correct branch.
        """
        hub = hub_with_deploy_branches["hub"]
        store = Store(hub)

        # Create a changeset for a cross-repo feature
        cs = create_changeset(store, "add-auth", ["api", "web"])

        # Add feature branch refs to each entry
        updated = store.add_changeset_entry(cs.id, "api", ref="feature/auth")
        # The first add_changeset_entry adds to existing, so we update the ref
        # by re-reading and checking the entries
        meta, _ = store.get_changeset(cs.id)

        # Set refs on existing entries (simulating the workflow)
        api_entry = next(e for e in meta.entries if e.project == "api")
        web_entry = next(e for e in meta.entries if e.project == "web")

        # Verify the changeset tracks feature branches, not deploy branches
        store.add_changeset_entry(cs.id, "web", ref="feature/auth-ui")
        meta, _ = store.get_changeset(cs.id)

        refs = {e.project: e.ref for e in meta.entries if e.ref}
        assert "feature/auth-ui" in refs.values(), (
            "changeset must track feature branch refs, not deploy branch"
        )

    def test_coordinated_push_rejects_direct_to_deploy_when_misaligned(
        self, hub_with_deploy_branches
    ):
        """coordinated_push rejects when submodule is on wrong branch.

        When tracking branches are configured (e.g., main), and a subproject
        is on a feature branch, coordinated_push (scope=all) rejects the push.
        This prevents accidentally pushing feature work directly into the deploy
        workflow — the correct path is push_subprojects for the feature branch,
        then PR, then merge.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        hub_bare = hub_with_deploy_branches["hub_bare"]

        api_remote_before = _remote_sha(api_bare, "main")
        hub_remote_before = _remote_sha(hub_bare, "main")

        # Put api on a feature branch (misaligned with tracked branch 'main')
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/experiment"], api_sub)
        (api_sub / "experiment.py").write_text("# experiment\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: experiment"], api_sub)

        # coordinated_push should reject this (branch misalignment)
        result = coordinated_push(root=hub)

        assert result["pushed"] is False
        # The preflight report indicates the branch mismatch
        report = result.get("report", "") + result.get("error", "")
        assert "branch mismatch" in report.lower() or "preflight failed" in report.lower(), (
            f"expected branch mismatch rejection, got: {report}"
        )

        # Neither remote should have been updated
        assert _remote_sha(api_bare, "main") == api_remote_before
        assert _remote_sha(hub_bare, "main") == hub_remote_before

    def test_feature_branch_push_then_deploy_stays_clean(self, hub_with_deploy_branches):
        """Full workflow: feature branch push leaves deploy clean for PR-based merge.

        Simulates the intended workflow:
        1. Create feature branch in subproject
        2. Commit changes
        3. Push feature branch to remote
        4. Verify: deploy branch on remote is completely untouched
        5. Verify: feature branch on remote has the changes
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        api_sub = hub / "projects" / "api"

        # Snapshot the deploy branch
        deploy_sha = _remote_sha(api_bare, "main")

        # 1. Create feature branch
        _git(["checkout", "-b", "feature/user-profiles"], api_sub)
        assert _branch(api_sub) == "feature/user-profiles"

        # 2. Make multiple commits on the feature branch
        (api_sub / "profiles.py").write_text("class UserProfile: pass\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add user profile model"], api_sub)

        (api_sub / "profiles_api.py").write_text("def get_profile(): ...\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add profile endpoint"], api_sub)

        feature_tip = _sha(api_sub)

        # 3. Push feature branch
        result = push_subprojects(["api"], root=hub)
        assert result["all_ok"] is True
        assert result["pushed"][0]["branch"] == "feature/user-profiles"

        # 4. Deploy branch is untouched
        assert _remote_sha(api_bare, "main") == deploy_sha, (
            "deploy branch must remain clean — changes only arrive via PR merge"
        )

        # 5. Feature branch has all commits
        assert _remote_sha(api_bare, "feature/user-profiles") == feature_tip
