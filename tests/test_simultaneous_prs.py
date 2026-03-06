"""Test: Workflow supports simultaneous PRs across multiple subprojects (US-PRJ-7-5).

Verifies acceptance criterion for story US-PRJ-7:
    > Workflow supports simultaneous PRs across multiple subprojects

Tests that multiple changesets and PRs can coexist and proceed independently:
1. Multiple subprojects can have independent feature branches pushed simultaneously
2. Independent changesets generate correct PR commands without interference
3. PR status checking works correctly across multiple active changesets
4. Hub ref updates for one changeset don't block unrelated changesets
5. Full end-to-end: two independent changesets proceed through the workflow in parallel
"""

import json
import os
import subprocess
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
from projectman.hub.registry import (
    is_project_blocked_by_changeset,
    push_subprojects,
    update_hub_refs,
)
from projectman.models import ChangesetStatus
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


def _remote_branch_exists(bare_repo, branch):
    """Check if a branch exists in a bare repo."""
    result = _git(["rev-parse", "--verify", branch], bare_repo, check=False)
    return result.returncode == 0


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


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_three_subprojects(tmp_path):
    """Real git hub with THREE subprojects for simultaneous PR testing.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            mobile.git/       bare remote for mobile
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/    submodule (on main)
                projects/web/    submodule (on main)
                projects/mobile/ submodule (on main)
                .project/        PM metadata with changeset support
    """
    env = {"tmp": tmp_path}

    # Create subproject bare repos and seed with initial commits
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
        "projects": ["api", "web", "mobile"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    # Add submodules tracking main
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

    # Set protocol.file.allow in each submodule
    for name in ("api", "web", "mobile"):
        _git(["config", "protocol.file.allow", "always"], hub / "projects" / name)

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    env["hub"] = hub
    return env


# ─── Tests: Simultaneous feature branches ────────────────────────


class TestSimultaneousFeatureBranches:
    """Multiple subprojects can have independent feature branches pushed at the same time."""

    def test_three_subprojects_push_independent_feature_branches(self, hub_three_subprojects):
        """All three subprojects can push different feature branches simultaneously.

        Each subproject creates its own feature branch for its own work.
        Pushing all at once succeeds and each remote gets only its feature branch.
        """
        hub = hub_three_subprojects["hub"]

        # Create independent feature branches in all three subprojects
        branches = {
            "api": "feature/auth-service",
            "web": "feature/dashboard-ui",
            "mobile": "feature/push-notifications",
        }
        for name, branch in branches.items():
            sub = hub / "projects" / name
            _git(["checkout", "-b", branch], sub)
            (sub / "feature.py").write_text(f"# {name} feature\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature work"], sub)

        # Push all three at once
        result = push_subprojects(["api", "web", "mobile"], root=hub)

        assert result["all_ok"] is True
        assert len(result["pushed"]) == 3

        pushed = {p["name"]: p["branch"] for p in result["pushed"]}
        assert pushed["api"] == "feature/auth-service"
        assert pushed["web"] == "feature/dashboard-ui"
        assert pushed["mobile"] == "feature/push-notifications"

        # Each remote has its feature branch
        for name, branch in branches.items():
            assert _remote_branch_exists(hub_three_subprojects[f"{name}_bare"], branch)

    def test_feature_branches_on_different_subprojects_dont_interfere(
        self, hub_three_subprojects
    ):
        """Feature branches in one subproject don't affect other subprojects' remotes.

        When api and web have feature branches, mobile's remote is unaffected,
        and vice versa.
        """
        hub = hub_three_subprojects["hub"]
        api_bare = hub_three_subprojects["api_bare"]
        web_bare = hub_three_subprojects["web_bare"]
        mobile_bare = hub_three_subprojects["mobile_bare"]

        # Record initial deploy branch SHAs
        api_main = _remote_sha(api_bare, "main")
        web_main = _remote_sha(web_bare, "main")
        mobile_main = _remote_sha(mobile_bare, "main")

        # Only api and web get feature branches; mobile stays on main
        for name, branch in [("api", "feature/auth"), ("web", "feature/ui")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", branch], sub)
            (sub / "new.py").write_text(f"# {name}\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: new feature"], sub)

        push_subprojects(["api", "web"], root=hub)

        # Feature branches exist on their remotes
        assert _remote_branch_exists(api_bare, "feature/auth")
        assert _remote_branch_exists(web_bare, "feature/ui")

        # mobile remote has no feature branches
        assert not _remote_branch_exists(mobile_bare, "feature/auth")
        assert not _remote_branch_exists(mobile_bare, "feature/ui")

        # All deploy branches remain unchanged
        assert _remote_sha(api_bare, "main") == api_main
        assert _remote_sha(web_bare, "main") == web_main
        assert _remote_sha(mobile_bare, "main") == mobile_main


