"""Test: Deploy branch is protected from direct pushes (US-PRJ-7-4).

Verifies acceptance criterion for story US-PRJ-7:
    > Deploy branch is protected from direct pushes

Uses real git repos with bare remotes to verify that:
1. push_preflight blocks pushes when subprojects are on feature branches (not deploy)
2. coordinated_push never updates the remote deploy branch during feature work
3. validate_branches(strict=True) catches feature-vs-deploy misalignment
4. The full feature branch workflow leaves the remote deploy branch untouched
5. push_subprojects only ever pushes the current branch, never the deploy branch
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import (
    coordinated_push,
    push_preflight,
    push_subprojects,
    validate_branches,
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


# ─── Tests: Preflight gate blocks misaligned branches ────────────


class TestPreflightBlocksFeatureBranch:
    """push_preflight blocks when subprojects are on feature branches (not deploy)."""

    def test_preflight_blocks_single_misaligned_project(self, hub_with_deploy_branches):
        """Preflight blocks when one subproject is on a feature branch instead of deploy.

        The push_preflight gate uses strict branch validation. When a subproject
        is on a feature branch (misaligned with the tracking branch in .gitmodules),
        the preflight must block and report the mismatch.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        # Switch api to a feature branch (misaligned with tracked 'main')
        _git(["checkout", "-b", "feature/new-api"], api_sub)
        (api_sub / "new.py").write_text("# new\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: new feature"], api_sub)

        result = push_preflight(projects=["api"], root=hub)

        assert result["can_proceed"] is False
        assert len(result["blocked"]) == 1
        assert result["blocked"][0]["name"] == "api"
        assert "branch mismatch" in result["blocked"][0]["reason"]
        assert "feature/new-api" in result["blocked"][0]["reason"]
        assert "main" in result["blocked"][0]["reason"]

    def test_preflight_blocks_all_misaligned_projects(self, hub_with_deploy_branches):
        """Preflight blocks all subprojects that are on feature branches.

        When multiple subprojects are on feature branches, each one must
        independently be reported as blocked.
        """
        hub = hub_with_deploy_branches["hub"]

        for name, feature in [("api", "feature/auth"), ("web", "feature/ui")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", feature], sub)
            (sub / "feature.txt").write_text(f"{name} work\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature"], sub)

        result = push_preflight(root=hub)

        assert result["can_proceed"] is False
        assert len(result["blocked"]) == 2
        blocked_names = {b["name"] for b in result["blocked"]}
        assert blocked_names == {"api", "web"}

    def test_preflight_passes_when_on_deploy_branch(self, hub_with_deploy_branches):
        """Preflight passes when all subprojects are on the deploy branch.

        When subprojects are aligned with their tracking branch (deploy branch),
        the preflight gate allows the push to proceed.
        """
        hub = hub_with_deploy_branches["hub"]

        # Both subprojects are on 'main' (deploy branch) — default state
        assert _branch(hub / "projects" / "api") == "main"
        assert _branch(hub / "projects" / "web") == "main"

        result = push_preflight(root=hub)

        assert result["can_proceed"] is True
        assert len(result["blocked"]) == 0


# ─── Tests: validate_branches strict mode ────────────────────────


