"""Tests for no-auto-push behavior (US-PRJ-5-4).

Verifies acceptance criterion for story US-PRJ-5:
> Does not auto-push

After commit_project_changes(), committed changes must remain local.
Push is always an explicit, separate action via push_project_changes().
"""

import subprocess

import pytest

from projectman.store import Store


class TestCommitDoesNotPush:
    """Verify commit_project_changes() never pushes to a remote."""

    def test_commit_does_not_update_remote(self, tmp_git_project_with_remote):
        """After commit_project_changes(), the remote must NOT have the new commit."""
        store = Store(tmp_git_project_with_remote)

        # Record the remote HEAD before the commit
        remote_before = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_before = remote_before.stdout.split()[0] if remote_before.stdout.strip() else ""

        # Perform a PM mutation and commit
        store.create_story("No-push feature", "Should stay local")
        result = store.commit_project_changes()

        assert result["commit_hash"]

        # The remote must still point to the same SHA as before
        remote_after = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_after = remote_after.stdout.split()[0] if remote_after.stdout.strip() else ""

        assert remote_sha_before == remote_sha_after, (
            "commit_project_changes() must not push — remote SHA changed"
        )

    def test_local_ahead_after_commit(self, tmp_git_project_with_remote):
        """After commit, local branch should be ahead of remote (not in sync)."""
        store = Store(tmp_git_project_with_remote)
        store.create_story("Local-only story", "Must not be pushed")
        store.commit_project_changes()

        # Check that local is ahead of origin
        status = subprocess.run(
            ["git", "status", "--porcelain", "--branch"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        assert "ahead" in status.stdout, (
            "Local branch should be ahead of remote after commit (not pushed)"
        )

    def test_explicit_push_required_to_update_remote(self, tmp_git_project_with_remote):
        """Remote is only updated after an explicit push_project_changes() call."""
        store = Store(tmp_git_project_with_remote)

        store.create_story("Explicit push story", "Needs explicit push")
        commit_result = store.commit_project_changes()
        local_sha = commit_result["commit_hash"]

        # Before explicit push: remote does not have the commit
        remote_before = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_before = remote_before.stdout.split()[0] if remote_before.stdout.strip() else ""
        assert remote_sha_before != local_sha, (
            "Remote should not have the commit before explicit push"
        )

        # After explicit push: remote has the commit
        store.push_project_changes()

        remote_after = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_after = remote_after.stdout.split()[0] if remote_after.stdout.strip() else ""
        assert remote_sha_after == local_sha, (
            "Remote should have the commit only after explicit push_project_changes()"
        )

    def test_multiple_commits_stay_local(self, tmp_git_project_with_remote):
        """Multiple sequential commits must all stay local without pushing."""
        store = Store(tmp_git_project_with_remote)

        remote_before = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_before = remote_before.stdout.split()[0] if remote_before.stdout.strip() else ""

        # Create story, commit; then create task, commit — neither should push
        store.create_story("Multi-commit story", "First commit")
        store.commit_project_changes()

        store.create_task("US-TST-1", "Multi-commit task", "Second commit")
        store.commit_project_changes()

        store.update("US-TST-1-1", status="in-progress")
        store.commit_project_changes()

        # Remote must be unchanged after all three commits
        remote_after = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_after = remote_after.stdout.split()[0] if remote_after.stdout.strip() else ""

        assert remote_sha_before == remote_sha_after, (
            "Multiple commit_project_changes() calls must not push — remote SHA changed"
        )

    def test_commit_return_value_has_no_push_info(self, tmp_git_project_with_remote):
        """commit_project_changes() return dict should not contain push metadata."""
        store = Store(tmp_git_project_with_remote)
        store.create_story("Return value story", "Check return dict")

        result = store.commit_project_changes()

        # Should have commit info, not push info
        assert "commit_hash" in result
        assert "message" in result
        assert "files_changed" in result
        # Should NOT have push-related keys
        assert "remote" not in result
        assert "branch" not in result, (
            "commit result should not contain push metadata like 'branch'"
        )
