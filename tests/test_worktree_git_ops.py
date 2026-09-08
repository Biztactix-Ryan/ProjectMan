"""PM git operations against a worktree-mounted ``.project/`` (US-PM-21).

EPIC-PM-3 / ADR-001 hypothesised that once ``.project/`` is a worktree of the
``projectman`` branch, git commands "just work" because git resolves the
branch from the directory they run in.  That is true only for commands run
*inside* the store — and every PM git op used to run from the repo root:

* ``Store.commit_project_changes`` ran ``git add .project`` at the root,
  which git refuses for the now-ignored worktree path;
* ``Store.push_project_changes`` pushed the *root's* branch (main).

These tests pin the corrected behaviour on real repos with real bare origins:
commits land on the projectman branch and never touch main, pushes move only
that branch, and the status dashboard reports the store distinctly.  The
plain-directory shape (no migration) is checked alongside so the fix is
proven not to change it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from projectman.cli import cli
from projectman.store import NothingToCommit, Store, _cache
from projectman.worktree import (
    IMPORT_COMMIT_MESSAGE,
    MigrationError,
    describe_store_state,
    migrate_to_worktree,
    push_branch,
    store_git_state,
    store_status_payload,
    worktree_branch,
)
from test_migrate_worktree import add_origin, clone_of, git, init_repo, out


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _config(name: str, prefix: str) -> dict:
    return {
        "name": name,
        "prefix": prefix,
        "description": "",
        "next_story_id": 1,
    }


def write_store(root: Path) -> Path:
    """A minimal but loadable PM store under ``root/.project``."""
    pm = root / ".project"
    (pm / "stories").mkdir(parents=True)
    (pm / "tasks").mkdir()
    (pm / "config.yaml").write_text(yaml.safe_dump(_config("demo", "DEMO")))
    (pm / "PROJECT.md").write_text("# Demo\n")
    # Since US-PM-29 the five index files are derived and pm_commit rebuilds
    # them immediately before staging.  A scaffolded store has them on disk
    # and gitignored (US-PM-29-6), so these fixtures do too — otherwise the
    # rebuild would stage five files behind every commit and "a clean store
    # is nothing to commit" could never hold.
    from projectman.indexer import write_index, write_store_gitignore
    from projectman.store import Store

    write_index(Store(root))
    write_store_gitignore(pm)
    return pm


def head(repo: Path, ref: str = "HEAD") -> str:
    return out("rev-parse", ref, cwd=repo)


def ls_remote(repo: Path, ref: str) -> str:
    line = out("ls-remote", "origin", ref, cwd=repo)
    return line.split()[0] if line else ""


def porcelain(repo: Path) -> str:
    return out("status", "--porcelain", "--untracked-files=all", cwd=repo)


def tree_paths(repo: Path, ref: str) -> list[str]:
    return out("ls-tree", "-r", "--name-only", ref, cwd=repo).splitlines()


def gitlinks(repo: Path, ref: str = "HEAD") -> list[str]:
    """Paths committed as submodule pointers (mode 160000) in ``ref``."""
    return [
        line.split("\t", 1)[1]
        for line in out("ls-tree", "-r", ref, cwd=repo).splitlines()
        if line.startswith("160000 ")
    ]


def touch_story(root: Path, name: str = "US-DEMO-1") -> Path:
    path = root / ".project" / "stories" / f"{name}.md"
    path.write_text(f"---\nid: {name}\ntitle: A story\nstatus: backlog\n---\n\nBody.\n")
    return path


@pytest.fixture(autouse=True)
def _clear_store_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def plain(tmp_path):
    """A repo with a bare origin whose ``.project/`` is still tracked on main."""
    root = init_repo(tmp_path / "plain")
    write_store(root)
    (root / "README.md").write_text("# demo\n")
    git("add", "-A", cwd=root)
    git("commit", "-m", "init", cwd=root)
    add_origin(root, tmp_path, name="plain-origin.git")
    git("branch", "--set-upstream-to=origin/main", "main", cwd=root)
    return root


@pytest.fixture
def mounted(plain):
    """The same repo after ``migrate-worktree``, with both branches on origin."""
    result = migrate_to_worktree(plain)
    assert result["pushed"], result
    git("push", "origin", "main", cwd=plain)
    assert worktree_branch(plain, plain / ".project") == "projectman"
    return plain


# ─── store_git_state ──────────────────────────────────────────────────────


class TestStoreGitState:
    """The one helper every git op consults to learn which branch owns the store."""

    def test_a_plain_store_reports_the_checked_out_branch(self, plain):
        state = store_git_state(plain)
        assert state["worktree"] is False
        assert state["branch"] == "main"
        assert state["detached"] is False
        assert state["head"] == head(plain)
        assert state["upstream"] == "origin/main"
        assert (state["ahead"], state["behind"]) == (0, 0)
        assert state["dirty"] is False and state["dirty_count"] == 0

    def test_a_mounted_store_reports_the_projectman_branch(self, mounted):
        state = store_git_state(mounted)
        assert state["worktree"] is True
        assert state["branch"] == "projectman"
        assert state["head"] == head(mounted / ".project")
        assert state["head"] != head(mounted)
        assert state["upstream"] == "origin/projectman"
        assert (state["ahead"], state["behind"]) == (0, 0)

    def test_dirty_counts_only_files_under_the_store(self, mounted):
        touch_story(mounted)
        (mounted / "src.py").write_text("x = 1\n")  # outside the store: main's business
        state = store_git_state(mounted)
        assert state["dirty"] is True
        assert state["dirty_count"] == 1

    def test_ahead_counts_unpushed_store_commits(self, mounted):
        touch_story(mounted)
        git("add", "-A", cwd=mounted / ".project")
        git("commit", "-m", "story", cwd=mounted / ".project")
        state = store_git_state(mounted)
        assert state["ahead"] == 1 and state["behind"] == 0

    def test_behind_counts_commits_only_on_origin(self, mounted, tmp_path):
        other = clone_of(mounted / ".." / "plain-origin.git", tmp_path / "other")
        git("checkout", "projectman", cwd=other)
        (other / "PROJECT.md").write_text("# changed elsewhere\n")
        git("add", "-A", cwd=other)
        git("commit", "-m", "elsewhere", cwd=other)
        git("push", "origin", "projectman", cwd=other)
        git("fetch", "origin", cwd=mounted)
        state = store_git_state(mounted)
        assert state["behind"] == 1 and state["ahead"] == 0

    def test_no_upstream_leaves_counts_at_zero(self, plain):
        git("branch", "--unset-upstream", cwd=plain)
        state = store_git_state(plain)
        assert state["upstream"] is None
        assert (state["ahead"], state["behind"]) == (0, 0)

    def test_a_detached_store_head_is_reported(self, mounted):
        git("checkout", "--detach", cwd=mounted / ".project")
        state = store_git_state(mounted)
        assert state["branch"] is None
        assert state["detached"] is True
        assert state["head"] == head(mounted / ".project")

    def test_a_missing_store_is_the_all_clean_shape(self, tmp_path):
        state = store_git_state(tmp_path)
        assert state["branch"] is None and state["worktree"] is False
        assert state["head"] is None and state["dirty"] is False

    def test_a_store_outside_any_repo_is_not_detached(self, tmp_path):
        (tmp_path / ".project").mkdir()
        state = store_git_state(tmp_path)
        assert state["branch"] is None
        assert state["detached"] is False
        assert state["head"] is None

    def test_a_custom_project_dir_is_honoured(self, plain):
        (plain / "pm").mkdir()
        state = store_git_state(plain, "pm")
        assert state["path"] == "pm"
        assert state["branch"] == "main"


class TestDescribeStoreState:
    def test_clean_worktree(self, mounted):
        assert describe_store_state(store_git_state(mounted)) == (
            ".project on projectman (worktree), clean"
        )

    def test_dirty_plain_directory_with_counts(self):
        text = describe_store_state({
            "path": ".project", "worktree": False, "branch": "main",
            "dirty": True, "dirty_count": 3, "ahead": 2, "behind": 1,
            "upstream": "origin/main",
        })
        assert text == ".project on main (plain directory), 3 uncommitted files, 2 ahead, 1 behind"

    def test_one_file_is_singular_and_no_upstream_is_named(self):
        text = describe_store_state({
            "path": ".project", "worktree": True, "branch": "projectman",
            "dirty": True, "dirty_count": 1, "ahead": 0, "behind": 0, "upstream": None,
        })
        assert "1 uncommitted file," in text
        assert text.endswith("no upstream")

    def test_detached_and_repo_less_stores_are_named(self):
        assert "on detached HEAD" in describe_store_state(
            {"path": ".project", "worktree": True, "branch": None, "detached": True}
        )
        assert "on no git" in describe_store_state({"path": ".project", "branch": None})


# ─── push_branch ──────────────────────────────────────────────────────────


class TestPushBranch:
    def test_pushes_the_named_branch_from_the_root(self, mounted):
        touch_story(mounted)
        git("add", "-A", cwd=mounted / ".project")
        git("commit", "-m", "story", cwd=mounted / ".project")
        proc = push_branch(mounted, "projectman")
        assert proc.returncode == 0
        assert ls_remote(mounted, "refs/heads/projectman") == head(mounted / ".project")

    def test_set_upstream_configures_tracking(self, plain):
        git("branch", "--unset-upstream", cwd=plain)
        assert push_branch(plain, "main", set_upstream=True).returncode == 0
        assert out("rev-parse", "--abbrev-ref", "main@{upstream}", cwd=plain) == "origin/main"

    def test_a_failed_push_is_returned_not_raised(self, mounted):
        git("remote", "set-url", "origin", str(mounted / "nowhere.git"), cwd=mounted)
        proc = push_branch(mounted, "projectman")
        assert proc.returncode != 0
        assert proc.stderr

    def test_a_relative_remote_url_resolves_from_the_root(self, plain, tmp_path):
        """A remote at ``../x.git`` is relative to wherever git runs; pushing
        from inside ``.project/`` would look one level too deep."""
        rel_origin = tmp_path / "rel-origin.git"
        git("init", "--bare", "-b", "main", str(rel_origin), cwd=tmp_path)
        git("remote", "set-url", "origin", "../rel-origin.git", cwd=plain)
        git("push", "-u", "origin", "main", cwd=plain)

        result = migrate_to_worktree(plain)

        assert result["pushed"] is True, result["push_error"]
        assert ls_remote(plain, "refs/heads/projectman") == head(plain / ".project")


# ─── Store.commit_project_changes / push_project_changes ─────────────────


class TestCommit:
    """US-PM-21 criterion: pm_commit lands commits on the projectman branch
    without dirtying main."""

    def test_the_commit_lands_on_the_projectman_branch(self, mounted):
        main_before = head(mounted)
        touch_story(mounted)

        result = Store(mounted).commit_project_changes()

        assert result["on_branch"] == "projectman"
        assert result["commit_hash"] == head(mounted / ".project")
        assert result["commit_hash"] == head(mounted, "projectman")
        assert head(mounted) == main_before

    def test_main_is_not_dirtied_and_never_regains_the_store(self, mounted):
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        assert porcelain(mounted) == ""
        assert not any(p.startswith(".project") for p in tree_paths(mounted, "main"))
        assert gitlinks(mounted, "main") == []

    def test_only_the_touched_files_are_in_the_commit(self, mounted):
        touch_story(mounted)
        result = Store(mounted).commit_project_changes()
        committed = out(
            "diff-tree", "--no-commit-id", "--name-only", "-r", result["commit_hash"],
            cwd=mounted / ".project",
        ).splitlines()
        assert committed == ["stories/US-DEMO-1.md"]
        assert result["files_changed"] == ["stories/US-DEMO-1.md"]

    def test_the_auto_message_still_recognises_stories_by_store_relative_path(self, mounted):
        touch_story(mounted)
        result = Store(mounted).commit_project_changes()
        assert result["message"] == "pm: update 1 story"

    def test_a_custom_message_is_used_verbatim(self, mounted):
        touch_story(mounted)
        result = Store(mounted).commit_project_changes(message="pm: hello")
        assert out("log", "-1", "--format=%s", cwd=mounted / ".project") == "pm: hello"

    def test_nothing_to_commit_is_the_expected_negative(self, mounted):
        with pytest.raises(NothingToCommit):
            Store(mounted).commit_project_changes()

    def test_a_file_outside_the_store_is_left_alone(self, mounted):
        (mounted / "src.py").write_text("x = 1\n")
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        assert porcelain(mounted) == "?? src.py"

    def test_a_deleted_store_file_is_committed_as_a_deletion(self, mounted):
        (mounted / ".project" / "PROJECT.md").unlink()
        result = Store(mounted).commit_project_changes()
        assert result["files_changed"] == ["PROJECT.md"]
        assert "PROJECT.md" not in tree_paths(mounted / ".project", "HEAD")

    def test_the_store_api_still_writes_through_the_worktree(self, mounted):
        """A real PM mutation, not a hand-written file, is what gets committed."""
        store = Store(mounted)
        created = store.create_story("Feature", "Description")
        story = created[0] if isinstance(created, tuple) else created
        result = store.commit_project_changes()
        assert result["on_branch"] == "projectman"
        assert f"stories/{story.id}.md" in result["files_changed"]
        assert f"stories/{story.id}.md" in tree_paths(mounted / ".project", "HEAD")


class TestCommitPlainDirectoryUnchanged:
    """The fix must not change the un-migrated shape at all."""

    def test_the_commit_lands_on_main_with_root_relative_paths(self, plain):
        touch_story(plain)
        result = Store(plain).commit_project_changes()
        assert result["on_branch"] == "main"
        assert result["commit_hash"] == head(plain)
        assert result["files_changed"] == [".project/stories/US-DEMO-1.md"]
        assert result["message"] == "pm: update 1 story"

    def test_a_non_store_file_is_not_staged(self, plain):
        (plain / "src.py").write_text("x = 1\n")
        touch_story(plain)
        Store(plain).commit_project_changes()
        assert porcelain(plain) == "?? src.py"


class TestPush:
    """US-PM-21 criterion: pm_push pushes only the projectman branch."""

    def test_pushes_the_projectman_branch_and_nothing_else(self, mounted):
        # An unpushed commit on main proves push is selective.
        (mounted / "src.py").write_text("x = 1\n")
        git("add", "src.py", cwd=mounted)
        git("commit", "-m", "code", cwd=mounted)
        origin_main_before = ls_remote(mounted, "refs/heads/main")
        touch_story(mounted)
        commit = Store(mounted).commit_project_changes()["commit_hash"]

        result = Store(mounted).push_project_changes()

        assert result == {"branch": "projectman", "remote": "origin"}
        assert ls_remote(mounted, "refs/heads/projectman") == commit
        assert ls_remote(mounted, "refs/heads/main") == origin_main_before
        assert ls_remote(mounted, "refs/heads/main") != head(mounted)

    def test_a_teammate_receives_the_pushed_store(self, mounted, tmp_path):
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        Store(mounted).push_project_changes()
        other = clone_of(tmp_path / "plain-origin.git", tmp_path / "teammate")
        assert "stories/US-DEMO-1.md" in tree_paths(other, "origin/projectman")

    def test_a_plain_store_still_pushes_the_checked_out_branch(self, plain):
        touch_story(plain)
        Store(plain).commit_project_changes()
        result = Store(plain).push_project_changes()
        assert result["branch"] == "main"
        assert ls_remote(plain, "refs/heads/main") == head(plain)

    def test_a_detached_store_head_is_refused(self, mounted):
        git("checkout", "--detach", cwd=mounted / ".project")
        with pytest.raises(RuntimeError, match="detached HEAD"):
            Store(mounted).push_project_changes()

    def test_a_detached_main_does_not_block_a_store_push(self, mounted):
        """Main's HEAD is irrelevant to the store now."""
        git("checkout", "--detach", cwd=mounted)
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        assert Store(mounted).push_project_changes()["branch"] == "projectman"

    def test_a_missing_remote_is_refused(self, mounted):
        git("remote", "remove", "origin", cwd=mounted)
        with pytest.raises(RuntimeError, match="not configured"):
            Store(mounted).push_project_changes()

    def test_a_failed_push_surfaces_git_stderr(self, mounted):
        git("remote", "set-url", "origin", str(mounted / "nowhere.git"), cwd=mounted)
        with pytest.raises(RuntimeError, match="Push failed"):
            Store(mounted).push_project_changes()

    def test_a_relative_remote_url_pushes_from_the_root(self, mounted, tmp_path):
        rel_origin = tmp_path / "rel-push.git"
        git("init", "--bare", "-b", "main", str(rel_origin), cwd=tmp_path)
        git("remote", "set-url", "origin", "../rel-push.git", cwd=mounted)
        touch_story(mounted)
        commit = Store(mounted).commit_project_changes()["commit_hash"]
        Store(mounted).push_project_changes()
        assert out("rev-parse", "projectman", cwd=rel_origin) == commit


