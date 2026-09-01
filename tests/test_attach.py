"""Tests for `projectman attach` (US-PM-20).

Attach is the fresh-clone counterpart of `migrate-worktree`: the migration
creates the `projectman` branch in the repo that owns the PM store, attach
mounts a branch that already exists.  So every test here builds the honest
shape — migrate a repo that has a real (filesystem) `origin`, then `git clone`
that origin — and runs the command in the clone.

Everything lives under tmp_path: the command runs `git worktree add`, so it
must never be pointed at a real checkout.

The git helpers and fixtures are imported from the migration tests rather than
duplicated, so both suites agree on what a test repo looks like.
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import cli
from projectman.worktree import MigrationError, attach_worktree
from test_migrate_worktree import (  # noqa: F401 — `repo`/`runner` are fixtures
    PM_FILES,
    add_origin,
    clone_of,
    git,
    init_repo,
    migrate,
    out,
    repo,
    runner,
    sha256_map,
    worktree_branch_for,
)


def attach(runner, cwd, *args):
    """Invoke `projectman attach` with the process cwd inside `cwd`."""
    here = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(cli, ["attach", *args])
    finally:
        os.chdir(here)


def upstream(repo: Path, branch: str = "projectman") -> str:
    """The configured upstream of `branch`, or "" when it has none."""
    proc = git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}",
        cwd=repo, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def reflog(repo: Path, branch: str = "projectman") -> list[str]:
    """`branch`'s reflog entries, or [] when it has none.

    Every checkout, reset or ref update on the branch appends a line here, so
    an unchanged reflog is proof that a command performed no git write — which
    is stronger than comparing the resulting state.
    """
    proc = git("reflog", "show", branch, cwd=repo, check=False)
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def tree(root: Path) -> list[str]:
    """Every entry under `root` as "<kind> <relative posix path>".

    `sha256_map` only sees files, so on its own it cannot tell an untouched
    empty subdirectory — or a symlink that was followed and replaced — from a
    deleted one. Pairing the two makes "byte-for-byte as it was" mean the
    shape of the tree as well as the content of its files.
    """
    entries = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        kind = "link" if path.is_symlink() else "dir" if path.is_dir() else "file"
        entries.append(f"{kind} {rel}")
    return entries


def worktree_list(repo: Path) -> str:
    """The porcelain worktree registry — unchanged means nothing was mounted."""
    return out("worktree", "list", "--porcelain", cwd=repo)


def publish(runner, repo: Path, origin: Path, *args: str) -> None:
    """Migrate `repo` and push both branches, as a real migration is finished.

    `migrate-worktree` pushes only the PM branch — the commit it makes on the
    current branch (untracking .project/, adding the .gitignore entry) is left
    for the developer to push. Doing that here is what makes a later clone the
    honest fresh-clone shape: origin/projectman present, no .project/ checked
    out on main.
    """
    result = migrate(runner, repo, *args)
    assert result.exit_code == 0, result.output
    git("push", "origin", "main", cwd=repo)


@pytest.fixture
def migrated(runner, repo, tmp_path):
    """A migrated repo plus the bare origin its `projectman` branch was pushed to."""
    origin = add_origin(repo, tmp_path)
    publish(runner, repo, origin)
    assert out("ls-remote", "origin", "refs/heads/projectman", cwd=repo)
    return repo, origin


@pytest.fixture
def clone(migrated, tmp_path):
    """A fresh clone of that origin — no .project/, but origin/projectman present."""
    _, origin = migrated
    dest = clone_of(origin, tmp_path / "clone")
    assert not (dest / ".project").exists()
    assert out("rev-parse", "--verify", "refs/remotes/origin/projectman", cwd=dest)
    return dest


class TestAttachOnAFreshClone:
    """US-PM-20 criterion: "projectman attach mounts the projectman branch as
    the .project worktree on a fresh clone"."""

    def test_attach_mounts_the_branch_as_the_project_worktree(self, runner, clone):
        result = attach(runner, clone)
        assert result.exit_code == 0, result.output

        proj = clone / ".project"
        assert worktree_branch_for(clone, proj) == "refs/heads/projectman"
        assert proj.joinpath(".git").is_file()
        assert "gitdir:" in proj.joinpath(".git").read_text()
        # The main checkout is untouched and still on its own branch.
        assert worktree_branch_for(clone, clone) == "refs/heads/main"

    def test_the_local_branch_is_created_tracking_the_remote_one(self, runner, clone):
        assert out("branch", "--list", "projectman", cwd=clone) == ""

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output

        assert upstream(clone) == "origin/projectman"
        assert out("rev-parse", "projectman", cwd=clone) == out(
            "rev-parse", "origin/projectman", cwd=clone
        )

    def test_the_pm_files_arrive_byte_identical(self, runner, migrated, clone):
        source, _ = migrated
        result = attach(runner, clone)
        assert result.exit_code == 0, result.output

        assert sha256_map(clone / ".project") == sha256_map(source / ".project")
        for rel, text in PM_FILES.items():
            assert (clone / rel).read_text() == text

    def test_the_mounted_worktree_is_a_clean_checkout_of_the_branch(self, runner, clone):
        """Asked from inside .project/: the branch, its upstream, nothing dirty.

        `worktree_branch_for` asks the *main* repo what it registered; these
        assertions ask the mounted checkout itself, which is what every later
        `git -C .project ...` (and every PM tool run from in there) sees.
        """
        result = attach(runner, clone)
        assert result.exit_code == 0, result.output

        proj = clone / ".project"
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=proj) == "projectman"
        assert out("rev-parse", "--abbrev-ref", "@{upstream}", cwd=proj) == (
            "origin/projectman"
        )
        # Nothing modified, staged or untracked: the checkout matches the commit.
        assert out("status", "--porcelain", cwd=proj) == ""
        assert out("rev-parse", "HEAD", cwd=proj) == out(
            "rev-parse", "origin/projectman", cwd=clone
        )

    def test_the_main_checkout_is_left_untouched(self, runner, clone):
        """Mounting the PM branch must not disturb the working branch.

        The .gitignore entry the migration committed is what keeps it that
        way: without it the freshly mounted .project/ would show up as
        untracked noise in every `git status` on main.
        """
        head_before = out("rev-parse", "HEAD", cwd=clone)
        assert out("status", "--porcelain", cwd=clone) == ""

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output

        assert out("rev-parse", "HEAD", cwd=clone) == head_before
        assert out("status", "--porcelain", cwd=clone) == ""
        assert (
            git("check-ignore", "-q", ".project", cwd=clone, check=False).returncode == 0
        )
        assert (clone / "README.md").read_text() == "# demo\n"

    def test_the_summary_names_the_branch_its_upstream_and_the_path(
        self, runner, clone
    ):
        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "projectman" in result.output
        assert "origin/projectman" in result.output
        assert str(clone / ".project") in result.output

    def test_two_clones_of_the_same_origin_attach_independently(
        self, runner, migrated, tmp_path
    ):
        """Attach is per-clone: two teammates do not interfere."""
        _, origin = migrated
        first = clone_of(origin, tmp_path / "clone-a")
        second = clone_of(origin, tmp_path / "clone-b")

        for dest in (first, second):
            result = attach(runner, dest)
            assert result.exit_code == 0, result.output

        for dest in (first, second):
            assert worktree_branch_for(dest, dest / ".project") == "refs/heads/projectman"
            assert upstream(dest) == "origin/projectman"
        # Each clone registered only its own worktree.
        assert str(second) not in out("worktree", "list", "--porcelain", cwd=first)
        assert str(first) not in out("worktree", "list", "--porcelain", cwd=second)
        # And both received the same PM files.
        assert sha256_map(first / ".project") == sha256_map(second / ".project")

    def test_an_empty_project_directory_is_mounted_over(self, runner, clone):
        (clone / ".project").mkdir()

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        assert (clone / ".project" / "config.yaml").exists()

    def test_attach_never_fetches(self, runner, migrated, clone):
        """A commit pushed to origin after the clone stays invisible.

        Attach reads local ref storage only, so what lands in the worktree is
        the clone's own origin/projectman — no network round trip is hidden in
        the command.
        """
        source, _ = migrated
        (source / ".project" / "later.md").write_text("# after the clone\n")
        git("add", "-A", cwd=source / ".project")
        git("commit", "-m", "later", cwd=source / ".project")
        git("push", "origin", "projectman", cwd=source / ".project")

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert not (clone / ".project" / "later.md").exists()


