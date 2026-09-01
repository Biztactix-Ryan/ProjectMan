"""Tests for `projectman init` detecting the projectman branch (US-PM-20).

US-PM-20 criterion: "projectman init detects origin/projectman and attaches
instead of scaffolding a new store" (task US-PM-20-6; verified by US-PM-20-2).

A fresh clone of a migrated repo has nothing to scaffold — the PM store exists,
it is just unmounted — so `init` there must run the attach flow and create no
files of its own.  Without such a branch the scaffolding must be exactly as it
always was, so both halves are pinned here.

Every test runs against throwaway repos under tmp_path: `init` can mount a
worktree, so it must never be pointed at a real checkout.  The git helpers and
the migrated-repo/clone fixtures are imported from the migration and attach
suites rather than duplicated.
"""

import os
from pathlib import Path

import yaml

from projectman.cli import cli
from test_attach import (  # noqa: F401 — `clone`/`migrated` are fixtures
    clone,
    migrated,
    reflog,
    upstream,
    worktree_list,
)
from test_migrate_worktree import (  # noqa: F401 — `repo`/`runner` are fixtures
    PM_FILES,
    add_origin,
    git,
    init_repo,
    out,
    repo,
    runner,
    sha256_map,
    worktree_branch_for,
)


def init(runner, cwd, *args, **kwargs):
    """Invoke `projectman init` with the process cwd inside `cwd`."""
    here = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(cli, ["init", *args], **kwargs)
    finally:
        os.chdir(here)


def store_files(root: Path) -> dict[str, str]:
    """`{path: sha256}` for the PM store at `root/.project`."""
    return sha256_map(root / ".project")


SCAFFOLD_FILES = ["config.yaml", "PROJECT.md", "INFRASTRUCTURE.md", "SECURITY.md"]


def committed_repo(root: Path) -> Path:
    """A git repo with one commit — `add_origin` needs something to push."""
    init_repo(root)
    (root / "README.md").write_text("# demo\n")
    git("add", "-A", cwd=root)
    git("commit", "-m", "initial", cwd=root)
    return root


class TestInitAttachesOnAFreshClone:
    """The criterion itself: init finds origin/projectman and attaches."""

    def test_init_mounts_the_branch_instead_of_scaffolding(self, runner, clone):
        result = init(runner, clone)
        assert result.exit_code == 0, result.output

        proj = clone / ".project"
        assert worktree_branch_for(clone, proj) == "refs/heads/projectman"
        assert proj.joinpath(".git").is_file()
        assert upstream(clone) == "origin/projectman"
        # The main checkout is untouched and still on its own branch.
        assert worktree_branch_for(clone, clone) == "refs/heads/main"

    def test_it_says_it_is_attaching_rather_than_scaffolding(self, runner, clone):
        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert "origin/projectman" in result.output
        assert "attaching" in result.output.lower()
        assert "Attached" in result.output
        # The scaffolding line must not appear — nothing was initialized.
        assert "Initialized project" not in result.output

    def test_the_store_is_the_branch_content_not_a_new_scaffold(
        self, runner, clone, migrated
    ):
        source, _ = migrated
        expected = store_files(source)

        result = init(runner, clone)
        assert result.exit_code == 0, result.output

        # Byte-for-byte the store that was migrated: no extra scaffold file,
        # and no scaffold config.yaml overwriting the branch's own.
        assert store_files(clone) == expected
        assert (clone / ".project/config.yaml").read_text() == \
            PM_FILES[".project/config.yaml"]
        assert not (clone / ".project/INFRASTRUCTURE.md").exists()
        assert not (clone / ".project/SECURITY.md").exists()

    def test_the_mounted_worktree_is_clean_with_nothing_scaffolded_into_it(
        self, runner, clone
    ):
        # The sharpest reading of "instead of scaffolding": had init written
        # config.yaml/PROJECT.md/stories/ into the mount, they would show up
        # here as untracked files even though the branch content is intact.
        result = init(runner, clone)
        assert result.exit_code == 0, result.output

        proj = clone / ".project"
        assert out("status", "--porcelain", cwd=proj) == ""
        tracked = sorted(out("ls-tree", "-r", "--name-only", "HEAD", cwd=proj).split())
        assert sorted(store_files(clone)) == tracked
        # ... and none of the scaffold's own files are among them.
        assert "INFRASTRUCTURE.md" not in tracked
        assert not (proj / "epics").exists()

    def test_an_existing_local_branch_is_mounted_as_is_not_recreated(
        self, runner, clone
    ):
        # A clone where the developer already made their own `projectman`
        # branch: attaching must mount that branch, not recreate it from
        # origin/projectman and lose the commit only they have.
        remote_head = out("rev-parse", "origin/projectman", cwd=clone)
        local_head = out(
            "-c", "user.name=Test User", "-c", "user.email=test@example.com",
            "commit-tree", f"{remote_head}^{{tree}}", "-p", remote_head,
            "-m", "local-only work", cwd=clone,
        )
        git("branch", "projectman", local_head, cwd=clone)
        assert local_head != remote_head
        before = reflog(clone)

        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert "existing local branch" in result.output

        proj = clone / ".project"
        assert worktree_branch_for(clone, proj) == "refs/heads/projectman"
        assert out("rev-parse", "HEAD", cwd=proj) == local_head
        assert out("rev-parse", "projectman", cwd=clone) == local_head
        # No ref update at all: the branch was mounted, never rewritten.
        assert reflog(clone) == before

    def test_detection_and_attach_never_reach_the_network(self, runner, clone):
        # Only local ref storage is consulted, so a dead origin URL — offline,
        # or a moved remote — must not stop the attach.
        git("remote", "set-url", "origin", str(clone / "no-such-origin.git"), cwd=clone)

        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert "origin/projectman" in result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        assert (clone / ".project/PROJECT.md").read_text() == \
            PM_FILES[".project/PROJECT.md"]

    def test_no_name_is_prompted_for_in_the_attach_case(self, runner, clone):
        # An empty stdin would abort the run if click still prompted; the
        # prompt would also be asking for a name nothing consumes.
        result = init(runner, clone, input="")
        assert result.exit_code == 0, result.output
        assert "Project name" not in result.output

    def test_gitignore_is_left_alone(self, runner, clone):
        before = (clone / ".gitignore").read_text()

        result = init(runner, clone)
        assert result.exit_code == 0, result.output

        assert (clone / ".gitignore").read_text() == before
        assert out("status", "--porcelain", cwd=clone) == ""

    def test_a_local_branch_without_a_remote_attaches_too(self, runner, clone):
        # Someone who fetched and branched, then dropped the remote: only
        # `projectman` exists locally, so there is still nothing to scaffold.
        git("branch", "projectman", "origin/projectman", cwd=clone)
        git("remote", "remove", "origin", cwd=clone)
        assert git("rev-parse", "--verify", "--quiet",
                   "refs/remotes/origin/projectman", cwd=clone,
                   check=False).returncode != 0

        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert "projectman" in result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        assert (clone / ".project/PROJECT.md").read_text() == \
            PM_FILES[".project/PROJECT.md"]