# ─── Tests: Independent changesets ───────────────────────────────


class TestIndependentChangesets:
    """Multiple changesets covering different subprojects can coexist."""

    def test_two_changesets_different_projects_generate_independent_prs(
        self, hub_three_subprojects
    ):
        """Two changesets for different subprojects generate separate PR commands.

        Changeset A covers api+web, changeset B covers mobile. Each generates
        PR commands only for its own projects.
        """
        hub = hub_three_subprojects["hub"]
        store = Store(hub)

        cs_a = create_changeset(store, "auth-feature", ["api", "web"])
        cs_b = create_changeset(store, "push-notif", ["mobile"])

        # Set feature branch refs
        meta_a, body_a = store.get_changeset(cs_a.id)
        meta_a.entries[0].ref = "feature/auth-api"
        meta_a.entries[1].ref = "feature/auth-web"
        _persist_changeset(store, meta_a, body_a)

        meta_b, body_b = store.get_changeset(cs_b.id)
        meta_b.entries[0].ref = "feature/push-notif"
        _persist_changeset(store, meta_b, body_b)

        result_a = changeset_create_prs(store, cs_a.id)
        result_b = changeset_create_prs(store, cs_b.id)

        # Changeset A has 2 PR commands (api, web)
        assert len(result_a["pr_commands"]) == 2
        assert result_a["pr_commands"][0]["project"] == "api"
        assert result_a["pr_commands"][1]["project"] == "web"

        # Changeset B has 1 PR command (mobile)
        assert len(result_b["pr_commands"]) == 1
        assert result_b["pr_commands"][0]["project"] == "mobile"

        # Cross-references in A don't mention mobile
        for cmd in result_a["pr_commands"]:
            assert "mobile" not in cmd["command"]

        # Cross-references in B don't mention api or web
        assert "api" not in result_b["pr_commands"][0]["command"]
        assert "web" not in result_b["pr_commands"][0]["command"]

    def test_pr_status_of_one_changeset_doesnt_affect_another(self, tmp_project):
        """Checking PR status for changeset A doesn't change changeset B's status.

        Two changesets with different subprojects can have their PR status
        checked independently.
        """
        store = Store(tmp_project)

        # Add changesets dir if not present
        cs_dir = tmp_project / ".project" / "changesets"
        cs_dir.mkdir(exist_ok=True)

        # Update config to be a hub with projects
        config_path = tmp_project / ".project" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["hub"] = True
        config["projects"] = ["api", "web", "mobile"]
        config["next_changeset_id"] = 1
        config_path.write_text(yaml.dump(config))

        store = Store(tmp_project)
        cs_a = create_changeset(store, "feature-a", ["api", "web"])
        cs_b = create_changeset(store, "feature-b", ["mobile"])

        # Set PR numbers on changeset A
        meta_a, body_a = store.get_changeset(cs_a.id)
        meta_a.entries[0].pr_number = 10
        meta_a.entries[1].pr_number = 11
        _persist_changeset(store, meta_a, body_a)

        # Set PR number on changeset B
        meta_b, body_b = store.get_changeset(cs_b.id)
        meta_b.entries[0].pr_number = 20
        _persist_changeset(store, meta_b, body_b)

        # Create project dirs for status checking
        for name in ("api", "web", "mobile"):
            (tmp_project / "projects" / name).mkdir(parents=True, exist_ok=True)

        # Check A: all merged
        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("MERGED", "2026-02-28T12:00:00Z")
            result_a = changeset_check_status(store, cs_a.id, root=tmp_project)

        assert result_a["status"] == "merged"

        # Changeset B should still be open (not affected by A)
        meta_b, _ = store.get_changeset(cs_b.id)
        assert meta_b.status == ChangesetStatus.open

        # Now check B: still open
        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("OPEN")
            result_b = changeset_check_status(store, cs_b.id, root=tmp_project)

        assert result_b["status"] == "open"

        # A is still merged
        meta_a, _ = store.get_changeset(cs_a.id)
        assert meta_a.status == ChangesetStatus.merged

    def test_three_changesets_at_different_lifecycle_stages(self, tmp_project):
        """Three changesets can exist at open, partial, and merged stages simultaneously."""
        cs_dir = tmp_project / ".project" / "changesets"
        cs_dir.mkdir(exist_ok=True)

        config_path = tmp_project / ".project" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["hub"] = True
        config["projects"] = ["api", "web", "mobile"]
        config["next_changeset_id"] = 1
        config_path.write_text(yaml.dump(config))

        store = Store(tmp_project)

        cs_open = create_changeset(store, "new-feature", ["api"])
        cs_partial = create_changeset(store, "half-done", ["web"])
        cs_merged = create_changeset(store, "completed", ["mobile"])

        update_changeset_status(store, cs_partial.id, "partial")
        update_changeset_status(store, cs_merged.id, "merged")

        # All three coexist with different statuses
        all_cs = store.list_changesets()
        statuses = {cs.title: cs.status for cs in all_cs}

        assert statuses["new-feature"] == ChangesetStatus.open
        assert statuses["half-done"] == ChangesetStatus.partial
        assert statuses["completed"] == ChangesetStatus.merged