STORE_CONFIG = "name: demo\nprefix: DEMO\nnext_story_id: 2\n"

STORE_STORY = """---
id: US-DEMO-1
title: A demo story
status: ready
priority: should
points: 3
created: 2026-01-01
updated: 2026-01-02
---

The story body.
"""

STORE_TASK = """---
id: US-DEMO-1-1
story_id: US-DEMO-1
title: A demo task
status: todo
points: 1
created: 2026-01-01
updated: 2026-01-02
---

The task body.
"""


class TestTheAttachedStoreIsUsable:
    """The point of the criterion: after attach, PM tools work in the clone.

    `PM_FILES` is deliberately minimal — its markdown has no frontmatter, so
    the Store would skip it as malformed and prove nothing.  This builds a
    store the Store class can actually parse, migrates it, clones, attaches,
    and reads the items back out of the mounted worktree.
    """

    @pytest.fixture
    def store_clone(self, runner, tmp_path):
        root = init_repo(tmp_path / "storerepo")
        (root / "README.md").write_text("# demo\n")
        proj = root / ".project"
        (proj / "stories").mkdir(parents=True)
        (proj / "tasks").mkdir(parents=True)
        (proj / "config.yaml").write_text(STORE_CONFIG)
        (proj / "stories" / "US-DEMO-1.md").write_text(STORE_STORY)
        (proj / "tasks" / "US-DEMO-1-1.md").write_text(STORE_TASK)
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)

        origin = add_origin(root, tmp_path, name="store-origin.git")
        publish(runner, root, origin)
        return clone_of(origin, tmp_path / "store-clone")

    def test_a_store_opened_on_the_clone_reads_the_migrated_items(
        self, runner, store_clone
    ):
        from projectman.store import Store, _cache

        assert not (store_clone / ".project").exists()

        result = attach(runner, store_clone)
        assert result.exit_code == 0, result.output

        _cache.clear()
        store = Store(store_clone)
        assert store.config.name == "demo"
        assert store.config.prefix == "DEMO"
        assert [s.id for s in store.list_stories()] == ["US-DEMO-1"]
        assert [t.id for t in store.list_tasks()] == ["US-DEMO-1-1"]

        meta, body = store.get_story("US-DEMO-1")
        assert meta.title == "A demo story"
        assert meta.points == 3
        assert "The story body." in body