# ─── Status dashboard ─────────────────────────────────────────────────────


class TestGitStatusReportsTheStoreDistinctly:
    """US-PM-21 criterion: pm_git_status reports the .project worktree state
    distinctly from main."""

    def test_a_mounted_store_reports_its_own_branch(self, mounted):
        data = store_status_payload(mounted)
        store = data["pm_store"]
        assert store["worktree"] is True
        assert store["branch"] == "projectman"
        assert store["upstream"] == "origin/projectman"
        assert "projectman (worktree), clean" in data["summary"]
        assert data["summary"].startswith("PM store: ")

    def test_store_dirty_and_ahead_are_separate_from_main(self, mounted):
        # Main: one unpushed commit, clean tree.  Store: one dirty file.
        (mounted / "src.py").write_text("x = 1\n")
        git("add", "src.py", cwd=mounted)
        git("commit", "-m", "code", cwd=mounted)
        touch_story(mounted)

        store = store_status_payload(mounted)["pm_store"]

        assert store["dirty"] is True and store["dirty_count"] == 1
        assert store["ahead"] == 0  # main's unpushed commit is not the store's
        assert out("rev-list", "--count", "origin/main..main", cwd=mounted) == "1"

    def test_store_ahead_after_commit_before_push(self, mounted):
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        store = store_status_payload(mounted)["pm_store"]
        assert store["ahead"] == 1
        assert "1 ahead" in store["description"]

    def test_a_plain_store_reads_as_a_plain_directory_on_main(self, plain):
        store = store_status_payload(plain)["pm_store"]
        assert store["worktree"] is False
        assert store["branch"] == "main"
        assert "(plain directory)" in store["description"]

    def test_the_payload_carries_only_the_one_store(self, mounted):
        """Hub mode is gone: no project list, no aggregate ok/issues keys."""
        data = store_status_payload(mounted)
        assert set(data) == {"summary", "pm_store"}

    def test_the_store_line_never_fails_the_dashboard(self, mounted, monkeypatch):
        import projectman.worktree as wt

        def boom(*a, **k):
            raise OSError("no git")

        monkeypatch.setattr(wt, "store_git_state", boom)
        data = store_status_payload(mounted)
        assert data["pm_store"]["branch"] is None
        assert data["pm_store"]["description"]