class TestValidateBranchesDeployProtection:
    """validate_branches(strict=True) catches feature-vs-deploy misalignment."""

    def test_strict_validation_detects_feature_branch_misalignment(
        self, hub_with_deploy_branches
    ):
        """Strict mode flags a feature branch as misaligned with the deploy branch.

        This is the core deploy protection check: if a subproject is on
        'feature/x' but .gitmodules says it should track 'main', strict
        validation must report it as misaligned and set ok=False.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        _git(["checkout", "-b", "feature/deploy-bypass-attempt"], api_sub)

        result = validate_branches(root=hub, strict=True)

        assert result["ok"] is False
        assert result["strict"] is True
        assert len(result["misaligned"]) == 1
        assert result["misaligned"][0]["name"] == "api"
        assert result["misaligned"][0]["expected"] == "main"
        assert result["misaligned"][0]["actual"] == "feature/deploy-bypass-attempt"

    def test_non_strict_validation_also_catches_misalignment(
        self, hub_with_deploy_branches
    ):
        """Even non-strict mode catches branch misalignment (not just strict).

        Misalignment is always blocking — the strict flag only changes
        whether detached HEAD is blocking or informational.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        _git(["checkout", "-b", "feature/test"], api_sub)

        result = validate_branches(root=hub, strict=False)

        assert result["ok"] is False
        assert len(result["misaligned"]) == 1

    def test_aligned_on_deploy_branch_passes_strict(self, hub_with_deploy_branches):
        """Subprojects on the deploy branch pass strict validation."""
        hub = hub_with_deploy_branches["hub"]

        result = validate_branches(root=hub, strict=True)

        assert result["ok"] is True
        assert len(result["aligned"]) == 2
        assert len(result["misaligned"]) == 0
        for entry in result["aligned"]:
            assert entry["branch"] == "main"

    def test_detached_head_blocked_in_strict_mode(self, hub_with_deploy_branches):
        """Detached HEAD is a blocking error in strict mode (push gate).

        A developer who accidentally detached HEAD should not be able to
        push — strict mode ensures this is caught before any push.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        # Detach HEAD
        sha = _sha(api_sub)
        _git(["checkout", sha], api_sub)

        result = validate_branches(root=hub, strict=True)

        assert result["ok"] is False
        assert len(result["detached"]) == 1
        assert result["detached"][0]["name"] == "api"


# ─── Tests: coordinated_push deploy protection ──────────────────


class TestCoordinatedPushDeployProtection:
    """coordinated_push never updates the remote deploy branch during feature work."""

    def test_coordinated_push_blocks_before_touching_remote_deploy(
        self, hub_with_deploy_branches
    ):
        """coordinated_push blocks at preflight — remote deploy branch is never touched.

        When a subproject is on a feature branch, coordinated_push must
        fail at the preflight gate. The remote deploy branch must remain
        at its original SHA, proving no direct push occurred.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        web_bare = hub_with_deploy_branches["web_bare"]
        hub_bare = hub_with_deploy_branches["hub_bare"]

        # Snapshot all remote deploy branches
        api_deploy_before = _remote_sha(api_bare, "main")
        web_deploy_before = _remote_sha(web_bare, "main")
        hub_deploy_before = _remote_sha(hub_bare, "main")

        # Create feature branch with changes in api
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/risky-change"], api_sub)
        (api_sub / "risky.py").write_text("# risky\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: risky change"], api_sub)

        # coordinated_push should block
        result = coordinated_push(root=hub)

        assert result["pushed"] is False

        # ALL remote deploy branches must be unchanged
        assert _remote_sha(api_bare, "main") == api_deploy_before
        assert _remote_sha(web_bare, "main") == web_deploy_before
        assert _remote_sha(hub_bare, "main") == hub_deploy_before

    def test_coordinated_push_report_explains_branch_mismatch(
        self, hub_with_deploy_branches
    ):
        """coordinated_push report includes the branch mismatch reason.

        The report must clearly tell the developer which project is misaligned
        and what branch it's on vs what was expected.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        _git(["checkout", "-b", "feature/hotfix"], api_sub)
        (api_sub / "fix.py").write_text("# fix\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: hotfix"], api_sub)

        result = coordinated_push(root=hub)

        assert result["pushed"] is False
        report = result.get("report", "")
        assert "Preflight FAILED" in report
        assert "branch mismatch" in report.lower()


# ─── Tests: push_subprojects isolation ───────────────────────────


class TestPushSubprojectsDeployIsolation:
    """push_subprojects only pushes the current branch, never the deploy branch."""

    def test_feature_push_creates_only_feature_branch_on_remote(
        self, hub_with_deploy_branches
    ):
        """Pushing a feature branch creates it on the remote but does not touch deploy.

        This verifies the fundamental isolation: push_subprojects pushes the
        current branch (feature), and the remote deploy branch (main) stays
        at its original position.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        api_sub = hub / "projects" / "api"

        deploy_sha_before = _remote_sha(api_bare, "main")

        # Create and push a feature branch
        _git(["checkout", "-b", "feature/isolated-work"], api_sub)
        (api_sub / "isolated.py").write_text("# isolated\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: isolated work"], api_sub)
        feature_sha = _sha(api_sub)

        result = push_subprojects(["api"], root=hub)

        assert result["all_ok"] is True
        assert result["pushed"][0]["branch"] == "feature/isolated-work"

        # Feature branch exists on remote with correct SHA
        assert _remote_sha(api_bare, "feature/isolated-work") == feature_sha

        # Deploy branch is UNTOUCHED
        assert _remote_sha(api_bare, "main") == deploy_sha_before

    def test_multiple_feature_pushes_leave_all_deploy_branches_intact(
        self, hub_with_deploy_branches
    ):
        """Pushing feature branches across multiple subprojects leaves all deploy branches intact."""
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        web_bare = hub_with_deploy_branches["web_bare"]

        api_deploy_before = _remote_sha(api_bare, "main")
        web_deploy_before = _remote_sha(web_bare, "main")

        # Feature branches in both subprojects
        for name, feature in [("api", "feature/api-v2"), ("web", "feature/web-v2")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", feature], sub)
            (sub / "v2.py").write_text(f"# {name} v2\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: v2 changes"], sub)

        result = push_subprojects(["api", "web"], root=hub)

        assert result["all_ok"] is True
        assert len(result["pushed"]) == 2

        # Both deploy branches are untouched
        assert _remote_sha(api_bare, "main") == api_deploy_before
        assert _remote_sha(web_bare, "main") == web_deploy_before

        # Feature branches exist on their respective remotes
        assert _remote_branch_exists(api_bare, "feature/api-v2")
        assert _remote_branch_exists(web_bare, "feature/web-v2")