# ─── Tests: Hub ref updates with simultaneous changesets ─────────


class TestHubRefUpdatesWithSimultaneousChangesets:
    """Hub ref updates work correctly when multiple changesets are active."""

    def test_merged_changeset_updates_refs_while_another_is_open_on_different_project(
        self, hub_three_subprojects
    ):
        """A merged changeset for mobile can update hub refs even if an open changeset
        exists for api — they cover different projects, so no blocking.
        """
        hub = hub_three_subprojects["hub"]
        store = Store(hub)
        tmp = hub_three_subprojects["tmp"]

        # Create feature branch in mobile and push it
        mobile_sub = hub / "projects" / "mobile"
        _git(["checkout", "-b", "feature/push-notif"], mobile_sub)
        (mobile_sub / "push.py").write_text("# push notifications\n")
        _git(["add", "."], mobile_sub)
        _git(["commit", "-m", "mobile: push notifications"], mobile_sub)
        _git(["push", "-u", "origin", "feature/push-notif"], mobile_sub)

        # Simulate PR merge for mobile
        _merge_feature_into_main(
            hub_three_subprojects["mobile_bare"], "feature/push-notif", tmp, "mobile",
        )

        # Create an open changeset on api (should not block mobile)
        cs_api = create_changeset(store, "api-auth", ["api"])

        # Create a merged changeset on mobile
        cs_mobile = create_changeset(store, "mobile-push", ["mobile"])
        update_changeset_status(store, cs_mobile.id, "merged")

        # Verify api's open changeset does not block mobile
        blocked = is_project_blocked_by_changeset(hub, "mobile")
        assert blocked is None, "mobile should not be blocked by api's changeset"

        # Update hub refs for mobile should succeed
        result = update_hub_refs(cs_mobile.id, root=hub)
        assert "error" not in result
        assert "updated hub refs" in result
        assert "mobile" in result

    def test_open_changeset_blocks_same_project_not_others(
        self, hub_three_subprojects
    ):
        """An open changeset on api blocks another api changeset but not web or mobile."""
        hub = hub_three_subprojects["hub"]
        store = Store(hub)

        create_changeset(store, "api-feature-1", ["api"])

        # api is blocked
        assert is_project_blocked_by_changeset(hub, "api") is not None

        # web and mobile are not blocked
        assert is_project_blocked_by_changeset(hub, "web") is None
        assert is_project_blocked_by_changeset(hub, "mobile") is None

    def test_sequential_hub_ref_updates_for_different_changesets(
        self, hub_three_subprojects
    ):
        """Two changesets for different projects can both update hub refs sequentially.

        First mobile's changeset merges and updates refs, then api's changeset
        merges and updates refs. Both succeed without conflict.
        """
        hub = hub_three_subprojects["hub"]
        store = Store(hub)
        tmp = hub_three_subprojects["tmp"]

        # Create feature branches in both subprojects and push
        for name, branch, content in [
            ("mobile", "feature/push-notif", "# push\n"),
            ("api", "feature/auth", "# auth\n"),
        ]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", branch], sub)
            (sub / "feature.py").write_text(content)
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: feature work"], sub)
            _git(["push", "-u", "origin", branch], sub)

        # Simulate PR merges
        _merge_feature_into_main(
            hub_three_subprojects["mobile_bare"], "feature/push-notif", tmp, "mobile",
        )
        _merge_feature_into_main(
            hub_three_subprojects["api_bare"], "feature/auth", tmp, "api",
        )

        # Create and merge both changesets
        cs_mobile = create_changeset(store, "mobile-push", ["mobile"])
        update_changeset_status(store, cs_mobile.id, "merged")

        cs_api = create_changeset(store, "api-auth", ["api"])
        update_changeset_status(store, cs_api.id, "merged")

        # Update mobile refs first
        result_mobile = update_hub_refs(cs_mobile.id, root=hub)
        assert "error" not in result_mobile
        assert "mobile" in result_mobile

        # Then update api refs
        result_api = update_hub_refs(cs_api.id, root=hub)
        assert "error" not in result_api
        assert "api" in result_api

        # Both updates are reflected in hub commit history
        log = _git(["log", "--oneline", "-5"], hub).stdout
        assert "mobile-push" in log
        assert "api-auth" in log


