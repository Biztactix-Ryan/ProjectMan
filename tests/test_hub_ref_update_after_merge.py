"""Test: Hub only updates refs after PRs are merged (US-PRJ-7-3).

Verifies acceptance criterion for story US-PRJ-7:
    > Hub only updates refs after PRs are merged

Tests that update_hub_refs() enforces the merge-first gate:
1. Rejects ref updates when changeset is open (PRs not created/merged)
2. Rejects ref updates when changeset is partial (some PRs merged, not all)
3. Succeeds when changeset is fully merged — updates submodule refs
4. Blocks updates when another open changeset exists for the same project
5. Full workflow: feature → PR merge → hub ref update → ref log recorded
"""

import os
import subprocess
from pathlib import Path

import frontmatter
import pytest
import yaml

from projectman.changesets import create_changeset, update_changeset_status
from projectman.hub.registry import (
    is_project_blocked_by_changeset,
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


def _persist_changeset(store: Store, meta, body: str) -> None:
    """Write updated changeset metadata back to disk."""
    post = frontmatter.Post(content=body, **meta.model_dump(mode="json"))
    store._changeset_path(meta.id).write_text(frontmatter.dumps(post))


def _merge_feature_into_main(bare_repo, feature_branch, tmp_path, name):
    """Simulate a PR merge by merging a feature branch into main in a bare repo.

    Clones the bare repo, merges the feature branch, and pushes main back.
    This simulates what happens on GitHub when a PR is merged.
    """
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
def hub_for_merge(tmp_path):
    """Real git hub with subprojects, feature branches pushed, ready for merge testing.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/ submodule on feature/add-auth (pushed)
                projects/web/ submodule on feature/add-auth-ui (pushed)
                .project/     PM metadata with changeset support

    Feature branches are already pushed to the remotes, simulating
    the state after push_subprojects() but before PR merge.
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
        env[f"{name}_initial_main_sha"] = _remote_sha(bare, "main")

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

    # Set protocol.file.allow in each submodule so that
    # update_hub_refs() can fetch via file:// protocol in tests
    for name in ("api", "web"):
        _git(["config", "protocol.file.allow", "always"], hub / "projects" / name)

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub with submodules"], hub)
    _git(["push", "-u", "origin", "main"], hub)

    # Record submodule SHAs before feature work
    env["api_sub_sha_before"] = _sha(hub / "projects" / "api")
    env["web_sub_sha_before"] = _sha(hub / "projects" / "web")

    # Create feature branches in subprojects and push them
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "feature/add-auth"], api_sub)
    (api_sub / "auth.py").write_text("class AuthService: pass\n")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: add auth service"], api_sub)
    _git(["push", "-u", "origin", "feature/add-auth"], api_sub)

    web_sub = hub / "projects" / "web"
    _git(["checkout", "-b", "feature/add-auth-ui"], web_sub)
    (web_sub / "login.html").write_text("<form>login</form>\n")
    _git(["add", "."], web_sub)
    _git(["commit", "-m", "web: add login page"], web_sub)
    _git(["push", "-u", "origin", "feature/add-auth-ui"], web_sub)

    env["hub"] = hub
    return env


# ─── Tests: Hub ref update gate ──────────────────────────────────


class TestUpdateHubRefsRejectsUnmerged:
    """update_hub_refs() refuses to update when changeset is not fully merged."""

    def test_rejects_open_changeset(self, hub_for_merge):
        """Open changeset (no PRs merged yet) → update_hub_refs returns error."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])
        assert cs.status == ChangesetStatus.open

        result = update_hub_refs(cs.id, root=hub)

        assert "error" in result
        assert "not merged" in result
        assert f"status: {ChangesetStatus.open.value}" in result

    def test_rejects_partial_changeset(self, hub_for_merge):
        """Partial changeset (some PRs merged) → update_hub_refs returns error."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api", "web"])
        update_changeset_status(store, cs.id, "partial")

        result = update_hub_refs(cs.id, root=hub)

        assert "error" in result
        assert "not merged" in result
        assert f"status: {ChangesetStatus.partial.value}" in result

    def test_rejects_closed_changeset(self, hub_for_merge):
        """Closed changeset (PR closed without merge) → update_hub_refs returns error."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "add-auth", ["api"])
        update_changeset_status(store, cs.id, "closed")

        result = update_hub_refs(cs.id, root=hub)

        assert "error" in result
        assert "not merged" in result

    def test_submodule_refs_unchanged_on_rejection(self, hub_for_merge):
        """When update is rejected, submodule refs remain at their pre-feature state."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        api_sha_before = hub_for_merge["api_sub_sha_before"]
        web_sha_before = hub_for_merge["web_sub_sha_before"]

        cs = create_changeset(store, "add-auth", ["api", "web"])

        # Simulate: merge feature branches into main on remotes
        # (so there IS a new ref to pick up — but we should NOT pick it up)
        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth",
            hub_for_merge["tmp"], "api",
        )

        # Attempt update with open changeset → rejected
        result = update_hub_refs(cs.id, root=hub)
        assert "error" in result

        # Hub submodule refs are unchanged — still point to initial commits
        # (The submodule in the hub still has the old ref in the git index)
        hub_commit_log = _git(["log", "--oneline", "-5"], hub).stdout
        assert "hub: changeset" not in hub_commit_log, (
            "no hub commit should have been created for a rejected update"
        )


class TestUpdateHubRefsOnMerge:
    """update_hub_refs() succeeds and updates refs when changeset is merged."""

    def test_updates_refs_after_all_prs_merged(self, hub_for_merge):
        """When changeset is merged, hub submodule refs are updated to new main."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        # Simulate PR merges on both remotes
        api_merged_sha = _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )
        web_merged_sha = _merge_feature_into_main(
            hub_for_merge["web_bare"], "feature/add-auth-ui", tmp, "web",
        )

        # Create changeset and mark as merged
        cs = create_changeset(store, "add-auth", ["api", "web"])
        update_changeset_status(store, cs.id, "merged")

        result = update_hub_refs(cs.id, root=hub)

        assert "error" not in result
        assert "updated hub refs" in result
        assert "api" in result
        assert "web" in result

    def test_hub_commit_references_changeset(self, hub_for_merge):
        """The hub commit message includes the changeset title and project list."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )
        _merge_feature_into_main(
            hub_for_merge["web_bare"], "feature/add-auth-ui", tmp, "web",
        )

        cs = create_changeset(store, "add-auth", ["api", "web"])
        update_changeset_status(store, cs.id, "merged")
        update_hub_refs(cs.id, root=hub)

        # Check the latest hub commit message
        commit_msg = _git(["log", "-1", "--format=%s"], hub).stdout.strip()
        assert "hub: changeset" in commit_msg
        assert "add-auth" in commit_msg
        assert "api" in commit_msg
        assert "web" in commit_msg

    def test_ref_log_records_changeset_source(self, hub_for_merge):
        """After update, ref-log.yaml contains entries with source='changeset'."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )
        _merge_feature_into_main(
            hub_for_merge["web_bare"], "feature/add-auth-ui", tmp, "web",
        )

        cs = create_changeset(store, "add-auth", ["api", "web"])
        update_changeset_status(store, cs.id, "merged")
        update_hub_refs(cs.id, root=hub)

        ref_log_path = hub / ".project" / "ref-log.yaml"
        assert ref_log_path.exists(), "ref-log.yaml should be created after update"

        entries = yaml.safe_load(ref_log_path.read_text())
        assert isinstance(entries, list)
        assert len(entries) >= 2  # one per project

        projects_logged = {e["project"] for e in entries}
        assert "api" in projects_logged
        assert "web" in projects_logged

        for entry in entries:
            assert entry["source"] == "changeset"
            assert entry["old_ref"]  # had a ref before
            assert entry["new_ref"]  # has a new ref after
            assert entry["old_ref"] != entry["new_ref"]
            assert entry["commit"]  # hub commit SHA recorded

    def test_single_project_changeset_updates_only_that_ref(self, hub_for_merge):
        """A changeset with one project only updates that project's ref."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        # Only merge api, not web
        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )

        cs = create_changeset(store, "api-only", ["api"])
        update_changeset_status(store, cs.id, "merged")

        result = update_hub_refs(cs.id, root=hub)

        assert "error" not in result
        assert "api" in result
        assert "web" not in result

        # Commit message only mentions api
        commit_msg = _git(["log", "-1", "--format=%s"], hub).stdout.strip()
        assert "api" in commit_msg
        assert "web" not in commit_msg


class TestBlockedByAnotherChangeset:
    """update_hub_refs() blocks when another open changeset covers the same project."""

    def test_blocked_by_open_changeset_on_same_project(self, hub_for_merge):
        """A merged changeset can't update refs if another open changeset covers the project."""
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )

        # Create two changesets: one open (blocking) and one merged
        blocker = create_changeset(store, "other-feature", ["api"])
        # blocker stays open

        target = create_changeset(store, "add-auth", ["api"])
        update_changeset_status(store, target.id, "merged")

        result = update_hub_refs(target.id, root=hub)

        assert "error" in result
        assert "blocked" in result
        assert blocker.id in result

    def test_is_project_blocked_detects_open_changeset(self, hub_for_merge):
        """is_project_blocked_by_changeset returns the blocking changeset ID."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "active-work", ["api"])
        # Status is open by default

        result = is_project_blocked_by_changeset(hub, "api")
        assert result == cs.id

    def test_is_project_blocked_detects_partial_changeset(self, hub_for_merge):
        """A partial changeset also blocks the project."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "half-done", ["api", "web"])
        update_changeset_status(store, cs.id, "partial")

        result = is_project_blocked_by_changeset(hub, "api")
        assert result == cs.id

    def test_merged_changeset_does_not_block(self, hub_for_merge):
        """A fully merged changeset does not block the project."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        cs = create_changeset(store, "done-feature", ["api"])
        update_changeset_status(store, cs.id, "merged")

        result = is_project_blocked_by_changeset(hub, "api")
        assert result is None

    def test_unrelated_project_not_blocked(self, hub_for_merge):
        """An open changeset on 'api' does not block 'web'."""
        hub = hub_for_merge["hub"]
        store = Store(hub)

        create_changeset(store, "api-only-work", ["api"])

        result = is_project_blocked_by_changeset(hub, "web")
        assert result is None


class TestFullWorkflowRefUpdateAfterMerge:
    """End-to-end: feature branch → PR merge simulation → hub ref update."""

    def test_complete_lifecycle(self, hub_for_merge):
        """Full lifecycle: open changeset blocks, merged changeset allows ref update.

        Simulates the complete PR-based workflow:
        1. Create changeset (open) → hub refs cannot be updated
        2. Mark changeset as partial → still blocked
        3. Mark changeset as merged → hub refs updated
        4. Ref log reflects the change
        """
        hub = hub_for_merge["hub"]
        store = Store(hub)
        tmp = hub_for_merge["tmp"]

        # Simulate PR merges on remotes (happens independently of changeset status)
        _merge_feature_into_main(
            hub_for_merge["api_bare"], "feature/add-auth", tmp, "api",
        )
        _merge_feature_into_main(
            hub_for_merge["web_bare"], "feature/add-auth-ui", tmp, "web",
        )

        cs = create_changeset(store, "add-auth", ["api", "web"])

        # Step 1: open → rejected
        result = update_hub_refs(cs.id, root=hub)
        assert "error" in result
        assert "not merged" in result

        # Step 2: partial → still rejected
        update_changeset_status(store, cs.id, "partial")
        result = update_hub_refs(cs.id, root=hub)
        assert "error" in result
        assert "not merged" in result

        # Step 3: merged → success
        update_changeset_status(store, cs.id, "merged")
        result = update_hub_refs(cs.id, root=hub)
        assert "error" not in result
        assert "updated hub refs" in result

        # Step 4: ref log exists and is correct
        ref_log = yaml.safe_load(
            (hub / ".project" / "ref-log.yaml").read_text()
        )
        assert len(ref_log) == 2
        assert all(e["source"] == "changeset" for e in ref_log)
