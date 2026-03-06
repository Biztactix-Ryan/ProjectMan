"""Tests for auto-commit behavior across mutation types and config states (US-PRJ-5-7).

Covers seven scenarios:
1. Enabled + create story → git log shows commit with `pm: create US-TST-X`
2. Enabled + update task → commit with `pm: update US-TST-X-X status=done`
3. Disabled → no new commit, file is untracked
4. Only .project/ files → other dirty files excluded from commit
5. Not a git repo → mutation succeeds, warning logged, no crash
6. No auto-push → `git log origin/main..HEAD` shows unpushed commit
7. Hub mode subproject → subproject auto_commit overrides hub setting
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
        ["git", "log", "--pretty=format:%s", f"-{count}"],
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


# ─── Scenario 1: Enabled + create story ─────────────────────────


class TestEnabledCreateStory:
    """auto_commit=True, create a story → commit with 'pm: create US-TST-X'."""

    def test_create_story_produces_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Auth feature", "Add login flow")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: create US-TST-1"

    def test_commit_contains_story_file(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Auth feature", "Add login flow")

        files = _git_show_files(tmp_git_project)
        assert any("stories/US-TST-1.md" in f for f in files)


# ─── Scenario 2: Enabled + update task ──────────────────────────


class TestEnabledUpdateTask:
    """auto_commit=True, update task status → commit with 'pm: update ... status=done'."""

    def test_update_task_status_produces_commit(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")
        auto_commit_store.create_task("US-TST-1", "Task", "Desc")

        auto_commit_store.update("US-TST-1-1", status="done")

        messages = _git_log(tmp_git_project, 1)
        assert messages[0] == "pm: update US-TST-1-1 status=done"

    def test_update_task_with_multiple_fields(self, auto_commit_store, tmp_git_project):
        auto_commit_store.create_story("Story", "Desc")
        auto_commit_store.create_task("US-TST-1", "Task", "Desc")

        auto_commit_store.update("US-TST-1-1", status="in-progress", assignee="alice")

        messages = _git_log(tmp_git_project, 1)
        msg = messages[0]
        assert msg.startswith("pm: update US-TST-1-1")
        assert "status=in-progress" in msg
        assert "assignee=alice" in msg


# ─── Scenario 3: Disabled ───────────────────────────────────────


class TestDisabled:
    """auto_commit=False (default), mutations produce no new commits."""

    def test_create_story_no_commit(self, tmp_git_project):
        store = Store(tmp_git_project)
        initial_log = _git_log(tmp_git_project)

        store.create_story("Story", "Description")

        after_log = _git_log(tmp_git_project)
        assert initial_log == after_log

    def test_created_file_is_untracked(self, tmp_git_project):
        store = Store(tmp_git_project)

        store.create_story("Story", "Description")

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
        )
        # The new story file should show as untracked or modified, not committed
        # Git may show the directory or the file depending on whether the dir is new
        assert ".project/stories" in status.stdout

    def test_update_no_commit(self, tmp_git_project):
        store = Store(tmp_git_project)
        store.create_story("Story", "Desc")
        initial_log = _git_log(tmp_git_project)

        store.update("US-TST-1", status="active")

        after_log = _git_log(tmp_git_project)
        assert initial_log == after_log


# ─── Scenario 4: Only .project/ files ───────────────────────────


class TestOnlyProjectFiles:
    """auto_commit=True with dirty non-.project/ files → only .project/ in the commit."""

    def test_dirty_files_excluded_from_commit(self, auto_commit_store, tmp_git_project):
        # Create a dirty non-.project/ file
        (tmp_git_project / "README.md").write_text("hello world")
        (tmp_git_project / "src").mkdir(exist_ok=True)
        (tmp_git_project / "src" / "app.py").write_text("print('hello')")

        auto_commit_store.create_story("Feature", "Description")

        # All committed files should be under .project/
        files = _git_show_files(tmp_git_project)
        for f in files:
            assert ".project/" in f, f"Non-.project file committed: {f}"

    def test_dirty_files_remain_dirty(self, auto_commit_store, tmp_git_project):
        (tmp_git_project / "README.md").write_text("hello world")

        auto_commit_store.create_story("Feature", "Description")

        # README.md should still be untracked
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_git_project),
            capture_output=True,
            text=True,
        )
        assert "README.md" in status.stdout

    def test_modified_tracked_file_not_committed(self, auto_commit_store, tmp_git_project):
        """A modified tracked file outside .project/ should not be included in auto-commit."""
        # Create and commit a tracked file
        (tmp_git_project / "tracked.txt").write_text("original")
        subprocess.run(
            ["git", "add", "tracked.txt"],
            cwd=str(tmp_git_project), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add tracked"],
            cwd=str(tmp_git_project), capture_output=True, check=True,
        )
        # Modify it (dirty but not staged)
        (tmp_git_project / "tracked.txt").write_text("modified")

        auto_commit_store.create_story("Feature", "Description")

        files = _git_show_files(tmp_git_project)
        for f in files:
            assert ".project/" in f, f"Non-.project file in auto-commit: {f}"
        # tracked.txt should still be modified
        assert (tmp_git_project / "tracked.txt").read_text() == "modified"


# ─── Scenario 5: Not a git repo ─────────────────────────────────


class TestNotAGitRepo:
    """auto_commit=True but no .git dir → mutation succeeds, no crash."""

    def test_create_story_succeeds_without_git(self, tmp_project):
        _enable_auto_commit(tmp_project)
        store = Store(tmp_project)

        meta, _ = store.create_story("Story", "Desc")

        assert meta.id == "US-TST-1"
        assert (tmp_project / ".project" / "stories" / "US-TST-1.md").exists()

    def test_create_task_succeeds_without_git(self, tmp_project):
        _enable_auto_commit(tmp_project)
        store = Store(tmp_project)
        store.create_story("Story", "Desc")

        task_meta = store.create_task("US-TST-1", "Task", "Desc")

        assert task_meta.id == "US-TST-1-1"

    def test_update_succeeds_without_git(self, tmp_project):
        _enable_auto_commit(tmp_project)
        store = Store(tmp_project)
        store.create_story("Story", "Desc")

        meta = store.update("US-TST-1", status="active")

        assert meta.status.value == "active"

    def test_warning_logged_when_no_git(self, tmp_project, caplog):
        """auto-commit should log a warning when git is unavailable."""
        _enable_auto_commit(tmp_project)
        store = Store(tmp_project)

        import logging
        with caplog.at_level(logging.WARNING, logger="projectman.store"):
            store.create_story("Story", "Desc")

        # The warning should mention auto-commit failure (git add or commit failed)
        auto_commit_warnings = [
            r for r in caplog.records
            if "auto-commit" in r.message.lower()
        ]
        assert len(auto_commit_warnings) > 0, (
            "Expected a warning about auto-commit failure when not in a git repo"
        )


# ─── Scenario 6: No auto-push ───────────────────────────────────


class TestNoAutoPush:
    """After auto-commit, committed changes stay local (not pushed)."""

    def test_auto_commit_does_not_push(self, tmp_git_project_with_remote):
        _enable_auto_commit(tmp_git_project_with_remote)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(tmp_git_project_with_remote), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "enable auto_commit"],
            cwd=str(tmp_git_project_with_remote), capture_output=True, check=True,
        )
        store = Store(tmp_git_project_with_remote)

        store.create_story("Local-only feature", "Should not be pushed")

        # Verify there are unpushed commits
        result = subprocess.run(
            ["git", "log", "--oneline", "@{upstream}..HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        # Should have at least 2 unpushed commits (enable + create story)
        unpushed = [l for l in result.stdout.strip().splitlines() if l]
        assert len(unpushed) >= 1, "Expected unpushed commits after auto-commit"

    def test_remote_unchanged_after_auto_commit(self, tmp_git_project_with_remote):
        _enable_auto_commit(tmp_git_project_with_remote)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(tmp_git_project_with_remote), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "enable auto_commit"],
            cwd=str(tmp_git_project_with_remote), capture_output=True, check=True,
        )
        # Push the enable commit so we have a baseline
        subprocess.run(
            ["git", "push"],
            cwd=str(tmp_git_project_with_remote), capture_output=True,
        )

        remote_before = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_before = remote_before.stdout.split()[0] if remote_before.stdout.strip() else ""

        store = Store(tmp_git_project_with_remote)
        store.create_story("Feature", "Should stay local")

        remote_after = subprocess.run(
            ["git", "ls-remote", "origin", "HEAD"],
            cwd=str(tmp_git_project_with_remote),
            capture_output=True,
            text=True,
        )
        remote_sha_after = remote_after.stdout.split()[0] if remote_after.stdout.strip() else ""

        assert remote_sha_before == remote_sha_after, (
            "auto-commit must not push — remote SHA changed"
        )


# ─── Scenario 7: Hub mode subproject ────────────────────────────


class TestHubSubprojectOverride:
    """auto_commit in subproject config overrides hub setting."""

    @pytest.fixture
    def hub_with_subproject(self, tmp_git_hub):
        """Create a hub with auto_commit=False and a subproject with auto_commit=True."""
        hub_root = tmp_git_hub
        hub_config_path = hub_root / ".project" / "config.yaml"

        # Hub has auto_commit=False (default)
        with open(hub_config_path) as f:
            hub_config = yaml.safe_load(f)
        hub_config["auto_commit"] = False
        with open(hub_config_path, "w") as f:
            yaml.dump(hub_config, f)

        # Create subproject directory structure
        sub_dir = hub_root / ".project" / "projects" / "myapp"
        sub_dir.mkdir(parents=True)
        (sub_dir / "stories").mkdir()
        (sub_dir / "tasks").mkdir()
        (sub_dir / "epics").mkdir(exist_ok=True)

        sub_config = {
            "name": "myapp",
            "prefix": "APP",
            "description": "A sub-project",
            "hub": False,
            "auto_commit": True,
            "next_story_id": 1,
            "next_epic_id": 1,
            "projects": [],
        }
        with open(sub_dir / "config.yaml", "w") as f:
            yaml.dump(sub_config, f)

        # Commit all setup
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(hub_root), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "setup hub with subproject"],
            cwd=str(hub_root), capture_output=True, check=True,
        )

        return hub_root

    def test_subproject_auto_commits_when_hub_does_not(self, hub_with_subproject):
        """Subproject with auto_commit=True creates commits even if hub is False."""
        hub_root = hub_with_subproject
        sub_dir = hub_root / ".project" / "projects" / "myapp"

        sub_store = Store(hub_root, project_dir=sub_dir)

        initial_log = _git_log(hub_root)

        sub_store.create_story("Subproject feature", "Implemented in subproject")

        after_log = _git_log(hub_root, 1)
        assert after_log[0] == "pm: create US-APP-1"
        assert after_log != initial_log

    def test_hub_store_does_not_auto_commit(self, hub_with_subproject):
        """Hub Store with auto_commit=False does not create commits."""
        hub_root = hub_with_subproject

        hub_store = Store(hub_root)
        initial_log = _git_log(hub_root)

        hub_store.create_story("Hub story", "Should not auto-commit")

        after_log = _git_log(hub_root)
        assert initial_log == after_log

    def test_subproject_commit_contains_subproject_files(self, hub_with_subproject):
        """Auto-commit from subproject should include subproject files."""
        hub_root = hub_with_subproject
        sub_dir = hub_root / ".project" / "projects" / "myapp"

        sub_store = Store(hub_root, project_dir=sub_dir)
        sub_store.create_story("Feature", "Description")

        files = _git_show_files(hub_root)
        assert any("projects/myapp/" in f for f in files)