# ─── Tests: End-to-end deploy protection ─────────────────────────


class TestEndToEndDeployProtection:
    """Full workflow scenarios proving the deploy branch stays protected."""

    def test_feature_workflow_never_modifies_deploy_branch(
        self, hub_with_deploy_branches
    ):
        """Complete feature workflow: create branch, commit, push — deploy untouched.

        Simulates a developer's full workflow:
        1. Switch to feature branch
        2. Make multiple commits
        3. Push feature branch via push_subprojects
        4. Attempt coordinated_push (should fail because on feature branch)
        5. Verify: deploy branch on remote never changed through any step
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        hub_bare = hub_with_deploy_branches["hub_bare"]
        api_sub = hub / "projects" / "api"

        # Snapshot deploy state
        api_deploy_sha = _remote_sha(api_bare, "main")
        hub_deploy_sha = _remote_sha(hub_bare, "main")

        # 1. Create feature branch
        _git(["checkout", "-b", "feature/full-workflow"], api_sub)

        # 2. Multiple commits
        (api_sub / "step1.py").write_text("# step 1\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: step 1"], api_sub)

        (api_sub / "step2.py").write_text("# step 2\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: step 2"], api_sub)

        feature_tip = _sha(api_sub)

        # 3. Push feature branch (succeeds)
        push_result = push_subprojects(["api"], root=hub)
        assert push_result["all_ok"] is True
        assert _remote_sha(api_bare, "feature/full-workflow") == feature_tip

        # 4. Attempt coordinated_push (should fail — feature branch misalignment)
        coord_result = coordinated_push(root=hub)
        assert coord_result["pushed"] is False

        # 5. Deploy branches are completely untouched through the entire workflow
        assert _remote_sha(api_bare, "main") == api_deploy_sha, (
            "api deploy branch must not change during feature workflow"
        )
        assert _remote_sha(hub_bare, "main") == hub_deploy_sha, (
            "hub deploy branch must not change during feature workflow"
        )

    def test_only_feature_branches_appear_on_remote_after_push(
        self, hub_with_deploy_branches
    ):
        """After pushing feature work, only the feature branch is new on the remote.

        The remote should have: main (original) + feature branch (new).
        No other branches should be created, and main should not be modified.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        api_sub = hub / "projects" / "api"

        # Record which branches exist on remote before
        before_branches = _git(
            ["branch", "--list"], api_bare
        ).stdout.strip().split("\n")
        before_branches = {b.strip().lstrip("* ") for b in before_branches if b.strip()}

        # Push feature branch
        _git(["checkout", "-b", "feature/scoped-change"], api_sub)
        (api_sub / "scoped.py").write_text("# scoped\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: scoped change"], api_sub)

        push_subprojects(["api"], root=hub)

        # Check branches on remote after push
        after_branches = _git(
            ["branch", "--list"], api_bare
        ).stdout.strip().split("\n")
        after_branches = {b.strip().lstrip("* ") for b in after_branches if b.strip()}

        new_branches = after_branches - before_branches
        assert new_branches == {"feature/scoped-change"}, (
            f"Only the feature branch should be new, got: {new_branches}"
        )


