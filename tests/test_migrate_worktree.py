"""Tests for `projectman migrate-worktree` (US-PM-19).

Every test runs against a throwaway `git init` repo under tmp_path — the
command rewrites git state, so it must never be pointed at a real checkout.
"""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import cli


def git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def out(*args, cwd):
    return git(*args, cwd=cwd).stdout.strip()


def git_bytes(*args, cwd):
    """Raw (undecoded) stdout — needed to compare binary blobs byte for byte."""
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, check=True
    ).stdout


def init_repo(root: Path) -> Path:
    """A hermetic, committer-configured git repo on branch `main`."""
    root.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=root)
    git("config", "user.name", "Test User", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "commit.gpgsign", "false", cwd=root)
    # Ignore whatever the developer's global excludes file says, so the set of
    # files git tracks here depends only on this repo.
    git("config", "core.excludesFile", "/dev/null", cwd=root)
    return root


def sha256_map(root: Path) -> dict[str, str]:
    """``{relative posix path: sha256}`` for every file under ``root``.

    The worktree's ``.git`` marker file is skipped: it only exists *after* the
    migration and is not part of the PM store.
    """
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] == ".git":
            continue
        if path.is_file():
            digests[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def perm_map(root: Path, relpaths) -> dict[str, int]:
    return {rel: (root / rel).stat().st_mode & 0o777 for rel in relpaths}


PM_FILES = {
    ".project/config.yaml": "name: demo\nprefix: DEMO\n",
    ".project/index.yaml": "entries: []\n",
    ".project/PROJECT.md": "# Demo\n",
    ".project/stories/US-DEMO-1.md": "# US-DEMO-1\n\nA story.\n",
    ".project/tasks/US-DEMO-1-1.md": "# US-DEMO-1-1\n\nA task.\n",
}

# A deliberately awkward but realistic PM store: nested dirs, a JSONL log, an
# archive subtree, a dotfile with no trailing newline, non-ASCII UTF-8 text and
# a binary blob containing NUL and 0xFF bytes.
RICH_PM_FILES: dict[str, bytes] = {
    ".project/config.yaml": b"name: demo\nprefix: DEMO\n",
    ".project/index.yaml": b"entries: []\n",
    ".project/PROJECT.md": "# Demo — café ✓\n".encode(),
    ".project/stories/US-DEMO-1.md": b"# US-DEMO-1\n\nA story.\n",
    ".project/tasks/US-DEMO-1-1.md": b"# US-DEMO-1-1\n\nA task.\n",
    ".project/sprints/SPRINT-DEMO-1.md": b"# Sprint 1\n",
    ".project/logs/activity.jsonl": b'{"id":"US-DEMO-1"}\n{"id":"US-DEMO-1-1"}\n',
    ".project/archive/2025/stories/US-OLD-1.md": b"# archived story\n",
    ".project/.pm-state": b"cursor: 7",  # dotfile, no trailing newline
    ".project/blob.bin": bytes(range(256)),  # binary: embedded NUL and 0xFF
}
RICH_EXECUTABLE = ".project/hooks/pre-commit.sh"
RICH_EMPTY_DIR = ".project/empty-drawer"


@pytest.fixture
def rich_repo(tmp_path):
    """A repo whose tracked .project/ exercises every awkward file shape."""
    root = init_repo(tmp_path / "rich")
    (root / "README.md").write_text("# demo\n")
    for rel, data in RICH_PM_FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    hook = root / RICH_EXECUTABLE
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(b"#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    # Git cannot track an empty directory; it is here so the on-disk move can
    # be checked for dropping it (see the empty-directory test below).
    (root / RICH_EMPTY_DIR).mkdir(parents=True)
    git("add", "-A", cwd=root)
    git("commit", "-m", "initial", cwd=root)
    return root


@pytest.fixture
def repo(tmp_path):
    """A git repo on branch `main` with a tracked .project/ and one other file."""
    root = init_repo(tmp_path / "repo")

    (root / "README.md").write_text("# demo\n")
    for rel, text in PM_FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git("add", "-A", cwd=root)
    git("commit", "-m", "initial", cwd=root)
    return root


@pytest.fixture
def runner():
    return CliRunner()


def migrate(runner, repo, *args):
    import os

    cwd = os.getcwd()
    os.chdir(repo)
    try:
        return runner.invoke(cli, ["migrate-worktree", *args])
    finally:
        os.chdir(cwd)


def worktree_branch_for(repo, path):
    """The branch `git worktree list --porcelain` reports for `path`, or None.

    Parses the porcelain record blocks (`worktree <path>` … blank line) so the
    branch assertion is exact rather than a substring match on human output.
    """
    target = Path(path).resolve()
    record: dict[str, str] = {}
    for line in out("worktree", "list", "--porcelain", cwd=repo).splitlines() + [""]:
        if not line.strip():
            if Path(record.get("worktree", "/nonexistent")).resolve() == target:
                return record.get("branch")
            record = {}
            continue
        key, _, value = line.partition(" ")
        record[key] = value
    return None


class TestMigration:
    def test_project_becomes_a_worktree_on_an_orphan_branch(self, runner, repo):
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        proj = repo / ".project"
        # A worktree checkout has a .git *file* pointing into the main repo.
        assert proj.joinpath(".git").is_file()
        worktrees = out("worktree", "list", cwd=repo)
        assert str(proj) in worktrees
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=proj) == "projectman"

        # Orphan: the branch's root commit has no parents and an empty tree.
        root_sha = out("rev-list", "--max-parents=0", "projectman", cwd=repo)
        assert "\n" not in root_sha
        assert out("show", "-s", "--format=%s", root_sha, cwd=repo) == "ProjectMan root"
        assert out("ls-tree", root_sha, cwd=repo) == ""
        # ...and it shares no history with main.
        assert out("rev-list", "--max-parents=0", "main", cwd=repo) != root_sha

    def test_git_registers_project_as_a_worktree_of_the_projectman_branch(
        self, runner, repo
    ):
        """`git worktree list --porcelain` must name .project on refs/heads/projectman."""
        proj = repo / ".project"
        assert worktree_branch_for(repo, proj) is None

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        assert worktree_branch_for(repo, proj) == "refs/heads/projectman"
        # The main checkout is still its own worktree on the original branch.
        assert worktree_branch_for(repo, repo) == "refs/heads/main"
        # The worktree marker resolves back into the main repo's gitdir.
        assert proj.joinpath(".git").is_file()
        assert "gitdir:" in proj.joinpath(".git").read_text()
        assert (
            Path(out("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=proj))
            .resolve()
            == (repo / ".git").resolve()
        )

    def test_the_projectman_branch_is_an_orphan_disjoint_from_main(self, runner, repo):
        """The branch's root commit is parentless and unrelated to main's history."""
        main_tip = out("rev-parse", "main", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        roots = out("rev-list", "--max-parents=0", "projectman", cwd=repo).splitlines()
        assert len(roots) == 1
        root_sha = roots[0]
        assert out("rev-list", "--count", f"{root_sha}^@", cwd=repo) == "0"
        assert out("show", "-s", "--format=%s", root_sha, cwd=repo) == "ProjectMan root"

        # Neither branch can reach the other: the histories are disjoint.
        for a, b in (("projectman", "main"), ("main", "projectman")):
            assert (
                git("merge-base", "--is-ancestor", a, b, cwd=repo, check=False).returncode
                != 0
            ), f"{a} must not be an ancestor of {b}"
        assert git("merge-base", "projectman", "main", cwd=repo, check=False).returncode != 0
        assert root_sha not in out("rev-list", "main", cwd=repo).splitlines()
        assert main_tip not in out("rev-list", "projectman", cwd=repo).splitlines()

    def test_the_main_checkout_stays_on_its_original_branch(self, runner, repo):
        """Migration must not move HEAD or rewrite the branch it was run from."""
        before_tip = out("rev-parse", "HEAD", cwd=repo)
        readme = (repo / "README.md").read_text()

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
        # The prior tip is still on main — the migration only added to it.
        assert (
            git(
                "merge-base", "--is-ancestor", before_tip, "main", cwd=repo, check=False
            ).returncode
            == 0
        )
        assert (repo / "README.md").read_text() == readme
        assert out("branch", "--format=%(refname:short)", cwd=repo).splitlines() == [
            "main",
            "projectman",
        ]

    def test_main_stops_tracking_project_and_gains_a_gitignore_entry(self, runner, repo):
        assert out("ls-files", ".project", cwd=repo) != ""

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        assert out("ls-files", ".project", cwd=repo) == ""
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
        gitignore = (repo / ".gitignore").read_text()
        assert ".project/" in gitignore.splitlines()
        # The .gitignore change and the untracking are committed on main.
        assert out("ls-files", ".gitignore", cwd=repo) == ".gitignore"
        assert git("diff", "--quiet", "HEAD", "--", ".gitignore", cwd=repo, check=False).returncode == 0
        # Unrelated files are untouched.
        assert out("ls-files", "README.md", cwd=repo) == "README.md"

    def test_main_commit_tree_contains_no_project_paths(self, runner, repo):
        """The untracking is committed, not merely staged: main's HEAD tree is clean."""
        before = out("ls-tree", "-r", "--name-only", "HEAD", cwd=repo).splitlines()
        assert any(p.startswith(".project/") for p in before)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        committed = out("ls-tree", "-r", "--name-only", "HEAD", cwd=repo).splitlines()
        assert [p for p in committed if p.startswith(".project")] == []
        assert set(committed) == {"README.md", ".gitignore"}
        # Nothing is left staged-but-uncommitted on main either.
        assert (
            git("diff", "--cached", "--quiet", "HEAD", cwd=repo, check=False).returncode == 0
        )

    def test_git_ignores_files_inside_project_on_main(self, runner, repo):
        """`git check-ignore` must agree that .project contents are ignored now."""
        assert (
            git("check-ignore", "-q", ".project/config.yaml", cwd=repo, check=False).returncode
            != 0
        )

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        for rel in PM_FILES:
            assert (
                git("check-ignore", "-q", rel, cwd=repo, check=False).returncode == 0
            ), f"{rel} should be ignored on main after migration"
        # ...and the rule that does it is the one the migration wrote.
        assert out("check-ignore", "-v", ".project/config.yaml", cwd=repo).startswith(
            ".gitignore:"
        )
        assert out("check-ignore", "-v", ".project/config.yaml", cwd=repo).split("\t")[
            0
        ].endswith(":.project/")
        # Unrelated files stay un-ignored.
        assert git("check-ignore", "-q", "README.md", cwd=repo, check=False).returncode != 0

    def test_the_main_commit_removes_project_and_only_touches_gitignore(
        self, runner, repo
    ):
        """The migration's main-branch commit has the documented message and a
        diff limited to deleting .project files plus the .gitignore entry."""
        from projectman.worktree import MAIN_COMMIT_MESSAGE

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        assert out("show", "-s", "--format=%s", "HEAD", cwd=repo) == MAIN_COMMIT_MESSAGE
        assert MAIN_COMMIT_MESSAGE == "Move .project onto the projectman worktree branch"

        changes = {
            line.split("\t")[1]: line.split("\t")[0]
            for line in out(
                "diff", "--name-status", "HEAD~1", "HEAD", cwd=repo
            ).splitlines()
        }
        assert changes == {
            **{rel: "D" for rel in PM_FILES},
            ".gitignore": "A",
        }

    def test_the_main_commit_modifies_a_pre_existing_gitignore(self, runner, repo):
        """With a .gitignore already tracked, the commit modifies it rather than
        adding one — and leaves its other rules alone."""
        (repo / ".gitignore").write_text("node_modules/\n")
        git("add", ".gitignore", cwd=repo)
        git("commit", "-m", "ignore", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        changes = {
            line.split("\t")[1]: line.split("\t")[0]
            for line in out(
                "diff", "--name-status", "HEAD~1", "HEAD", cwd=repo
            ).splitlines()
        }
        assert changes == {**{rel: "D" for rel in PM_FILES}, ".gitignore": "M"}
        assert (repo / ".gitignore").read_text().splitlines() == [
            "node_modules/",
            ".project/",
        ]

    def test_all_pm_files_survive_intact(self, runner, repo):
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        for rel, text in PM_FILES.items():
            assert (repo / rel).read_text() == text

        # And they are committed on the projectman branch.
        tracked = set(out("ls-files", cwd=repo / ".project").splitlines())
        assert tracked == {rel[len(".project/") :] for rel in PM_FILES}
        assert git("status", "--porcelain", cwd=repo / ".project").stdout.strip() == ""

    def test_the_temp_stash_is_cleaned_up_on_success(self, repo):
        import tempfile

        from projectman.worktree import migrate_to_worktree

        before = set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))
        result = migrate_to_worktree(repo)
        after = set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))

        assert result["stash"] is None
        assert after == before
        assert result["worktree_commit"]

    def test_works_without_a_remote(self, runner, repo):
        assert out("remote", cwd=repo) == ""
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

    def test_gitignore_entry_is_not_duplicated(self, runner, repo):
        (repo / ".gitignore").write_text("node_modules/\n.project/\n")
        git("add", ".gitignore", cwd=repo)
        git("commit", "-m", "ignore", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        lines = (repo / ".gitignore").read_text().splitlines()
        assert lines.count(".project/") == 1

    def test_migrating_a_repo_that_never_tracked_project(self, runner, tmp_path):
        root = tmp_path / "untracked"
        root.mkdir()
        git("init", "-b", "main", cwd=root)
        git("config", "user.name", "Test User", cwd=root)
        git("config", "user.email", "test@example.com", cwd=root)
        (root / "README.md").write_text("# demo\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        (root / ".project").mkdir()
        (root / ".project" / "config.yaml").write_text("name: demo\n")

        result = migrate(runner, root)
        assert result.exit_code == 0, result.output
        assert (root / ".project" / ".git").is_file()
        assert (root / ".project" / "config.yaml").read_text() == "name: demo\n"


class TestEnsureGitignoreEntry:
    """Unit tests for the .gitignore half of the criterion (no git required)."""

    def test_creates_gitignore_when_the_repo_has_none(self, tmp_path):
        from projectman.worktree import ensure_gitignore_entry

        assert not (tmp_path / ".gitignore").exists()
        assert ensure_gitignore_entry(tmp_path) is True
        assert (tmp_path / ".gitignore").read_text() == ".project/\n"

    def test_appends_to_an_existing_gitignore(self, tmp_path):
        from projectman.worktree import ensure_gitignore_entry

        (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc\n")
        assert ensure_gitignore_entry(tmp_path) is True
        assert (tmp_path / ".gitignore").read_text() == "node_modules/\n*.pyc\n.project/\n"

    def test_preserves_a_gitignore_with_no_trailing_newline(self, tmp_path):
        """The last existing rule must not be glued onto the new entry."""
        from projectman.worktree import ensure_gitignore_entry

        (tmp_path / ".gitignore").write_text("node_modules/")
        assert ensure_gitignore_entry(tmp_path) is True
        text = (tmp_path / ".gitignore").read_text()
        assert text == "node_modules/\n.project/\n"
        assert text.splitlines() == ["node_modules/", ".project/"]

    @pytest.mark.parametrize(
        "existing", [".project/", ".project", "/.project/", "/.project", "  .project/  "]
    )
    def test_does_not_duplicate_an_equivalent_existing_entry(self, tmp_path, existing):
        from projectman.worktree import ensure_gitignore_entry

        before = f"node_modules/\n{existing}\n*.pyc\n"
        (tmp_path / ".gitignore").write_text(before)

        assert ensure_gitignore_entry(tmp_path) is False
        assert (tmp_path / ".gitignore").read_text() == before

    def test_a_commented_out_rule_does_not_count_as_coverage(self, tmp_path):
        from projectman.worktree import ensure_gitignore_entry

        (tmp_path / ".gitignore").write_text("#.project/\n")
        assert ensure_gitignore_entry(tmp_path) is True
        assert (tmp_path / ".gitignore").read_text().splitlines() == [
            "#.project/",
            ".project/",
        ]


class TestRefusals:
    def test_refuses_when_the_branch_already_exists(self, runner, repo):
        git("branch", "projectman", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert "already exists" in result.output
        assert "attach" in result.output
        # Nothing was changed.
        assert out("ls-files", ".project", cwd=repo) != ""
        assert not (repo / ".project" / ".git").exists()

    def test_refuses_when_project_is_already_a_worktree(self, runner, repo):
        migrate(runner, repo)
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert "already" in result.output

    def test_refuses_when_there_is_no_project_directory(self, runner, tmp_path):
        root = tmp_path / "bare"
        root.mkdir()
        git("init", "-b", "main", cwd=root)
        git("config", "user.name", "Test User", cwd=root)
        git("config", "user.email", "test@example.com", cwd=root)
        (root / "README.md").write_text("# demo\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)

        result = migrate(runner, root)
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_refuses_outside_a_git_repository(self, runner, tmp_path):
        root = tmp_path / "nogit"
        (root / ".project").mkdir(parents=True)
        result = migrate(runner, root)
        assert result.exit_code == 1
        assert "not inside a git repository" in result.output


def repo_snapshot(root: Path) -> dict:
    """Everything a migration would touch, captured for a before/after compare."""
    gitignore = root / ".gitignore"
    return {
        "head": out("rev-parse", "HEAD", cwd=root),
        # Local branches *and* remote-tracking refs, with their sha.
        "refs": out("for-each-ref", "--format=%(refname) %(objectname)", cwd=root),
        "status": out("status", "--porcelain", cwd=root),
        "gitignore": gitignore.read_bytes() if gitignore.exists() else None,
        "worktrees": out("worktree", "list", "--porcelain", cwd=root),
        "project": sha256_map(root / ".project"),
    }


class TestDirtyTreeRefusal:
    """US-PM-19 criterion: "Migration refuses to run on a dirty working tree"."""

    def test_refuses_on_a_dirty_unstaged_tracked_file(self, runner, repo):
        (repo / "README.md").write_text("# demo, edited\n")
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "dirty" in result.output
        assert "commit or stash" in result.output
        assert "README.md" in result.output

    def test_refuses_on_a_staged_but_uncommitted_change(self, runner, repo):
        (repo / "README.md").write_text("# demo, staged\n")
        git("add", "README.md", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output
        assert "README.md" in result.output

    def test_refuses_on_a_modified_file_inside_project(self, runner, repo):
        """A change under .project/ would be carried into the import commit."""
        (repo / ".project" / "PROJECT.md").write_text("# Demo, edited\n")
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output
        assert ".project/PROJECT.md" in result.output

    def test_refuses_on_a_deleted_tracked_file(self, runner, repo):
        (repo / "README.md").unlink()
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output

    def test_untracked_file_outside_project_does_not_block(self, runner, repo):
        """Documented choice: untracked files elsewhere are neither moved nor
        committed by the migration, so they must not stand in its way."""
        (repo / "scratch.txt").write_text("not committed, not my problem\n")
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert (repo / "scratch.txt").read_text() == "not committed, not my problem\n"

    def test_untracked_file_inside_a_tracked_project_blocks(self, runner, repo):
        """It would otherwise be swept, unreviewed, into the import commit."""
        (repo / ".project" / "tasks" / "US-DEMO-1-2.md").write_text("# new\n")
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output

    def test_an_entirely_untracked_project_still_migrates(self, runner, tmp_path):
        """Refusing here would make the command useless for a .project/ that
        was never committed — the very case the migration is meant to fix."""
        root = init_repo(tmp_path / "untracked")
        (root / "README.md").write_text("# demo\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        for rel, text in PM_FILES.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

        result = migrate(runner, root)
        assert result.exit_code == 0, result.output
        assert worktree_branch_for(root, root / ".project") == "refs/heads/projectman"
        for rel, text in PM_FILES.items():
            assert (root / rel).read_text() == text

    def test_dirty_check_runs_before_any_mutation(self, runner, repo):
        """No orphan branch is created on the way to the dirty refusal."""
        (repo / "README.md").write_text("# demo, edited\n")
        migrate(runner, repo)
        assert git(
            "show-ref", "--verify", "--quiet", "refs/heads/projectman",
            cwd=repo, check=False,
        ).returncode != 0

    def test_the_cli_exits_1_and_reports_the_refusal_on_stderr(self, runner, repo):
        """The refusal reaches the shell as a failure, not a quiet no-op."""
        (repo / "README.md").write_text("# demo, edited\n")
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error: working tree is dirty")
        assert "commit or stash" in result.stderr
        assert "dirty" not in result.stdout

    def test_refuses_on_a_renamed_tracked_file(self, runner, repo):
        """`git mv` stages a rename; the destination path is the one reported."""
        git("mv", "README.md", "READYOU.md", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output
        assert "READYOU.md" in result.output
        assert "->" not in result.output

    def test_refuses_during_an_unresolved_merge_conflict(self, runner, repo):
        """An unmerged index is the dirtiest state there is."""
        git("checkout", "-b", "side", cwd=repo)
        (repo / "README.md").write_text("# from side\n")
        git("commit", "-am", "side edit", cwd=repo)
        git("checkout", "main", cwd=repo)
        (repo / "README.md").write_text("# from main\n")
        git("commit", "-am", "main edit", cwd=repo)
        assert git("merge", "side", cwd=repo, check=False).returncode != 0
        assert "UU README.md" in out("status", "--porcelain", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output
        assert "README.md" in result.output

    def test_more_than_ten_dirty_entries_are_summarised(self, runner, repo):
        """Only the first ten are listed; the rest are counted, not dumped."""
        extras = [f"file{n:02d}.txt" for n in range(12)]
        for name in extras:
            (repo / name).write_text("v1\n")
        git("add", "-A", cwd=repo)
        git("commit", "-m", "more files", cwd=repo)
        for name in extras:
            (repo / name).write_text("v2\n")
        (repo / "README.md").write_text("# demo, edited\n")  # 13 dirty entries

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "... and 3 more" in result.output
        listed = [ln for ln in result.output.splitlines() if ln.startswith("   M ")]
        assert len(listed) == 10
        # git orders README.md first, so the tail of the run is elided.
        assert "file11.txt" not in result.output

    def test_a_dirty_path_with_spaces_is_reported_unquoted(self, runner, repo):
        """`git status --porcelain` quotes such paths; the parser must unquote."""
        spaced = repo / ".project" / "my notes.md"
        spaced.write_text("v1\n")
        git("add", "-A", cwd=repo)
        git("commit", "-m", "spaced file", cwd=repo)
        spaced.write_text("v2\n")

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert ".project/my notes.md" in result.output
        assert '"' not in result.output

    def test_an_untracked_path_with_spaces_inside_project_still_blocks(
        self, runner, repo
    ):
        """Quoting must not smuggle an untracked PM file past the prefix check."""
        (repo / ".project" / "new notes.md").write_text("# new\n")
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "commit or stash" in result.output
        assert ".project/new notes.md" in result.output

    def test_an_ignored_file_does_not_block(self, runner, repo):
        """git never reports ignored files, and the migration must not either."""
        (repo / ".gitignore").write_text("*.log\n")
        git("add", "-A", cwd=repo)
        git("commit", "-m", "add gitignore", cwd=repo)
        (repo / "debug.log").write_text("noise\n")
        (repo / ".project" / "scratch.log").write_text("noise\n")

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert (repo / "debug.log").read_text() == "noise\n"
        assert (repo / ".project" / "scratch.log").read_text() == "noise\n"

    def test_a_dirty_refusal_pushes_nothing_to_origin(self, runner, repo, tmp_path):
        """The refusal precedes every mutation, the first push included."""
        add_origin(repo, tmp_path)
        (repo / "README.md").write_text("# demo, edited\n")

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert ls_remote(repo, "refs/heads/projectman") == ""


class TestExistingBranchRefusal:
    """US-PM-19 criterion: "Migration refuses when a projectman branch already
    exists and points at attach" — locally *and* on origin."""

    def test_refuses_when_the_branch_exists_locally_and_points_at_attach(
        self, runner, repo
    ):
        git("branch", "projectman", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "already exists" in result.output
        assert "projectman attach" in result.output

    def test_refuses_when_the_branch_exists_on_origin(self, runner, repo, tmp_path):
        """A real bare origin with `projectman` pushed to it, no local branch."""
        origin = tmp_path / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
        git("remote", "add", "origin", str(origin), cwd=repo)
        git("push", "origin", "main", cwd=repo)
        git("branch", "projectman", cwd=repo)
        git("push", "origin", "projectman", cwd=repo)
        git("branch", "-D", "projectman", cwd=repo)
        # Only the remote-tracking ref survives locally.
        assert git(
            "show-ref", "--verify", "--quiet", "refs/heads/projectman",
            cwd=repo, check=False,
        ).returncode != 0
        assert git(
            "show-ref", "--verify", "--quiet", "refs/remotes/origin/projectman",
            cwd=repo, check=False,
        ).returncode == 0

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "origin" in result.output
        assert "projectman attach" in result.output

    def test_refuses_on_a_bare_origin_ref_without_a_remote_configured(
        self, runner, repo
    ):
        """The check reads refs only — it never fetches, so a hand-written
        remote-tracking ref is enough to trigger it."""
        sha = out("rev-parse", "HEAD", cwd=repo)
        git("update-ref", "refs/remotes/origin/projectman", sha, cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "projectman attach" in result.output

    def test_a_custom_branch_name_is_checked_on_origin_too(self, runner, repo):
        sha = out("rev-parse", "HEAD", cwd=repo)
        git("update-ref", "refs/remotes/origin/pm-state", sha, cwd=repo)
        result = migrate(runner, repo, "--branch", "pm-state")
        assert result.exit_code != 0
        assert "pm-state" in result.output
        assert "projectman attach" in result.output

    def test_an_unrelated_remote_branch_does_not_block(self, runner, repo):
        sha = out("rev-parse", "HEAD", cwd=repo)
        git("update-ref", "refs/remotes/origin/feature", sha, cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

    def test_a_custom_branch_name_is_checked_locally_too(self, runner, repo):
        """`--branch` moves the check with it, and the message names it."""
        git("branch", "pm-state", cwd=repo)
        result = migrate(runner, repo, "--branch", "pm-state")
        assert result.exit_code == 1
        assert "branch 'pm-state' already exists" in result.stderr
        assert "projectman attach" in result.stderr

    def test_the_cli_reports_a_local_branch_refusal_on_stderr(self, runner, repo):
        """The refusal reaches the shell as a failure naming the branch and the
        remedy — on stderr, not stdout."""
        git("branch", "projectman", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error: branch 'projectman' already exists")
        assert "projectman attach" in result.stderr
        assert "attach" not in result.stdout

    def test_the_cli_reports_an_origin_branch_refusal_on_stderr(self, runner, repo):
        git("update-ref", "refs/remotes/origin/projectman",
            out("rev-parse", "HEAD", cwd=repo), cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error: branch 'projectman' already exists")
        assert "on origin" in result.stderr
        assert "projectman attach" in result.stderr
        assert "attach" not in result.stdout

    def test_an_unchecked_out_branch_with_unrelated_history_still_refuses(
        self, runner, repo
    ):
        """The check is by ref name, not by content: a `projectman` branch that
        is neither checked out nor related to HEAD still blocks."""
        empty_tree = out("hash-object", "-t", "tree", "/dev/null", cwd=repo)
        unrelated = out("commit-tree", empty_tree, "-m", "unrelated", cwd=repo)
        git("update-ref", "refs/heads/projectman", unrelated, cwd=repo)
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
        assert unrelated != out("rev-parse", "HEAD", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert "branch 'projectman' already exists" in result.stderr
        assert "projectman attach" in result.stderr

    def test_a_branch_on_a_non_origin_remote_does_not_block(self, runner, repo):
        """Documented scope: only `origin/<branch>` is consulted, so an
        `upstream/projectman` ref is not a refusal."""
        sha = out("rev-parse", "HEAD", cwd=repo)
        git("update-ref", "refs/remotes/upstream/projectman", sha, cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

    def test_the_branch_check_precedes_the_dirty_check(self, runner, repo):
        """A repo that is both dirty *and* has the branch gets the deterministic
        branch refusal, so the user is pointed at attach rather than at a
        cleanup that would not help."""
        git("branch", "projectman", cwd=repo)
        (repo / "README.md").write_text("# demo, edited\n")
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error: branch 'projectman' already exists")
        assert "projectman attach" in result.stderr
        assert "dirty" not in result.stderr

    def test_the_local_branch_check_never_touches_the_network(
        self, runner, repo, tmp_path
    ):
        """With an origin pointing at a path that does not exist, the local
        branch still refuses with the attach message — no fetch, no git
        transport error."""
        git("remote", "add", "origin", str(tmp_path / "nowhere.git"), cwd=repo)
        git("branch", "projectman", cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error: branch 'projectman' already exists")
        assert "projectman attach" in result.stderr
        assert "does not appear to be a git repository" not in result.stderr
        assert "Could not read from remote" not in result.stderr


class TestRefusalLeavesNoPartialState:
    """Every refusal must be a no-op: same HEAD, same refs, same .gitignore,
    same status, same PM files, no worktree."""

    def _assert_untouched(self, runner, repo, before):
        result = migrate(runner, repo)
        assert result.exit_code != 0, result.output
        assert repo_snapshot(repo) == before
        assert not (repo / ".project" / ".git").exists()
        assert worktree_branch_for(repo, repo / ".project") is None

    def test_a_dirty_tree_refusal_leaves_no_partial_state(self, runner, repo):
        (repo / "README.md").write_text("# demo, edited\n")
        self._assert_untouched(runner, repo, repo_snapshot(repo))

    def test_a_local_branch_refusal_leaves_no_partial_state(self, runner, repo):
        git("branch", "projectman", cwd=repo)
        self._assert_untouched(runner, repo, repo_snapshot(repo))

    def test_an_origin_branch_refusal_leaves_no_partial_state(self, runner, repo):
        git("update-ref", "refs/remotes/origin/projectman",
            out("rev-parse", "HEAD", cwd=repo), cwd=repo)
        self._assert_untouched(runner, repo, repo_snapshot(repo))

    def test_no_gitignore_is_created_by_a_refusal(self, runner, repo):
        assert not (repo / ".gitignore").exists()
        (repo / "README.md").write_text("# demo, edited\n")
        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert not (repo / ".gitignore").exists()


class TestStashSafety:
    def test_files_are_restored_when_the_worktree_step_fails(self, runner, repo, monkeypatch):
        """A failure after the move must put every PM file back."""
        import projectman.worktree as wt

        real_git = wt._git

        def exploding_git(*args, cwd, check=True):
            if args[:2] == ("worktree", "add"):
                raise wt.MigrationError("boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", exploding_git)

        with pytest.raises(wt.MigrationError):
            wt.migrate_to_worktree(repo)

        for rel, text in PM_FILES.items():
            assert (repo / rel).read_text() == text
        assert not (repo / ".project" / ".git").exists()

    def test_a_failed_run_can_be_retried(self, runner, repo, monkeypatch):
        """The rollback leaves no half-made branch blocking a second attempt."""
        import projectman.worktree as wt

        real_git = wt._git
        calls = {"n": 0}

        def flaky_git(*args, cwd, check=True):
            if args[:2] == ("worktree", "add"):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise wt.MigrationError("boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", flaky_git)

        with pytest.raises(wt.MigrationError):
            wt.migrate_to_worktree(repo)
        assert git("show-ref", "--verify", "--quiet", "refs/heads/projectman",
                   cwd=repo, check=False).returncode != 0

        result = wt.migrate_to_worktree(repo)
        assert result["worktree_commit"]
        for rel, text in PM_FILES.items():
            assert (repo / rel).read_text() == text


class TestPmFilesSurviveIntact:
    """US-PM-19 criterion: "All existing PM files survive the migration intact".

    `TestMigration.test_all_pm_files_survive_intact` covers the happy path for
    five plain ASCII files; these tests hold the criterion to a realistic store
    — nested directories, logs, an archive subtree, a dotfile, non-ASCII text,
    binary bytes, no trailing newline, an executable bit — and compare full
    ``{relpath: sha256}`` maps rather than a handful of strings.
    """

    def test_a_realistic_pm_store_is_byte_identical_on_disk_after_migration(
        self, runner, rich_repo
    ):
        proj = rich_repo / ".project"
        before = sha256_map(proj)
        assert set(before) == {
            rel[len(".project/") :] for rel in [*RICH_PM_FILES, RICH_EXECUTABLE]
        }
        stashes_before = set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))

        result = migrate(runner, rich_repo)
        assert result.exit_code == 0, result.output

        assert sha256_map(proj) == before
        # Name the awkward cases explicitly so a regression says which shape broke.
        assert (proj / "blob.bin").read_bytes() == bytes(range(256))
        assert (proj / ".pm-state").read_bytes() == b"cursor: 7"
        assert not (proj / ".pm-state").read_bytes().endswith(b"\n")
        assert (proj / "PROJECT.md").read_bytes() == "# Demo — café ✓\n".encode()
        assert (proj / "archive/2025/stories/US-OLD-1.md").is_file()
        # The migration also leaves no stash directory behind in the temp dir.
        assert (
            set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))
            == stashes_before
        )

    def test_every_pm_file_is_committed_on_the_projectman_branch_byte_for_byte(
        self, runner, rich_repo
    ):
        """The committed tree must match the pre-migration store exactly — not
        just the working copy that happens to sit on disk."""
        from projectman.worktree import IMPORT_COMMIT_MESSAGE

        proj = rich_repo / ".project"
        before = sha256_map(proj)

        result = migrate(runner, rich_repo)
        assert result.exit_code == 0, result.output

        committed = set(out("ls-tree", "-r", "--name-only", "HEAD", cwd=proj).splitlines())
        assert committed == set(before)

        for rel, digest in before.items():
            blob = git_bytes("show", f"projectman:{rel}", cwd=rich_repo)
            assert hashlib.sha256(blob).hexdigest() == digest, rel

        assert out("show", "-s", "--format=%s", "HEAD", cwd=proj) == IMPORT_COMMIT_MESSAGE
        # Nothing modified, staged or untracked is left over in the worktree.
        assert git("status", "--porcelain", cwd=proj).stdout.strip() == ""

    def test_file_modes_survive_the_migration(self, runner, rich_repo):
        """An executable PM file stays executable on disk and is recorded as
        mode 100755 in the projectman commit."""
        tracked = [*RICH_PM_FILES, RICH_EXECUTABLE]
        modes_before = perm_map(rich_repo, tracked)
        assert os.access(rich_repo / RICH_EXECUTABLE, os.X_OK)

        result = migrate(runner, rich_repo)
        assert result.exit_code == 0, result.output

        assert perm_map(rich_repo, tracked) == modes_before
        assert os.access(rich_repo / RICH_EXECUTABLE, os.X_OK)

        entries = {}
        for line in out("ls-tree", "-r", "HEAD", cwd=rich_repo / ".project").splitlines():
            meta, _, path = line.partition("\t")
            entries[path] = meta.split()[0]
        assert entries["hooks/pre-commit.sh"] == "100755"
        assert entries["config.yaml"] == "100644"
        assert entries["blob.bin"] == "100644"

    def test_an_empty_directory_survives_on_disk_but_is_not_committed(
        self, runner, rich_repo
    ):
        """Documented limitation: git has no representation for an empty
        directory, so it cannot appear in the projectman commit. The file move
        must still leave it on disk rather than silently dropping it."""
        empty = rich_repo / RICH_EMPTY_DIR
        assert empty.is_dir() and not any(empty.iterdir())

        result = migrate(runner, rich_repo)
        assert result.exit_code == 0, result.output

        assert empty.is_dir() and not any(empty.iterdir())
        proj = rich_repo / ".project"
        committed = out("ls-tree", "-r", "--name-only", "HEAD", cwd=proj).splitlines()
        assert not any(p.startswith("empty-drawer") for p in committed)
        # An untrackable empty dir must not leave the worktree looking dirty.
        assert git("status", "--porcelain", cwd=proj).stdout.strip() == ""

    def test_a_worktree_add_failure_leaves_every_file_intact_and_no_stash(
        self, rich_repo, monkeypatch
    ):
        """The rollback is the criterion's other half: a failure after the move
        must restore the whole store byte for byte and delete the stash."""
        import projectman.worktree as wt

        proj = rich_repo / ".project"
        before = sha256_map(proj)
        modes_before = perm_map(rich_repo, [*RICH_PM_FILES, RICH_EXECUTABLE])
        stashes_before = set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))

        real_git = wt._git

        def exploding_git(*args, cwd, check=True):
            if args[:2] == ("worktree", "add"):
                raise wt.MigrationError("boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", exploding_git)

        with pytest.raises(wt.MigrationError):
            wt.migrate_to_worktree(rich_repo)

        assert sha256_map(proj) == before
        assert perm_map(rich_repo, [*RICH_PM_FILES, RICH_EXECUTABLE]) == modes_before
        assert (rich_repo / RICH_EMPTY_DIR).is_dir()
        assert not (proj / ".git").exists()
        # The safety-net stash is removed on the failure path too.
        assert (
            set(Path(tempfile.gettempdir()).glob("projectman-migrate-*"))
            == stashes_before
        )


def add_origin(repo: Path, tmp_path: Path, name="origin.git") -> Path:
    """A real bare repo under tmp_path wired up as `origin`, with main pushed.

    Everything is on the filesystem, so these tests never touch a network.
    """
    origin = tmp_path / name
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("remote", "add", "origin", str(origin), cwd=repo)
    git("push", "origin", "main", cwd=repo)
    return origin


def ls_remote(repo: Path, ref: str) -> str:
    """The sha `git ls-remote origin <ref>` reports, or "" when absent."""
    line = out("ls-remote", "origin", ref, cwd=repo)
    return line.split("\t")[0] if line else ""


def clone_of(origin: Path, dest: Path, *args: str) -> Path:
    """A fresh `git clone` of the bare `origin` — someone else's checkout.

    Cloning is how a teammate (and `projectman attach`, US-PM-20) actually
    receives the pushed branch, so it is the honest way to assert what landed
    on the remote rather than trusting the pushing repo's own refs.
    """
    git("clone", *args, str(origin), str(dest), cwd=dest.parent)
    return dest


class TestPushToOrigin:
    """US-PM-19 criterion: "The projectman branch is pushed to origin when a
    remote exists" (task US-PM-19-9; verified by US-PM-19-6)."""

    def test_projectman_branch_is_pushed_to_origin_at_the_import_commit(
        self, runner, repo, tmp_path
    ):
        add_origin(repo, tmp_path)
        assert ls_remote(repo, "refs/heads/projectman") == ""

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        local = out("rev-parse", "projectman", cwd=repo)
        assert ls_remote(repo, "refs/heads/projectman") == local
        # ...and that sha is the import commit, not the empty root commit.
        assert out("rev-parse", "HEAD", cwd=repo / ".project") == local
        assert out("show", "-s", "--format=%s", local, cwd=repo) == (
            "Import ProjectMan state"
        )

    def test_the_pushed_branch_carries_the_pm_files(self, runner, repo, tmp_path):
        origin = add_origin(repo, tmp_path)
        assert migrate(runner, repo).exit_code == 0

        listed = out("ls-tree", "-r", "--name-only", "projectman", cwd=origin)
        assert sorted(listed.splitlines()) == sorted(
            rel.split("/", 1)[1] for rel in PM_FILES
        )

    def test_a_fresh_clone_of_origin_sees_projectman_as_an_orphan_branch(
        self, runner, repo, tmp_path
    ):
        """Orphan-ness has to survive the push: what a teammate clones must be a
        disjoint history, not a branch hanging off main."""
        origin = add_origin(repo, tmp_path)
        assert migrate(runner, repo).exit_code == 0

        clone = clone_of(origin, tmp_path / "clone")
        roots = out("rev-list", "--max-parents=0", "origin/projectman", cwd=clone)
        assert roots.splitlines() != []
        assert "\n" not in roots  # exactly one parentless commit
        assert out("show", "-s", "--format=%s", roots, cwd=clone) == "ProjectMan root"
        assert out("ls-tree", roots, cwd=clone) == ""
        # Disjoint from main: neither branch can reach the other.
        for a, b in (("origin/projectman", "origin/main"),
                     ("origin/main", "origin/projectman")):
            assert git(
                "merge-base", "--is-ancestor", a, b, cwd=clone, check=False
            ).returncode != 0

    def test_a_fresh_clone_of_origin_checks_out_byte_identical_pm_files(
        self, runner, rich_repo, tmp_path
    ):
        """The round trip US-PM-20 attach depends on: every PM file comes back
        out of origin with the same bytes it went in with."""
        origin = add_origin(rich_repo, tmp_path)
        before = sha256_map(rich_repo / ".project")
        assert migrate(runner, rich_repo).exit_code == 0

        clone = clone_of(origin, tmp_path / "clone", "--branch", "projectman")
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "projectman"
        assert sha256_map(clone) == before
        assert (clone / "blob.bin").read_bytes() == RICH_PM_FILES[".project/blob.bin"]

    def test_the_local_branch_tracks_origin_projectman(self, runner, repo, tmp_path):
        add_origin(repo, tmp_path)
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        assert (
            out("rev-parse", "--abbrev-ref", "projectman@{upstream}", cwd=repo)
            == "origin/projectman"
        )

    def test_a_custom_branch_name_is_pushed_under_that_name(
        self, runner, repo, tmp_path
    ):
        add_origin(repo, tmp_path)
        result = migrate(runner, repo, "--branch", "pm-state")
        assert result.exit_code == 0, result.output

        assert ls_remote(repo, "refs/heads/pm-state") == out(
            "rev-parse", "pm-state", cwd=repo
        )
        assert ls_remote(repo, "refs/heads/projectman") == ""

    def test_main_is_not_pushed_by_the_migration(self, runner, repo, tmp_path):
        add_origin(repo, tmp_path)
        main_before = ls_remote(repo, "refs/heads/main")

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output

        # The migration committed on main locally...
        assert out("rev-parse", "main", cwd=repo) != main_before
        # ...but only the projectman branch went to origin.
        assert ls_remote(repo, "refs/heads/main") == main_before

    def test_push_is_reported_in_the_output(self, runner, repo, tmp_path):
        add_origin(repo, tmp_path)
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert "origin/projectman" in result.output

    def test_the_result_dict_records_the_push(self, repo, tmp_path):
        from projectman.worktree import migrate_to_worktree

        add_origin(repo, tmp_path)
        result = migrate_to_worktree(repo)
        assert result["remote"] == "origin"
        assert result["pushed"] is True
        assert result["push_error"] is None


class TestNoRemoteSkipsPush:
    def test_no_remote_migrates_successfully_with_an_informational_message(
        self, runner, repo
    ):
        assert out("remote", cwd=repo) == ""
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert "no origin remote" in result.output
        assert "push -u origin projectman" in result.output

    def test_no_remote_leaves_pushed_false_in_the_result(self, repo):
        from projectman.worktree import migrate_to_worktree

        result = migrate_to_worktree(repo)
        assert result["remote"] is None
        assert result["pushed"] is False
        assert result["push_error"] is None
        assert result["worktree_commit"]

    def test_a_stale_remote_tracking_ref_without_a_remote_does_not_push(
        self, runner, repo
    ):
        """`origin/feature` in ref storage but no configured remote: the push
        must be skipped rather than blow up."""
        git("update-ref", "refs/remotes/origin/feature",
            out("rev-parse", "HEAD", cwd=repo), cwd=repo)
        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert "no origin remote" in result.output

    def test_a_non_origin_remote_alone_is_not_pushed_to(
        self, runner, repo, tmp_path
    ):
        """Only `origin` counts: a repo whose sole remote is `upstream` must be
        treated as remote-less rather than publishing to somebody else's fork."""
        upstream = tmp_path / "upstream.git"
        git("init", "--bare", "-b", "main", str(upstream), cwd=tmp_path)
        git("remote", "add", "upstream", str(upstream), cwd=repo)
        git("push", "upstream", "main", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert "no origin remote" in result.output
        assert out("ls-remote", str(upstream), "refs/heads/projectman", cwd=repo) == ""


class TestNoPushFlag:
    def test_no_push_leaves_origin_untouched_even_with_a_remote(
        self, runner, repo, tmp_path
    ):
        add_origin(repo, tmp_path)
        result = migrate(runner, repo, "--no-push")
        assert result.exit_code == 0, result.output

        assert ls_remote(repo, "refs/heads/projectman") == ""
        assert (repo / ".project" / ".git").is_file()  # migration still happened
        assert "--no-push" in result.output

    def test_no_push_leaves_the_branch_without_an_upstream(
        self, runner, repo, tmp_path
    ):
        add_origin(repo, tmp_path)
        assert migrate(runner, repo, "--no-push").exit_code == 0
        assert git(
            "rev-parse", "--abbrev-ref", "projectman@{upstream}",
            cwd=repo, check=False,
        ).returncode != 0

    def test_no_push_creates_no_remote_tracking_ref(self, runner, repo, tmp_path):
        """Not even a local `refs/remotes/origin/projectman`: leaving one behind
        would make a later re-run refuse with "already exists on origin"."""
        add_origin(repo, tmp_path)
        assert migrate(runner, repo, "--no-push").exit_code == 0

        assert git(
            "show-ref", "--verify", "--quiet", "refs/remotes/origin/projectman",
            cwd=repo, check=False,
        ).returncode != 0
        assert ls_remote(repo, "refs/heads/projectman") == ""


class TestPushFailure:
    def test_an_unreachable_remote_aborts_the_migration_cleanly(
        self, runner, repo, tmp_path
    ):
        """The first push happens when branch creation is the only mutation, so
        its failure must leave the repo exactly as it was."""
        git("remote", "add", "origin", str(tmp_path / "nope.git"), cwd=repo)
        head_before = out("rev-parse", "HEAD", cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code != 0
        assert "could not push" in result.output
        assert "--no-push" in result.output

        # Nothing migrated: no branch, no commit, no worktree, files in place.
        assert git("show-ref", "--verify", "--quiet", "refs/heads/projectman",
                   cwd=repo, check=False).returncode != 0
        assert out("rev-parse", "HEAD", cwd=repo) == head_before
        assert not (repo / ".project" / ".git").exists()
        assert not (repo / ".gitignore").exists()
        for rel, text in PM_FILES.items():
            assert (repo / rel).read_text() == text

    def test_a_failed_first_push_can_be_retried_after_fixing_the_remote(
        self, runner, repo, tmp_path
    ):
        git("remote", "add", "origin", str(tmp_path / "nope.git"), cwd=repo)
        assert migrate(runner, repo).exit_code != 0

        origin = tmp_path / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
        git("remote", "set-url", "origin", str(origin), cwd=repo)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert ls_remote(repo, "refs/heads/projectman") == out(
            "rev-parse", "projectman", cwd=repo
        )

    def test_a_failed_final_push_keeps_the_local_migration_and_warns(
        self, runner, repo, tmp_path, monkeypatch
    ):
        """The import commit has landed by then; losing correct local work over
        an unreachable remote would be far worse than an unpushed branch."""
        import projectman.worktree as wt

        add_origin(repo, tmp_path)
        real_git = wt._git
        seen = {"pushes": 0}

        def flaky_git(*args, cwd, check=True):
            if args[0] == "push":
                seen["pushes"] += 1
                if seen["pushes"] > 1:  # the post-import push only
                    return subprocess.CompletedProcess(
                        args, 1, "", "fatal: remote hung up unexpectedly"
                    )
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", flaky_git)

        result = migrate(runner, repo)
        assert result.exit_code == 0, result.output
        assert "push failed" in result.output
        assert "remote hung up" in result.output
        assert "git -C .project push" in result.output

        # The local migration is complete and the files are intact.
        assert (repo / ".project" / ".git").is_file()
        assert worktree_branch_for(repo, repo / ".project") == "refs/heads/projectman"
        for rel, text in PM_FILES.items():
            assert (repo / rel).read_text() == text
        # Origin still has only the root commit from the first push.
        assert ls_remote(repo, "refs/heads/projectman") != out(
            "rev-parse", "projectman", cwd=repo
        )

    def test_a_failed_final_push_leaves_origin_at_the_root_commit(
        self, repo, tmp_path, monkeypatch
    ):
        """Pin the exact intermediate state: the *first* push already landed the
        root commit on origin, so origin must hold that — not nothing, and not
        the import commit."""
        import projectman.worktree as wt

        add_origin(repo, tmp_path)
        real_git = wt._git
        seen = {"pushes": 0}

        def flaky_git(*args, cwd, check=True):
            if args[0] == "push":
                seen["pushes"] += 1
                if seen["pushes"] > 1:
                    return subprocess.CompletedProcess(args, 1, "", "boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", flaky_git)

        result = wt.migrate_to_worktree(repo)
        assert result["worktree_commit"] != result["root_commit"]
        assert ls_remote(repo, "refs/heads/projectman") == result["root_commit"]

    def test_a_rollback_after_the_first_push_deletes_the_remote_branch(
        self, repo, tmp_path, monkeypatch
    ):
        """The first push really happens (origin carries the root commit by the
        time the worktree is added), and the rollback takes it back off again —
        otherwise a retry would refuse with "already exists on origin"."""
        import projectman.worktree as wt

        add_origin(repo, tmp_path)
        real_git = wt._git
        observed = {}

        def exploding_git(*args, cwd, check=True):
            if args[:2] == ("worktree", "add"):
                # Sampled mid-migration: proof the first push already landed.
                observed["on_origin"] = ls_remote(repo, "refs/heads/projectman")
                observed["root"] = out("rev-parse", "projectman", cwd=repo)
                raise wt.MigrationError("boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", exploding_git)

        with pytest.raises(wt.MigrationError):
            wt.migrate_to_worktree(repo)

        assert observed["on_origin"] == observed["root"] != ""
        # ...and the rollback removed it from origin and from local ref storage.
        assert ls_remote(repo, "refs/heads/projectman") == ""
        assert git(
            "show-ref", "--verify", "--quiet", "refs/remotes/origin/projectman",
            cwd=repo, check=False,
        ).returncode != 0

    def test_a_failed_final_push_reports_pushed_false(self, repo, tmp_path, monkeypatch):
        import projectman.worktree as wt

        add_origin(repo, tmp_path)
        real_git = wt._git
        seen = {"pushes": 0}

        def flaky_git(*args, cwd, check=True):
            if args[0] == "push":
                seen["pushes"] += 1
                if seen["pushes"] > 1:
                    return subprocess.CompletedProcess(args, 1, "", "boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", flaky_git)

        result = wt.migrate_to_worktree(repo)
        assert result["pushed"] is False
        assert "boom" in result["push_error"]
        assert result["worktree_commit"]


class TestMigrationHelpText:
    """US-PM-19-9: help must cover the snapshot default and the ADR-001
    history-preserving alternative."""

    def test_help_documents_the_snapshot_default_and_filter_repo_alternative(
        self, runner
    ):
        result = runner.invoke(cli, ["migrate-worktree", "--help"])
        assert result.exit_code == 0
        assert "Snapshot import is the default" in result.output
        assert "git filter-repo --subdirectory-filter .project" in result.output
        assert "ADR-001" in result.output

    def test_help_documents_remote_handling_and_the_no_push_flag(self, runner):
        result = runner.invoke(cli, ["migrate-worktree", "--help"])
        assert result.exit_code == 0
        assert "--no-push" in result.output
        assert "push -u origin" in result.output