# ─── CLI and MCP surfaces ─────────────────────────────────────────────────


def _in(path: Path, fn):
    here = os.getcwd()
    os.chdir(path)
    try:
        return fn()
    finally:
        os.chdir(here)


class TestCli:
    def test_commit_names_the_branch(self, runner, mounted):
        touch_story(mounted)
        result = _in(mounted, lambda: runner.invoke(cli, ["commit"]))
        assert result.exit_code == 0, result.output
        assert "Branch: projectman" in result.output
        assert "stories/US-DEMO-1.md" in result.output

    def test_push_names_the_branch(self, runner, mounted):
        touch_story(mounted)
        Store(mounted).commit_project_changes()
        result = _in(mounted, lambda: runner.invoke(cli, ["push"]))
        assert result.exit_code == 0, result.output
        assert "Pushed projectman to origin" in result.output

    def test_git_status_json_carries_the_store(self, runner, mounted):
        result = _in(mounted, lambda: runner.invoke(cli, ["git-status", "--json"]))
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data) == {"summary", "pm_store"}
        assert data["pm_store"]["branch"] == "projectman"
        assert data["pm_store"]["worktree"] is True

    def test_git_status_table_shows_the_store_line(self, runner, mounted):
        result = _in(mounted, lambda: runner.invoke(cli, ["git-status"]))
        assert result.exit_code == 0, result.output
        assert "PM store: .project on projectman (worktree), clean" in result.output
        assert "branch" in result.output and "projectman" in result.output
        assert "mount" in result.output and "worktree" in result.output