class TestInitStillScaffolds:
    """Scaffolding is unchanged wherever there is no projectman branch."""

    def test_a_git_repo_without_the_branch_scaffolds_and_prompts_for_a_name(
        self, runner, tmp_path
    ):
        plain = init_repo(tmp_path / "plain")

        result = init(runner, plain, input="myproj\n")
        assert result.exit_code == 0, result.output
        assert "Project name" in result.output
        assert "Initialized project 'myproj'" in result.output

        proj = plain / ".project"
        for name in SCAFFOLD_FILES:
            assert (proj / name).is_file()
        assert (proj / "stories").is_dir()
        assert (proj / "tasks").is_dir()
        assert (proj / "epics").is_dir()
        assert yaml.safe_load((proj / "config.yaml").read_text())["name"] == "myproj"
        # A scaffold is a plain directory, never a worktree.
        assert not (proj / ".git").exists()

    def test_a_repo_with_an_origin_but_no_projectman_branch_scaffolds(
        self, runner, tmp_path
    ):
        # It is the branch that triggers attaching, not merely having a remote.
        plain = committed_repo(tmp_path / "with-origin")
        add_origin(plain, tmp_path, name="plain-origin.git")

        result = init(runner, plain, input="hasorigin\n")
        assert result.exit_code == 0, result.output
        assert "Project name" in result.output
        assert "Initialized project 'hasorigin'" in result.output
        assert "attaching" not in result.output.lower()
        assert not (plain / ".project/.git").exists()

    def test_only_origin_is_consulted_for_the_remote_branch(
        self, runner, migrated, tmp_path
    ):
        # A `projectman` branch on some *other* remote is deliberately not
        # attached: attach mounts origin/projectman, so init must agree.
        _, origin = migrated
        plain = committed_repo(tmp_path / "upstream-only")
        git("remote", "add", "upstream", str(origin), cwd=plain)
        git("fetch", "upstream", cwd=plain)
        assert out("rev-parse", "--verify", "refs/remotes/upstream/projectman",
                   cwd=plain)

        result = init(runner, plain, input="mine\n")
        assert result.exit_code == 0, result.output
        assert "Initialized project 'mine'" in result.output
        assert not (plain / ".project/.git").exists()
        assert yaml.safe_load(
            (plain / ".project/config.yaml").read_text()
        )["name"] == "mine"

    def test_outside_a_git_repo_scaffolding_is_unchanged(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--name", "loose", "--prefix", "LS"])
            assert result.exit_code == 0, result.output
            assert "Initialized project 'loose'" in result.output
            config = yaml.safe_load(Path(".project/config.yaml").read_text())
            assert config["name"] == "loose"
            assert config["prefix"] == "LS"

    def test_no_attach_scaffolds_a_fresh_store_on_a_clone(self, runner, clone):
        result = init(runner, clone, "--no-attach", "--name", "fresh")
        assert result.exit_code == 0, result.output
        assert "Initialized project 'fresh'" in result.output
        assert "attaching" not in result.output.lower()

        proj = clone / ".project"
        assert not (proj / ".git").exists()
        assert worktree_branch_for(clone, proj) is None
        assert yaml.safe_load((proj / "config.yaml").read_text())["name"] == "fresh"
        # No local branch was created — nothing was mounted.
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_the_no_attach_scaffold_lands_in_the_ignored_project_dir(
        self, runner, clone
    ):
        # main carries the migration's .gitignore entry, so the fresh store is
        # invisible to git — `--no-attach` cannot dirty the checkout.
        result = init(runner, clone, "--no-attach", "--name", "fresh")
        assert result.exit_code == 0, result.output

        assert out("status", "--porcelain", cwd=clone) == ""
        assert git("check-ignore", "-q", ".project", cwd=clone,
                   check=False).returncode == 0
        assert out("rev-parse", "origin/projectman", cwd=clone)  # branch untouched

    def test_no_attach_still_refuses_an_existing_project_dir(self, runner, clone):
        first = init(runner, clone, "--no-attach", "--name", "fresh")
        assert first.exit_code == 0, first.output

        second = init(runner, clone, "--no-attach", "--name", "again")
        assert second.exit_code != 0
        assert ".project/ already exists" in second.stderr
        assert yaml.safe_load(
            (clone / ".project/config.yaml").read_text()
        )["name"] == "fresh"


class TestInitAttachEdgeCases:
    def test_an_already_attached_clone_is_a_friendly_no_op(self, runner, clone):
        first = init(runner, clone)
        assert first.exit_code == 0, first.output
        before = store_files(clone)
        registry = worktree_list(clone)
        log = reflog(clone)

        second = init(runner, clone)
        assert second.exit_code == 0, second.output
        assert "already attached" in second.output.lower()
        assert "nothing to do" in second.output
        assert store_files(clone) == before
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        # Nothing was mounted or written a second time.
        assert worktree_list(clone) == registry
        assert reflog(clone) == log
        assert out("status", "--porcelain", cwd=clone / ".project") == ""

    def test_a_plain_project_dir_with_content_is_refused_untouched(
        self, runner, clone
    ):
        proj = clone / ".project"
        proj.mkdir()
        (proj / "notes.md").write_text("mine\n")
        before = store_files(clone)
        registry = worktree_list(clone)

        result = init(runner, clone)
        assert result.exit_code == 1
        assert ".project/ already exists" in result.stderr
        assert store_files(clone) == before
        assert (proj / "notes.md").read_text() == "mine\n"
        assert not (proj / "config.yaml").exists()
        assert worktree_list(clone) == registry
        assert out("branch", "--list", "projectman", cwd=clone) == ""

    def test_an_empty_project_dir_is_mounted_over(self, runner, clone):
        (clone / ".project").mkdir()

        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"

    def test_scaffold_options_are_ignored_with_a_warning_but_it_still_attaches(
        self, runner, clone, migrated
    ):
        source, _ = migrated
        expected = store_files(source)

        result = init(runner, clone, "--hub", "--name", "ignored", "--prefix", "ZZ")
        assert result.exit_code == 0, result.output
        assert "--hub ignored: attaching existing store" in result.stderr
        assert "--name ignored: attaching existing store" in result.stderr
        assert "--prefix ignored: attaching existing store" in result.stderr

        assert worktree_branch_for(clone, clone / ".project") == "refs/heads/projectman"
        assert store_files(clone) == expected
        # None of the hub scaffolding happened.
        assert not (clone / ".project/projects").exists()
        assert not (clone / ".project/VISION.md").exists()

    def test_hub_alone_attaches_and_builds_no_hub_scaffold(self, runner, clone):
        # `--hub` on its own leaves `name` unset: the attach path must still be
        # taken (no prompt, no hub directories), not the scaffold's.
        result = init(runner, clone, "--hub", input="")
        assert result.exit_code == 0, result.output
        assert "--hub ignored: attaching existing store" in result.stderr
        assert "Project name" not in result.output

        proj = clone / ".project"
        assert worktree_branch_for(clone, proj) == "refs/heads/projectman"
        for name in ("projects", "roadmap", "dashboards"):
            assert not (proj / name).exists()
        assert out("status", "--porcelain", cwd=proj) == ""

    def test_default_options_attach_without_any_ignored_warning(self, runner, clone):
        result = init(runner, clone)
        assert result.exit_code == 0, result.output
        assert "ignored" not in result.stderr