class TestAlreadyAttachedIsANoOp:
    """US-PM-20 criterion: "Attach is a friendly no-op when the worktree is
    already mounted"."""

    def test_second_attach_exits_zero_with_a_friendly_message(self, runner, clone):
        assert attach(runner, clone).exit_code == 0

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert "projectman" in result.output
        assert "Error" not in result.output

    def test_second_attach_changes_nothing(self, runner, clone):
        assert attach(runner, clone).exit_code == 0
        before = sha256_map(clone / ".project")
        head_before = out("rev-parse", "projectman", cwd=clone)
        worktrees_before = out("worktree", "list", "--porcelain", cwd=clone)

        assert attach(runner, clone).exit_code == 0

        assert sha256_map(clone / ".project") == before
        assert out("rev-parse", "projectman", cwd=clone) == head_before
        assert out("worktree", "list", "--porcelain", cwd=clone) == worktrees_before
        assert upstream(clone) == "origin/projectman"

    def test_the_no_op_message_does_not_claim_to_have_attached_anything(
        self, runner, clone
    ):
        """The friendly line, not the attach banner.

        `format_attach_result` has two branches; a regression that fell through
        to the mounting summary would still exit 0, so the message is what
        distinguishes "nothing to do" from "I just did it".
        """
        assert attach(runner, clone).exit_code == 0

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "nothing to do" in result.output
        assert ".project" in result.output
        assert "Attached .project/ to branch" not in result.output
        assert "created" not in result.output

    def test_the_second_attach_does_not_check_out_or_reset_the_branch(
        self, runner, clone
    ):
        """No git mutation at all — not even a silent re-checkout.

        `test_second_attach_changes_nothing` compares the visible end state,
        which a checkout-to-the-same-commit would survive. The reflogs grow on
        every checkout/reset/ref update, so leaving both the branch's and the
        mounted worktree's HEAD reflog untouched is the assertion that no git
        write happened in the first place.
        """
        assert attach(runner, clone).exit_code == 0
        proj = clone / ".project"
        reflog_before = reflog(clone, "projectman")
        head_reflog_before = reflog(proj, "HEAD")
        # The mount wrote both, so finding them unchanged means something.
        assert reflog_before and head_reflog_before
        proj_head_before = out("rev-parse", "HEAD", cwd=proj)
        proj_status_before = out("status", "--porcelain", cwd=proj)
        main_head_before = out("rev-parse", "HEAD", cwd=clone)
        main_status_before = out("status", "--porcelain", cwd=clone)

        assert attach(runner, clone).exit_code == 0

        assert reflog(clone, "projectman") == reflog_before
        assert reflog(proj, "HEAD") == head_reflog_before
        assert out("rev-parse", "HEAD", cwd=proj) == proj_head_before
        assert out("status", "--porcelain", cwd=proj) == proj_status_before
        assert out("rev-parse", "HEAD", cwd=clone) == main_head_before
        assert out("status", "--porcelain", cwd=clone) == main_status_before

    def test_a_hand_mounted_worktree_is_a_no_op_too(self, runner, clone):
        """The mount attach finds need not be one attach made.

        A developer who already knows the incantation runs `git worktree add`
        himself; attach must recognise that state as attached rather than
        insisting it did the work.
        """
        git("branch", "projectman", "origin/projectman", cwd=clone)
        git("worktree", "add", ".project", "projectman", cwd=clone)
        before = sha256_map(clone / ".project")
        worktrees_before = out("worktree", "list", "--porcelain", cwd=clone)

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert sha256_map(clone / ".project") == before
        assert out("worktree", "list", "--porcelain", cwd=clone) == worktrees_before

    def test_attach_in_the_migrated_repo_itself_is_a_no_op(self, runner, migrated):
        """Attach in the source repo, where migrate-worktree did the mounting.

        The migration leaves exactly the shape attach would have produced, so
        running attach there — a plausible thing to do after following the
        migration docs — must be the no-op, not a second migration.
        """
        source, _ = migrated
        proj = source / ".project"
        assert worktree_branch_for(source, proj) == "refs/heads/projectman"
        before = sha256_map(proj)
        worktrees_before = out("worktree", "list", "--porcelain", cwd=source)
        head_before = out("rev-parse", "projectman", cwd=source)

        result = attach(runner, source)
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert sha256_map(proj) == before
        assert out("worktree", "list", "--porcelain", cwd=source) == worktrees_before
        assert out("rev-parse", "projectman", cwd=source) == head_before

    def test_a_no_op_leaves_uncommitted_pm_edits_alone(self, runner, clone):
        """In-progress PM work survives a redundant attach.

        This is the case where clobbering would actually cost someone
        something: modified, staged and untracked files inside the mounted
        worktree must all be exactly as they were.
        """
        assert attach(runner, clone).exit_code == 0
        proj = clone / ".project"
        (proj / "config.yaml").write_text("name: demo\nprefix: DEMO\nedited: yes\n")
        (proj / "scratch.md").write_text("# work in progress\n")
        (proj / "stories" / "US-DEMO-1.md").write_text("# US-DEMO-1\n\nEdited.\n")
        git("add", "stories/US-DEMO-1.md", cwd=proj)
        before = sha256_map(proj)
        status_before = out("status", "--porcelain", cwd=proj)
        assert status_before  # the worktree really is dirty

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert sha256_map(proj) == before
        assert out("status", "--porcelain", cwd=proj) == status_before
        assert (proj / "scratch.md").read_text() == "# work in progress\n"

    def test_a_custom_branch_already_mounted_is_a_no_op(self, runner, repo, tmp_path):
        origin = add_origin(repo, tmp_path)
        publish(runner, repo, origin, "--branch", "pm-state")
        dest = clone_of(origin, tmp_path / "clone-custom")
        assert attach(runner, dest, "--branch", "pm-state").exit_code == 0
        before = sha256_map(dest / ".project")
        worktrees_before = out("worktree", "list", "--porcelain", cwd=dest)

        result = attach(runner, dest, "--branch", "pm-state")
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert "pm-state" in result.output
        assert sha256_map(dest / ".project") == before
        assert out("worktree", "list", "--porcelain", cwd=dest) == worktrees_before

    def test_the_no_op_needs_no_network(self, runner, clone):
        """Offline, on a plane, with origin pointing at nothing.

        The no-op is decided from the worktree list and local refs; if any
        branch of it reached for the remote, an unreachable origin would turn
        a "nothing to do" into a failure.
        """
        assert attach(runner, clone).exit_code == 0
        git("remote", "set-url", "origin", "/nonexistent/origin.git", cwd=clone)

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert "already attached" in result.output.lower()
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"

    def test_a_worktree_of_a_different_branch_is_refused(self, runner, clone):
        git("branch", "other", "main", cwd=clone)
        git("worktree", "add", ".project", "other", cwd=clone)

        result = attach(runner, clone)
        assert result.exit_code == 1, result.output
        assert "other" in result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/other"

    def test_a_detached_head_worktree_is_refused_as_detached(self, runner, clone):
        """No branch is mounted, so there is nothing to call "already attached"."""
        git("worktree", "add", "--detach", ".project", "main", cwd=clone)
        before = sha256_map(clone / ".project")

        result = attach(runner, clone)
        assert result.exit_code == 1, result.output
        assert "detached" in result.output.lower()
        assert worktree_branch_for(clone, clone / ".project") is None
        assert sha256_map(clone / ".project") == before