class TestMcpTools:
    """The MCP wrappers route through the same code; check the visible contract."""

    def test_pm_commit_reports_the_branch(self, mounted, monkeypatch):
        from projectman.server import pm_commit

        monkeypatch.chdir(mounted)
        touch_story(mounted)
        data = yaml.safe_load(pm_commit())
        assert data["committed"]["on_branch"] == "projectman"
        assert data["committed"]["files_committed"] == 1
        assert head(mounted / ".project") == data["committed"]["commit_hash"]

    def test_pm_commit_on_a_clean_store_is_the_expected_negative(self, mounted, monkeypatch):
        from projectman.server import pm_commit

        monkeypatch.chdir(mounted)
        data = yaml.safe_load(pm_commit())
        assert data["status"] == "nothing_to_commit"

    def test_pm_push_pushes_only_the_projectman_branch(self, mounted, monkeypatch):
        from projectman.server import pm_commit, pm_push

        monkeypatch.chdir(mounted)
        (mounted / "src.py").write_text("x = 1\n")
        git("add", "src.py", cwd=mounted)
        git("commit", "-m", "code", cwd=mounted)
        touch_story(mounted)
        pm_commit()
        data = yaml.safe_load(pm_push())
        assert data["pushed"]["branch"] == "projectman"
        assert ls_remote(mounted, "refs/heads/projectman") == head(mounted / ".project")
        assert ls_remote(mounted, "refs/heads/main") != head(mounted)