# ─── Tests: Full end-to-end simultaneous workflow ────────────────


class TestFullSimultaneousWorkflow:
    """End-to-end: two independent changesets go through the full PR workflow in parallel."""

    def test_two_changesets_full_lifecycle_simultaneously(self, hub_three_subprojects):
        """Two changesets for different subprojects proceed through the full workflow.

        Timeline:
        1. Developer A creates feature branches in api+web
        2. Developer B creates feature branch in mobile
        3. Both push their feature branches
        4. Both create changesets
        5. Both generate PR commands
        6. Developer B's PR merges first → hub refs updated for mobile
        7. Developer A's PRs merge later → hub refs updated for api+web
        8. Both changesets are fully resolved
        """
        hub = hub_three_subprojects["hub"]
        store = Store(hub)
        tmp = hub_three_subprojects["tmp"]

        # Step 1: Developer A creates feature branches in api+web
        api_sub = hub / "projects" / "api"
        _git(["checkout", "-b", "feature/auth"], api_sub)
        (api_sub / "auth.py").write_text("class Auth: pass\n")
        _git(["add", "."], api_sub)
        _git(["commit", "-m", "api: add auth"], api_sub)

        web_sub = hub / "projects" / "web"
        _git(["checkout", "-b", "feature/auth-ui"], web_sub)
        (web_sub / "login.html").write_text("<form>login</form>\n")
        _git(["add", "."], web_sub)
        _git(["commit", "-m", "web: add login"], web_sub)

        # Step 2: Developer B creates feature branch in mobile
        mobile_sub = hub / "projects" / "mobile"
        _git(["checkout", "-b", "feature/push-notif"], mobile_sub)
        (mobile_sub / "push.py").write_text("# push\n")
        _git(["add", "."], mobile_sub)
        _git(["commit", "-m", "mobile: add push"], mobile_sub)

        # Step 3: Both push feature branches
        result = push_subprojects(["api", "web", "mobile"], root=hub)
        assert result["all_ok"] is True
        assert len(result["pushed"]) == 3

        # Step 4: Both create changesets
        cs_auth = create_changeset(store, "add-auth", ["api", "web"])
        meta_auth, body_auth = store.get_changeset(cs_auth.id)
        meta_auth.entries[0].ref = "feature/auth"
        meta_auth.entries[1].ref = "feature/auth-ui"
        _persist_changeset(store, meta_auth, body_auth)

        cs_push = create_changeset(store, "push-notifications", ["mobile"])
        meta_push, body_push = store.get_changeset(cs_push.id)
        meta_push.entries[0].ref = "feature/push-notif"
        _persist_changeset(store, meta_push, body_push)

        # Step 5: Both generate PR commands independently
        prs_auth = changeset_create_prs(store, cs_auth.id)
        prs_push = changeset_create_prs(store, cs_push.id)

        assert len(prs_auth["pr_commands"]) == 2
        assert len(prs_push["pr_commands"]) == 1

        # Verify no cross-contamination
        for cmd in prs_auth["pr_commands"]:
            assert "mobile" not in cmd["command"]
        assert "api" not in prs_push["pr_commands"][0]["command"]

        # Step 6: Developer B's PR merges first
        _merge_feature_into_main(
            hub_three_subprojects["mobile_bare"], "feature/push-notif", tmp, "mobile",
        )
        update_changeset_status(store, cs_push.id, "merged")

        # Hub ref update for mobile succeeds (auth changeset is open but on different projects)
        result_push = update_hub_refs(cs_push.id, root=hub)
        assert "error" not in result_push
        assert "mobile" in result_push

        # Auth changeset is still open — api/web refs should NOT have been touched
        meta_auth, _ = store.get_changeset(cs_auth.id)
        assert meta_auth.status == ChangesetStatus.open

        # Step 7: Developer A's PRs merge
        _merge_feature_into_main(
            hub_three_subprojects["api_bare"], "feature/auth", tmp, "api",
        )
        _merge_feature_into_main(
            hub_three_subprojects["web_bare"], "feature/auth-ui", tmp, "web",
        )
        update_changeset_status(store, cs_auth.id, "merged")

        result_auth = update_hub_refs(cs_auth.id, root=hub)
        assert "error" not in result_auth
        assert "api" in result_auth
        assert "web" in result_auth

        # Step 8: Both changesets are resolved
        meta_auth, _ = store.get_changeset(cs_auth.id)
        meta_push, _ = store.get_changeset(cs_push.id)
        assert meta_auth.status == ChangesetStatus.merged
        assert meta_push.status == ChangesetStatus.merged

        # Ref log has entries for all three projects
        ref_log = yaml.safe_load(
            (hub / ".project" / "ref-log.yaml").read_text()
        )
        projects_logged = {e["project"] for e in ref_log}
        assert "api" in projects_logged
        assert "web" in projects_logged
        assert "mobile" in projects_logged

    def test_overlapping_projects_in_simultaneous_changesets_are_blocked(
        self, hub_three_subprojects
    ):
        """When two changesets overlap on a project, the second is blocked until the first resolves.

        Changeset A covers api+web, changeset B covers web+mobile.
        B cannot update hub refs for web until A is resolved.
        """
        hub = hub_three_subprojects["hub"]
        store = Store(hub)
        tmp = hub_three_subprojects["tmp"]

        # Create feature branches and push
        for name, branch in [("api", "feature/a"), ("web", "feature/b"), ("mobile", "feature/c")]:
            sub = hub / "projects" / name
            _git(["checkout", "-b", branch], sub)
            (sub / "f.py").write_text(f"# {name}\n")
            _git(["add", "."], sub)
            _git(["commit", "-m", f"{name}: work"], sub)
            _git(["push", "-u", "origin", branch], sub)

        # Changeset A: api+web (stays open)
        cs_a = create_changeset(store, "feature-a", ["api", "web"])

        # Changeset B: web+mobile (wants to merge, but web is blocked by A)
        cs_b = create_changeset(store, "feature-b", ["web", "mobile"])

        # Merge mobile's PR
        _merge_feature_into_main(
            hub_three_subprojects["mobile_bare"], "feature/c", tmp, "mobile",
        )
        _merge_feature_into_main(
            hub_three_subprojects["web_bare"], "feature/b", tmp, "web-b",
        )
        update_changeset_status(store, cs_b.id, "merged")

        # web is blocked by cs_a (which is open and covers web)
        blocked = is_project_blocked_by_changeset(hub, "web")
        assert blocked == cs_a.id

        # B cannot update hub refs because web is blocked
        result = update_hub_refs(cs_b.id, root=hub)
        assert "error" in result
        assert "blocked" in result

        # Once A is closed/merged, B can proceed
        update_changeset_status(store, cs_a.id, "merged")
        # Merge api+web for A
        _merge_feature_into_main(
            hub_three_subprojects["api_bare"], "feature/a", tmp, "api",
        )
        result_a = update_hub_refs(cs_a.id, root=hub)
        assert "error" not in result_a

        # Now B can update (A is no longer blocking web)
        result_b = update_hub_refs(cs_b.id, root=hub)
        assert "error" not in result_b
        assert "mobile" in result_b
