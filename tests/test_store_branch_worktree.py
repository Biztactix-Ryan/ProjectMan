"""`worktree.create_store_branch` / `ensure_store_branch` mount the store branch.

These two helpers are what puts a project's `.project/` on its own orphan
`projectman` branch and mounts it as a git worktree (ADR-001).  They used to
be reached through the hub's `add-project`; that command is gone (EPIC-PM-6)
and the helpers stayed, so they are pinned here directly.

Two halves:

* `ensure_store_branch` attaches a `projectman` branch that already exists —
  including one that only exists locally, never pushed — and does *not*
  re-scaffold over it;
* `create_store_branch` rolls the repo all the way back when the scaffold it
  is given blows up, and refuses to clobber an existing branch or store.

Every test builds real git repositories under `tmp_path`.  Nothing here may
be pointed at a checkout anyone cares about.

`GIT_AUTHOR_*`/`GIT_COMMITTER_*` are supplied because the store commit is
made inside a freshly initialised repo that has no local identity.
"""

from pathlib import Path

import pytest

from projectman import worktree
from test_migrate_worktree import git, init_repo, out, worktree_branch_for


# ─── Environment ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _git_env(monkeypatch):
    """Give git an identity for the commits these helpers make."""
    for var, value in (
        ("GIT_AUTHOR_NAME", "Test User"),
        ("GIT_AUTHOR_EMAIL", "test@example.com"),
        ("GIT_COMMITTER_NAME", "Test User"),
        ("GIT_COMMITTER_EMAIL", "test@example.com"),
    ):
        monkeypatch.setenv(var, value)


# ─── A local-only projectman branch ────────────────────────────────────────


class TestLocalBranchWithoutOrigin:
    """The branch exists locally but was never pushed — attach it, don't recreate.

    Pinned on `worktree.ensure_store_branch`, the single helper the whole
    decision lives in — the case reaches production through a repo whose
    branch was created locally by `migrate-worktree --no-push`.
    """

    @pytest.fixture
    def repo_with_local_branch(self, tmp_path):
        root = init_repo(tmp_path / "local-only")
        (root / "README.md").write_text("# local\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        bare = tmp_path / "local-origin.git"
        git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
        git("remote", "add", "origin", str(bare), cwd=root)
        git("push", "origin", "main", cwd=root)
        # A `projectman` branch that only exists here.
        worktree._create_orphan_branch(root, "projectman")
        assert worktree.branch_exists(root, "projectman")
        assert not worktree.remote_branch_exists(root, "projectman")
        return root

    def test_it_attaches_the_local_branch_and_does_not_scaffold(
        self, repo_with_local_branch
    ):
        root = repo_with_local_branch
        before = out("rev-parse", "projectman", cwd=root)
        scaffolded = []

        result = worktree.ensure_store_branch(
            root, populate=lambda path: scaffolded.append(path)
        )

        assert result["source"] == "attached"
        assert result["attached"] is True
        assert scaffolded == [], "populate must not run when the branch exists"
        assert worktree.is_worktree(root / ".project")
        assert worktree_branch_for(root, root / ".project") == "refs/heads/projectman"
        # No second, unrelated history was created on top of it.
        assert out("rev-parse", "projectman", cwd=root) == before

    def test_it_still_gitignores_the_store(self, repo_with_local_branch):
        root = repo_with_local_branch
        result = worktree.ensure_store_branch(root)
        assert result["gitignore_updated"] is True
        assert ".project/" in (root / ".gitignore").read_text()


# ─── The failure path ──────────────────────────────────────────────────────


class TestCreateStoreBranchRollsBack:
    """`create_store_branch` puts the repo back when the scaffold blows up."""

    @pytest.fixture
    def plain_repo(self, tmp_path):
        root = init_repo(tmp_path / "plain")
        (root / "README.md").write_text("# plain\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        return root

    def test_a_failing_populate_leaves_no_branch_and_no_worktree(self, plain_repo):
        root = plain_repo

        def boom(path: Path) -> None:
            (path / "half-written.md").write_text("oops\n")
            raise RuntimeError("scaffold exploded")

        with pytest.raises(RuntimeError, match="scaffold exploded"):
            worktree.create_store_branch(root, populate=boom)

        assert not worktree.branch_exists(root, "projectman")
        assert not (root / ".project").exists()
        assert "projectman" not in out("worktree", "list", "--porcelain", cwd=root)
        # The checkout itself is untouched.
        assert out("status", "--porcelain", cwd=root) == ""

    def test_it_refuses_when_the_branch_already_exists(self, plain_repo):
        root = plain_repo
        worktree._create_orphan_branch(root, "projectman")
        with pytest.raises(worktree.MigrationError, match="already exists"):
            worktree.create_store_branch(root)

    def test_it_refuses_to_overwrite_an_existing_store_directory(self, plain_repo):
        root = plain_repo
        store = root / ".project"
        store.mkdir()
        (store / "config.yaml").write_text("name: plain\n")

        with pytest.raises(worktree.MigrationError, match="refusing to overwrite"):
            worktree.create_store_branch(root)

        assert (store / "config.yaml").read_text() == "name: plain\n"
        assert not worktree.branch_exists(root, "projectman")