class TestPlainDirectoryIsNeverClobbered:
    """US-PM-20 criterion: "Attach fails with an actionable message when
    .project holds untracked content instead of clobbering it"."""

    @pytest.fixture
    def store(self, clone):
        """An unmigrated-looking plain .project/ directory in the clone."""
        proj = clone / ".project"
        (proj / "tasks").mkdir(parents=True)
        (proj / "config.yaml").write_text("name: local\nprefix: LOC\n")
        (proj / "tasks" / "US-LOC-1-1.md").write_text("# US-LOC-1-1\n")
        return proj

    def test_it_refuses_with_an_actionable_message(self, runner, clone, store):
        result = attach(runner, clone)
        assert result.exit_code == 1, result.output
        assert "migrate-worktree" in result.output
        assert "untracked content" in result.output

    def test_the_directory_is_left_byte_for_byte_as_it_was(self, runner, clone, store):
        before = sha256_map(store)

        assert attach(runner, clone).exit_code == 1

        assert sha256_map(store) == before
        assert not (store / ".git").exists()
        assert worktree_branch_for(clone, store) is None
        # No half-done state: the branch was not created either.
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_the_message_names_the_path_and_both_remedies(self, runner, clone, store):
        """Actionable means the reader can act without reading the source.

        The refusal has to say *what* is in the way (.project/, holding
        untracked content) and offer both ways out: the migration, for the
        common case of an unmigrated store, and moving the directory aside for
        everything else.
        """
        result = attach(runner, clone)

        assert result.exit_code == 1, result.output
        assert result.stderr.startswith("Error: .project/ already exists")
        assert "untracked content" in result.stderr
        assert "refusing to overwrite" in result.stderr
        assert "projectman migrate-worktree" in result.stderr
        assert "move or remove .project/" in result.stderr
        assert "re-run `projectman attach`" in result.stderr
        # Nothing on stdout claims anything was attached.
        assert result.stdout.strip() == ""

    def test_nested_dirs_dotfiles_and_empty_subdirs_all_survive(
        self, runner, clone, store
    ):
        """The whole shape is preserved, not just the files sha256_map sees."""
        (store / "stories").mkdir()  # empty subdirectory
        (store / ".secrets").write_text("token: hunter2\n")
        (store / "archive" / "2025").mkdir(parents=True)
        (store / "archive" / "2025" / "US-LOC-9.md").write_text("# old\n")
        before_digests = sha256_map(store)
        before_tree = tree(store)

        assert attach(runner, clone).exit_code == 1

        assert sha256_map(store) == before_digests
        assert tree(store) == before_tree
        assert "dir stories" in before_tree  # the empty dir was really there

    def test_a_directory_holding_only_a_hidden_file_is_not_treated_as_empty(
        self, runner, clone
    ):
        """`.project/.keep` is content: a dotfile must not read as an empty dir."""
        proj = clone / ".project"
        proj.mkdir()
        (proj / ".keep").write_bytes(b"")

        result = attach(runner, clone)
        assert result.exit_code == 1, result.output
        assert "untracked content" in result.stderr
        assert (proj / ".keep").exists()
        assert not (proj / ".git").exists()
        assert worktree_branch_for(clone, proj) is None
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_no_worktree_is_registered_and_the_main_checkout_is_untouched(
        self, runner, clone, store
    ):
        """The refusal happens before any git write, not after a partial one."""
        worktrees_before = worktree_list(clone)
        head_before = out("rev-parse", "HEAD", cwd=clone)
        main_reflog_before = reflog(clone, "main")

        assert attach(runner, clone).exit_code == 1

        assert worktree_list(clone) == worktrees_before
        assert out("rev-parse", "HEAD", cwd=clone) == head_before
        assert reflog(clone, "main") == main_reflog_before
        # origin/projectman existed, so a branch would have been created had
        # the refusal come any later.
        assert out("branch", "--list", "projectman", cwd=clone) == ""
        assert reflog(clone, "projectman") == []

    def test_the_refusal_is_idempotent(self, runner, clone, store):
        """Re-running after ignoring the error gives the same answer, not a
        worn-down one that eventually deletes the directory."""
        before = sha256_map(store)

        first = attach(runner, clone)
        second = attach(runner, clone)

        assert first.exit_code == second.exit_code == 1
        assert first.stderr == second.stderr
        assert sha256_map(store) == before
        assert worktree_branch_for(clone, store) is None

    def test_a_symlinked_directory_with_content_is_refused_and_kept(
        self, runner, clone, tmp_path
    ):
        """A symlink is followed for the content check — and never removed.

        `Path.is_dir()` follows the link, so the target's content is what
        decides, and the refusal fires before anything is unlinked. Deleting
        the symlink (or its target) would be the destructive bug this
        criterion exists to prevent.
        """
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "notes.md").write_text("# not ours\n")
        (clone / ".project").symlink_to(elsewhere, target_is_directory=True)

        result = attach(runner, clone)

        assert result.exit_code == 1, result.output
        assert "untracked content" in result.stderr
        assert (clone / ".project").is_symlink()
        assert Path(os.readlink(clone / ".project")) == elsewhere
        assert (elsewhere / "notes.md").read_text() == "# not ours\n"
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_a_file_at_the_project_path_is_refused(self, runner, clone):
        (clone / ".project").write_text("not a directory\n")

        result = attach(runner, clone)
        assert result.exit_code == 1, result.output
        assert (clone / ".project").read_text() == "not a directory\n"

    def test_the_file_refusal_says_what_is_wrong_and_what_to_do(self, runner, clone):
        (clone / ".project").write_text("not a directory\n")

        result = attach(runner, clone)

        assert result.exit_code == 1, result.output
        assert "is not a directory" in result.stderr
        assert "move it aside" in result.stderr
        assert "re-run `projectman attach`" in result.stderr
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_an_empty_directory_is_put_back_when_the_worktree_add_fails(
        self, clone, monkeypatch
    ):
        """The other half of the promise: the empty dir attach *is* allowed to
        remove goes back if git then refuses, so a failed attach still leaves
        the tree as it was found."""
        import projectman.worktree as wt

        real_git = wt._git

        def exploding_git(*args, cwd, check=True):
            if args[:2] == ("worktree", "add"):
                raise wt.MigrationError("boom")
            return real_git(*args, cwd=cwd, check=check)

        monkeypatch.setattr(wt, "_git", exploding_git)
        (clone / ".project").mkdir()

        with pytest.raises(MigrationError, match="boom"):
            attach_worktree(clone)

        assert (clone / ".project").is_dir()
        assert list((clone / ".project").iterdir()) == []
        assert worktree_branch_for(clone, clone / ".project") is None