# ─── Coverage of the remaining worktree.py branches ───────────────────────


class TestWorktreeModuleEdges:
    def test_worktree_branch_is_none_for_a_path_that_is_not_a_worktree(self, mounted):
        assert worktree_branch(mounted, mounted / "not-a-worktree") is None
        assert worktree_branch(mounted, mounted / ".project") == "projectman"

    def test_dirty_paths_skips_a_whitespace_only_status_line(self, plain, monkeypatch):
        import projectman.worktree as wt

        real = wt._git

        def padded(*args, cwd, check=True):
            proc = real(*args, cwd=cwd, check=check)
            if args[:2] == ("status", "--porcelain"):
                proc.stdout = "   \n" + proc.stdout
            return proc

        monkeypatch.setattr(wt, "_git", padded)
        assert wt.dirty_paths(plain) == []

    def test_a_commit_tree_failure_is_a_migration_error(self, plain, monkeypatch):
        import projectman.worktree as wt

        real_run = wt.subprocess.run

        def failing(cmd, *a, **k):
            if cmd[:2] == ["git", "commit-tree"]:
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: nope")
            return real_run(cmd, *a, **k)

        monkeypatch.setattr(wt.subprocess, "run", failing)
        with pytest.raises(MigrationError, match="git commit-tree failed: fatal: nope"):
            wt.migrate_to_worktree(plain)
        assert not (plain / ".project" / ".git").exists()
        assert out("branch", "--list", "projectman", cwd=plain) == ""

    def test_a_failure_after_the_worktree_is_mounted_removes_it_and_restores_files(
        self, plain, monkeypatch
    ):
        """The rollback path where the worktree already exists on disk."""
        import projectman.worktree as wt

        real = wt._git
        before = {p.name: p.read_text() for p in (plain / ".project").rglob("*") if p.is_file()}

        def exploding(*args, cwd, check=True):
            if args[:2] == ("commit", "-m") and args[2] == IMPORT_COMMIT_MESSAGE:
                raise wt.MigrationError("disk full")
            return real(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", exploding)
        with pytest.raises(MigrationError, match="disk full"):
            wt.migrate_to_worktree(plain)

        after = {p.name: p.read_text() for p in (plain / ".project").rglob("*") if p.is_file()}
        assert after == before
        assert not (plain / ".project" / ".git").exists()
        assert "projectman" not in out("worktree", "list", cwd=plain)
        assert out("branch", "--list", "projectman", cwd=plain) == ""

