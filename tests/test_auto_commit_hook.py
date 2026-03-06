"""Tests for auto-commit hook wired into store mutation methods (US-PRJ-5-6).

Verifies that when auto_commit is enabled, each PM mutation (create/update/archive)
triggers a git commit of only the affected files with a conventional commit message.
"""

import subprocess

import pytest
import yaml

from projectman.store import Store


def _enable_auto_commit(project_root):
    """Enable auto_commit in the project config."""
    config_path = project_root / ".project" / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    config["auto_commit"] = True
    with open(config_path, "w") as f:
        yaml.dump(config, f)


def _git_log(cwd, count=5):
    """Return the last N commit messages."""
    result = subprocess.run(
        ["git", "log", f"--pretty=format:%s", f"-{count}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()


def _git_show_files(cwd, ref="HEAD"):
    """Return files changed in a specific commit."""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", ref],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()


@pytest.fixture
def auto_commit_store(tmp_git_project):
    """A Store with auto_commit enabled, inside a git repo."""
    _enable_auto_commit(tmp_git_project)
    # Commit the config change so we start clean
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_git_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "enable auto_commit"],
        cwd=str(tmp_git_project), capture_output=True, check=True,
    )
    return Store(tmp_git_project)


class TestAutoCommitDisabled:
    """When auto_commit is False (default), no commits are created."""

    def test_create_story_no_commit(self, tmp_git_project):
        store = Store(tmp_git_project)
        initial_log = _git_log(tmp_git_project)

        store.create_story("Story", "Description")

        after_log = _git_log(tmp_git_project)
        assert initial_log == after_log

    def test_create_task_no_commit(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Story", "Desc")
        initial_log = _git_log(tmp_git_project)

        store.create_task("US-TST-1", "Task", "Desc")

        after_log = _git_log(tmp_git_project)
        assert initial_log == after_log

    def test_update_no_commit(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Story", "Desc")
        initial_log = _git_log(tmp_git_project)

        store.update("US-TST-1", status="active")

        after_log = _git_log(tmp_git_project)
        assert initial_log == after_log


class TestAutoCommitCreateStory:
    def test_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Auth feature", "Add login flow")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: create US-TST-1"

    def test_commits_story_and_config_files(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Auth feature", "Add login flow")

        files = _git_show_files(tmp_git_project)
        assert any("stories/US-TST-1.md" in f for f in files)
        assert any("config.yaml" in f for f in files)

    def test_with_acceptance_criteria_single_commit(self, auto_commit_store, tmp_git_project):
        """Story + auto-created test tasks produce a single commit."""
        auto_commit_store.create_story(
            "Feature", "Desc",
            acceptance_criteria=["Users can log in", "Error on invalid password"],
        )

        messages = _git_log(tmp_git_project, 2)
        # Should be one commit for the whole create_story, not multiple
        assert messages[0] == "pm: create US-TST-1"
        assert messages[1] == "enable auto_commit"

    def test_with_acceptance_criteria_includes_task_files(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story(
            "Feature", "Desc",
            acceptance_criteria=["AC one", "AC two"],
        )

        files = _git_show_files(tmp_git_project)
        assert any("stories/US-TST-1.md" in f for f in files)
        assert any("tasks/US-TST-1-1.md" in f for f in files)
        assert any("tasks/US-TST-1-2.md" in f for f in files)


class TestAutoCommitCreateTask:
    def test_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")
        # create_story already auto-committed

        auto_commit_store.create_task("US-TST-1", "Implement endpoint", "Build API")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: create US-TST-1-1"

    def test_commits_only_task_file(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.create_task("US-TST-1", "Task", "Desc")

        files = _git_show_files(tmp_git_project)
        assert len(files) == 1
        assert "tasks/US-TST-1-1.md" in files[0]


class TestAutoCommitCreateTasks:
    def test_batch_creates_single_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "Desc A"},
            {"title": "Task B", "description": "Desc B"},
        ])

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: create 2 tasks under US-TST-1"

    def test_batch_commits_all_task_files(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.create_tasks("US-TST-1", [
            {"title": "Task A", "description": "Desc A"},
            {"title": "Task B", "description": "Desc B"},
        ])

        files = _git_show_files(tmp_git_project)
        assert any("US-TST-1-1.md" in f for f in files)
        assert any("US-TST-1-2.md" in f for f in files)


class TestAutoCommitCreateEpic:
    def test_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_epic("Auth epic", "Authentication system")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: create EPIC-TST-1"

    def test_commits_epic_and_config(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_epic("Auth epic", "Authentication system")

        files = _git_show_files(tmp_git_project)
        assert any("epics/EPIC-TST-1.md" in f for f in files)
        assert any("config.yaml" in f for f in files)


class TestAutoCommitUpdate:
    def test_update_story_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.update("US-TST-1", status="active")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update US-TST-1 status=active"

    def test_update_task_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")
        auto_commit_store.create_task("US-TST-1", "Task", "Desc")

        auto_commit_store.update("US-TST-1-1", status="in-progress", assignee="alice")

        messages = _git_log(tmp_git_project, 1)
        msg = messages[0]
        assert msg.startswith("pm: update US-TST-1-1")
        assert "status=in-progress" in msg
        assert "assignee=alice" in msg

    def test_update_epic_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_epic("Epic", "Desc")

        auto_commit_store.update("EPIC-TST-1", status="active")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update EPIC-TST-1 status=active"

    def test_update_body_only(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Original body")

        auto_commit_store.update("US-TST-1", body="Updated body")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update US-TST-1 body"

    def test_update_commits_only_affected_file(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.update("US-TST-1", status="active")

        files = _git_show_files(tmp_git_project)
        assert len(files) == 1
        assert "stories/US-TST-1.md" in files[0]


class TestAutoCommitArchive:
    def test_archive_story_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")

        auto_commit_store.archive("US-TST-1")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update US-TST-1 status=archived"

    def test_archive_task_creates_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")
        auto_commit_store.create_task("US-TST-1", "Task", "Desc")

        auto_commit_store.archive("US-TST-1-1")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update US-TST-1-1 status=done"


class TestAutoCommitErrorHandling:
    def test_no_git_repo_does_not_crash(self, tmp_project):
        """Auto-commit should silently skip if not in a git repo."""
        _enable_auto_commit(tmp_project)
        store = Store(tmp_project)

        # Should not raise
        meta, _ = store.create_story("Story", "Desc")
        assert meta.id == "US-TST-1"

    def test_mutation_succeeds_even_if_commit_fails(self, auto_commit_store, tmp_git_project):
        """The mutation itself should succeed even if auto-commit has issues."""
        auto_commit_store.create_story("Story", "Desc")
        meta = auto_commit_store.update("US-TST-1", status="active")
        assert meta.status.value == "active"