class TestExistingLocalBranch:
    def test_an_unmounted_local_branch_is_mounted(self, runner, clone):
        git("branch", "projectman", "origin/projectman", cwd=clone)
        sha = out("rev-parse", "projectman", cwd=clone)

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        assert out("rev-parse", "projectman", cwd=clone) == sha
        assert (clone / ".project" / "config.yaml").exists()

    def test_the_existing_branch_is_not_recreated_from_the_remote(self, runner, clone):
        """A local `projectman` that points somewhere else is mounted as-is.

        Pointing it at `main` makes the difference observable: if attach
        recreated the branch from origin/projectman the worktree would hold the
        PM files, and if it mounts what is there it holds README.md instead.
        """
        git("branch", "projectman", "main", cwd=clone)
        main_sha = out("rev-parse", "main", cwd=clone)

        result = attach(runner, clone)
        assert result.exit_code == 0, result.output
        assert out("rev-parse", "projectman", cwd=clone) == main_sha
        assert out("rev-parse", "HEAD", cwd=clone / ".project") == main_sha
        assert (clone / ".project" / "README.md").exists()
        assert "existing local branch" in result.output


class TestNothingToAttach:
    def test_no_branch_and_no_remote_points_at_the_migration(self, runner, tmp_path):
        root = init_repo(tmp_path / "solo")
        (root / "README.md").write_text("# solo\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)

        result = attach(runner, root)
        assert result.exit_code == 1, result.output
        assert "migrate-worktree" in result.output
        assert not (root / ".project").exists()

    def test_a_remote_without_the_branch_points_at_git_fetch(self, runner, tmp_path):
        root = init_repo(tmp_path / "remoted")
        (root / "README.md").write_text("# remoted\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        add_origin(root, tmp_path, name="remoted-origin.git")

        result = attach(runner, root)
        assert result.exit_code == 1, result.output
        assert "git fetch origin" in result.output
        assert not (root / ".project").exists()

    def test_an_unmigrated_store_is_refused_before_the_branch_lookup(
        self, runner, repo, tmp_path
    ):
        """A tracked .project/ is content: the clobber refusal wins."""
        add_origin(repo, tmp_path)
        proj_before = sha256_map(repo / ".project")

        result = attach(runner, repo)
        assert result.exit_code == 1, result.output
        assert "migrate-worktree" in result.output
        assert sha256_map(repo / ".project") == proj_before

    def test_an_empty_project_dir_with_no_branch_anywhere_is_refused(
        self, runner, tmp_path
    ):
        root = init_repo(tmp_path / "empty")
        (root / "README.md").write_text("# empty\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "initial", cwd=root)
        (root / ".project").mkdir()

        result = attach(runner, root)
        assert result.exit_code == 1, result.output
        assert "nothing to attach" in result.output
        # The empty directory it found is still there.
        assert (root / ".project").is_dir()
        assert list((root / ".project").iterdir()) == []

    def test_outside_a_git_repo_is_refused(self, runner, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()

        result = attach(runner, plain)
        assert result.exit_code == 1, result.output
        assert "not inside a git repository" in result.output


class TestBranchOption:
    def test_a_custom_branch_name_is_attached(self, runner, repo, tmp_path):
        origin = add_origin(repo, tmp_path)
        publish(runner, repo, origin, "--branch", "pm-state")
        dest = clone_of(origin, tmp_path / "clone2")

        result = attach(runner, dest, "--branch", "pm-state")
        assert result.exit_code == 0, result.output
        assert worktree_branch_for(dest, dest / ".project") == "refs/heads/pm-state"
        assert upstream(dest, "pm-state") == "origin/pm-state"

    def test_the_default_branch_is_not_found_when_a_custom_one_was_used(
        self, runner, repo, tmp_path
    ):
        origin = add_origin(repo, tmp_path)
        publish(runner, repo, origin, "--branch", "pm-state")
        dest = clone_of(origin, tmp_path / "clone3")

        result = attach(runner, dest)
        assert result.exit_code == 1, result.output
        assert "projectman" in result.output
        assert not (dest / ".project").exists()


class TestAttachEngine:
    """The engine is the API `projectman init` will reuse (US-PM-20-6)."""

    def test_it_returns_a_summary_dict(self, clone):
        result = attach_worktree(clone)
        assert result["attached"] is True
        assert result["already"] is False
        assert result["created_branch"] is True
        assert result["branch"] == "projectman"
        assert result["tracking"] == "origin/projectman"
        assert result["head"] == out("rev-parse", "projectman", cwd=clone)

    def test_a_second_call_reports_already(self, clone):
        attach_worktree(clone)
        result = attach_worktree(clone)
        assert result["already"] is True
        assert result["attached"] is True
        assert result["created_branch"] is False

    def test_the_no_op_result_still_reports_tracking_and_head(self, clone):
        """`init` (US-PM-20-6) reuses this result, so the no-op must be as
        informative as the real attach — same branch, upstream and commit."""
        first = attach_worktree(clone)
        second = attach_worktree(clone)

        assert second["already"] is True
        assert second["branch"] == "projectman"
        assert second["tracking"] == "origin/projectman"
        assert second["head"] == first["head"]
        assert second["head"] == out("rev-parse", "projectman", cwd=clone)
        assert Path(second["path"]) == clone / ".project"

    def test_refusals_raise_migration_error(self, clone):
        (clone / ".project").mkdir()
        (clone / ".project" / "config.yaml").write_text("name: local\n")
        with pytest.raises(MigrationError, match="untracked content"):
            attach_worktree(clone)


class TestAttachHelpText:
    def test_help_explains_idempotence_and_clobber_safety(self):
        result = CliRunner().invoke(cli, ["attach", "--help"])
        assert result.exit_code == 0, result.output
        assert "--branch" in result.output
        assert "migrate-worktree" in result.output

    def test_attach_is_listed_in_the_command_index(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output
        assert "attach" in result.output