# ─── Tests: validate_not_on_deploy_branch ────────────────────────


class TestValidateNotOnDeployBranch:
    """validate_not_on_deploy_branch blocks dirty changes on the deploy branch."""

    def test_blocks_modified_tracked_file_on_deploy_branch(self, hub_with_deploy_branches):
        """Returns an error when a tracked file is modified on the deploy branch.

        If a developer edits a tracked file while on the deploy branch (main),
        validate_not_on_deploy_branch must return an error directing them
        to create a feature branch first.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        # On deploy branch (main) — modify an existing tracked file
        assert _branch(api_sub) == "main"
        (api_sub / "README.md").write_text("# modified on deploy\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result != ""
        assert "uncommitted changes" in result
        assert "deploy branch" in result
        assert "feature branch" in result

    def test_allows_untracked_files_on_deploy_branch(self, hub_with_deploy_branches):
        """Returns empty string when only untracked files exist on deploy branch.

        Untracked files alone are not dangerous — they haven't been staged
        for commit. The developer may just have scratch files.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        assert _branch(api_sub) == "main"
        (api_sub / "scratch.txt").write_text("# just a scratch file\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""

    def test_blocks_staged_changes_on_deploy_branch(self, hub_with_deploy_branches):
        """Returns an error when subproject has staged changes on deploy branch.

        Staged but uncommitted changes on the deploy branch are equally
        dangerous — the developer should be on a feature branch.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        (api_sub / "staged.py").write_text("# staged on deploy\n")
        _git(["add", "staged.py"], api_sub)

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result != ""
        assert "uncommitted changes" in result

    def test_allows_clean_deploy_branch(self, hub_with_deploy_branches):
        """Returns empty string when deploy branch is clean (no changes).

        A clean deploy branch is fine — the developer hasn't started
        editing yet or has already committed/stashed changes.
        """
        hub = hub_with_deploy_branches["hub"]

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""

    def test_allows_dirty_feature_branch(self, hub_with_deploy_branches):
        """Returns empty string when changes are on a feature branch (not deploy).

        Dirty changes on a feature branch are expected and correct —
        that's the whole point of feature branches.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        _git(["checkout", "-b", "feature/work"], api_sub)
        (api_sub / "work.py").write_text("# feature work\n")

        result = validate_not_on_deploy_branch("api", root=hub)

        assert result == ""

    def test_preflight_blocks_dirty_deploy_branch(self, hub_with_deploy_branches):
        """push_preflight blocks when a subproject has dirty changes on deploy.

        validate_not_on_deploy_branch is wired into push_preflight, so
        modified tracked files on the deploy branch must prevent the push.
        """
        hub = hub_with_deploy_branches["hub"]
        api_sub = hub / "projects" / "api"

        # Modify a tracked file on the deploy branch
        (api_sub / "README.md").write_text("# accidental edit on deploy\n")

        result = push_preflight(projects=["api"], root=hub)

        assert result["can_proceed"] is False
        assert len(result["blocked"]) == 1
        assert "api" == result["blocked"][0]["name"]
        assert "deploy branch" in result["blocked"][0]["reason"]

    def test_coordinated_push_blocks_dirty_deploy_branch(
        self, hub_with_deploy_branches
    ):
        """coordinated_push blocks when subproject has dirty changes on deploy.

        The full coordinated_push flow should fail at preflight when
        a subproject has modified tracked files on the deploy branch.
        """
        hub = hub_with_deploy_branches["hub"]
        api_bare = hub_with_deploy_branches["api_bare"]
        api_sub = hub / "projects" / "api"

        deploy_sha_before = _remote_sha(api_bare, "main")

        # Modify a tracked file on the deploy branch
        (api_sub / "README.md").write_text("# risky direct edit\n")

        result = coordinated_push(root=hub)

        assert result["pushed"] is False
        assert "Preflight FAILED" in result["report"]

        # Remote deploy branch must be untouched
        assert _remote_sha(api_bare, "main") == deploy_sha_before
