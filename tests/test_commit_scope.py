"""Tests for commit scope: only .project/ files are committed (US-PRJ-5-3).

Verifies acceptance criterion for story US-PRJ-5:
> Only commits .project/ files touched by the mutation
"""

import subprocess

import pytest

from projectman.store import Store


class TestCommitOnlyProjectFiles:
    """Verify commit_project_changes() only commits .project/ files."""

    def test_non_project_files_not_committed(self, tmp_git_project):
        """Modified files outside .project/ must NOT be included in the commit."""
        store = Store(tmp_git_project)

        # Create a non-.project file (dirty working tree)
        (tmp_git_project / "README.md").write_text("hello")
        # Also create a PM mutation
        store.create_story("Feature A", "Description")

        result = store.commit_project_changes()

        # All committed files should be under .project/
        for f in result["files_changed"]:
            assert ".project/" in f, f"Non-.project file committed: {f}"

        # README.md should still be untracked / not committed
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
        )
        assert "README.md" in status.stdout

    def test_staged_non_project_files_not_in_result(self, tmp_git_project):
        """files_changed should only list .project/ paths even if other files are staged."""
        store = Store(tmp_git_project)

        # Stage a non-.project file
        (tmp_git_project / "extra.txt").write_text("extra")
        subprocess.run(
            ["git", "add", "extra.txt"],
            cwd=str(tmp_git_project),
            capture_output=True,
            check=True,
        )

        # Do a PM mutation
        store.create_story("Feature B", "Description")

        result = store.commit_project_changes()

        # Result should only report .project/ files
        for f in result["files_changed"]:
            assert ".project/" in f, f"Non-.project file in files_changed: {f}"

    def test_git_log_shows_only_project_files(self, tmp_git_project):
        """The actual git commit should contain only .project/ file changes."""
        store = Store(tmp_git_project)

        # Create a non-.project file
        (tmp_git_project / "src").mkdir(exist_ok=True)
        (tmp_git_project / "src" / "app.py").write_text("print('hello')")

        # Do a PM mutation
        store.create_story("Feature C", "Description")

        result = store.commit_project_changes()

        # Inspect the commit diff
        diff = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
            check=True,
        )
        committed_files = [f for f in diff.stdout.strip().splitlines() if f]

        for f in committed_files:
            assert f.startswith(".project/"), f"Non-.project file in commit: {f}"

        # At least one .project/ file should have been committed
        assert len(committed_files) > 0

    def test_files_changed_matches_actual_commit(self, tmp_git_project):
        """The files_changed list should match what git actually committed."""
        store = Store(tmp_git_project)
        store.create_story("Feature D", "Description")

        result = store.commit_project_changes()

        # Get actual files from the commit
        diff = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
            check=True,
        )
        actual_files = sorted(f for f in diff.stdout.strip().splitlines() if f)
        reported_files = sorted(result["files_changed"])

        # The reported files should be a subset of (or equal to) actual committed files
        # that are under .project/
        actual_project_files = [f for f in actual_files if f.startswith(".project/")]
        assert reported_files == actual_project_files

    def test_create_task_commits_only_task_file(self, tmp_git_project):
        """Creating a task should only commit the new task file (and index if any)."""
        store = Store(tmp_git_project)
        store.create_story("Feature E", "Description")
        store.commit_project_changes()  # commit the story first

        store.create_task("US-TST-1", "Implement endpoint", "Build the API")

        result = store.commit_project_changes()

        # All files should be under .project/
        for f in result["files_changed"]:
            assert ".project/" in f
        # Should include the task file
        assert any("tasks/" in f for f in result["files_changed"])

    def test_update_commits_only_updated_file(self, tmp_git_project):
        """Updating a story should only commit the changed story file."""
        store = Store(tmp_git_project)
        store.create_story("Feature F", "Description")
        store.commit_project_changes()

        store.update("US-TST-1", status="active")

        result = store.commit_project_changes()

        # Only .project/ files
        for f in result["files_changed"]:
            assert ".project/" in f
        # Should include the story file
        assert any("stories/US-TST-1.md" in f for f in result["files_changed"])

    def test_non_project_files_remain_dirty(self, tmp_git_project):
        """Non-.project files should remain in their original state after commit."""
        store = Store(tmp_git_project)

        # Create and track a file, then modify it
        (tmp_git_project / "tracked.txt").write_text("original")
        subprocess.run(
            ["git", "add", "tracked.txt"],
            cwd=str(tmp_git_project),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add tracked"],
            cwd=str(tmp_git_project),
            capture_output=True,
            check=True,
        )
        (tmp_git_project / "tracked.txt").write_text("modified")

        # PM mutation + commit
        store.create_story("Feature G", "Description")
        store.commit_project_changes()

        # tracked.txt should still show as modified
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
        )
        assert "tracked.txt" in status.stdout
        # And the content should still be the modified version
        assert (tmp_git_project / "tracked.txt").read_text() == "modified"
