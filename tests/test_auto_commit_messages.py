"""Tests for auto-generated commit messages from PM operations (US-PRJ-5-2).

Verifies acceptance criterion: "Auto-generated commit messages from PM operations"
— the system generates meaningful, structured commit messages when committing
.project/ changes produced by PM mutations.
"""

import subprocess
import yaml
import pytest

from projectman.store import Store


class TestGenerateCommitMessage:
    """Unit tests for Store._generate_commit_message()."""

    def test_single_story_file(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([".project/stories/TST-1.md"])
        assert msg == "pm: update 1 story"

    def test_multiple_stories(self, tmp_project):
        store = Store(tmp_project)
        files = [".project/stories/TST-1.md", ".project/stories/TST-2.md"]
        msg = store._generate_commit_message(files)
        assert msg == "pm: update 2 stories"

    def test_single_task_file(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([".project/tasks/TST-1-1.md"])
        assert msg == "pm: update 1 task"

    def test_multiple_tasks(self, tmp_project):
        store = Store(tmp_project)
        files = [".project/tasks/TST-1-1.md", ".project/tasks/TST-1-2.md", ".project/tasks/TST-1-3.md"]
        msg = store._generate_commit_message(files)
        assert msg == "pm: update 3 tasks"

    def test_single_epic_file(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([".project/epics/EPIC-TST-1.md"])
        assert msg == "pm: update 1 epic"

    def test_config_change(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([".project/config.yaml"])
        assert msg == "pm: update config"

    def test_index_change(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([".project/index.yaml"])
        assert msg == "pm: update config"

    def test_story_and_task_combined(self, tmp_project):
        store = Store(tmp_project)
        files = [".project/stories/TST-1.md", ".project/tasks/TST-1-1.md"]
        msg = store._generate_commit_message(files)
        assert msg == "pm: update 1 story, 1 task"

    def test_mixed_all_types(self, tmp_project):
        store = Store(tmp_project)
        files = [
            ".project/stories/TST-1.md",
            ".project/stories/TST-2.md",
            ".project/tasks/TST-1-1.md",
            ".project/epics/EPIC-TST-1.md",
            ".project/config.yaml",
        ]
        msg = store._generate_commit_message(files)
        assert msg == "pm: update 2 stories, 1 task, 1 epic, config"

    def test_empty_files_list(self, tmp_project):
        store = Store(tmp_project)
        msg = store._generate_commit_message([])
        assert msg == "pm: update project data"

    def test_message_always_starts_with_pm_prefix(self, tmp_project):
        store = Store(tmp_project)
        for files in [
            [".project/stories/TST-1.md"],
            [".project/tasks/TST-1-1.md"],
            [".project/config.yaml"],
            [".project/epics/EPIC-TST-1.md"],
            [],
        ]:
            msg = store._generate_commit_message(files)
            assert msg.startswith("pm: "), f"Message '{msg}' doesn't start with 'pm: '"


class TestCommitProjectChangesAutoMessage:
    """Integration tests: commit_project_changes() generates correct messages after PM ops."""

    def test_create_story_generates_story_message(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Auth feature", "Add login flow")

        result = store.commit_project_changes()

        assert result["message"].startswith("pm: ")
        assert "stor" in result["message"].lower()
        assert result["commit_hash"]
        assert any("stories/" in f for f in result["files_changed"])

    def test_create_task_generates_task_message(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Feature", "Description")
        store.commit_project_changes()  # commit the story first

        store.create_task("US-TST-1", "Implement endpoint", "Build the API")

        result = store.commit_project_changes()

        assert result["message"].startswith("pm: ")
        assert "task" in result["message"].lower()

    def test_create_story_and_task_generates_combined_message(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Feature", "Description")
        store.create_task("US-TST-1", "Task 1", "Do something")

        result = store.commit_project_changes()

        assert result["message"].startswith("pm: ")
        # Should mention both stories and tasks
        msg = result["message"].lower()
        assert "stor" in msg
        assert "task" in msg

    def test_update_task_generates_task_message(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Feature", "Description")
        store.create_task("US-TST-1", "Task 1", "Do something")
        store.commit_project_changes()

        store.update("US-TST-1-1", status="in-progress")

        result = store.commit_project_changes()

        assert result["message"].startswith("pm: ")
        assert "task" in result["message"].lower()

    def test_custom_message_overrides_auto(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Feature", "Description")

        result = store.commit_project_changes(message="custom: manual commit")

        assert result["message"] == "custom: manual commit"

    def test_auto_message_in_git_log(self, tmp_git_project):
        """The auto-generated message appears in git log."""
        store = Store(tmp_git_project)
        store.create_story("Feature", "Description")

        result = store.commit_project_changes()

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
        )
        assert result["message"] in log.stdout

    def test_no_changes_raises(self, tmp_git_project):
        """commit_project_changes raises when there are no changes."""
        store = Store(tmp_git_project)
        with pytest.raises(RuntimeError, match="No .project/ changes"):
            store.commit_project_changes()
