"""`projectman add-project` mounts the subproject's own `projectman` branch.

US-PM-31 criterion (task US-PM-31-7, verified by US-PM-31-2): "projectman
add-project attaches the submodule's origin/projectman branch as
projects/{name}/.project when it exists and otherwise creates the orphan
branch and scaffolds a fresh store there".

The point of the story is that a subproject's PM data belongs to the
subproject repo, not to the hub: `projects/{name}/.project` is a *git
worktree* of that submodule's `projectman` branch, and the hub's own
`.project/projects/` is never written to again.  Two halves follow from that
and both are pinned here:

* the clone already carries the store — `origin/projectman` came down with
  `git submodule add`, so it is attached and its contents are left alone;
* the clone carries nothing — the orphan branch is created, mounted,
  scaffolded and committed.

Every test builds real git repositories under `tmp_path`: a bare "origin"
per subproject, a real `git submodule add` into a real hub.  Nothing here may
be pointed at a checkout anyone cares about.

Two environment details make that hermetic:

* `protocol.file.allow=always` — git refuses to clone a submodule over the
  `file` transport by default (CVE-2022-39253).  It is supplied through
  `GIT_CONFIG_*` env vars rather than repo config because the refusal happens
  in the `git clone` child process, which does not inherit the superproject's
  config;
* `GIT_AUTHOR_*`/`GIT_COMMITTER_*` — the store commit is made inside a
  freshly cloned submodule that has no local identity configured.
"""

from pathlib import Path

import pytest
import yaml

from projectman import worktree
from projectman.config import load_config
from projectman.hub.registry import add_project, sync
from projectman.hub.stores import (
    hub_stores,
    invalidate as invalidate_store_map,
    store_path,
    subproject_path,
)
from projectman.indexer import DERIVED_INDEX_FILES
from test_migrate_worktree import git, init_repo, out, worktree_branch_for


# ─── Environment ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _git_env(monkeypatch):
    """Let git clone submodules from local paths, and give it an identity."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    for var, value in (
        ("GIT_AUTHOR_NAME", "Test User"),
        ("GIT_AUTHOR_EMAIL", "test@example.com"),
        ("GIT_COMMITTER_NAME", "Test User"),
        ("GIT_COMMITTER_EMAIL", "test@example.com"),
    ):
        monkeypatch.setenv(var, value)


# ─── Fixtures: a subproject's remote, with and without a store on it ────────


REMOTE_CONFIG = "name: widget\nprefix: RMT\nhub: false\nnext_story_id: 4\n"
REMOTE_STORY = "# US-RMT-3\n\nA story that already existed on the remote.\n"


@pytest.fixture
def sub_origin(_git_env, tmp_path):
    """A bare repo with a `main` branch — the subproject's remote.

    Returns `(bare, work)`: the bare repo `add-project` clones from, and the
    ordinary checkout the fixtures below push new branches from.
    """
    bare = tmp_path / "widget-origin.git"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    work = init_repo(tmp_path / "widget-work")
    (work / "README.md").write_text("# widget\n")
    (work / "widget.py").write_text("print('hi')\n")
    git("add", "-A", cwd=work)
    git("commit", "-m", "initial", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "origin", "main", cwd=work)
    return bare, work


@pytest.fixture
def sub_origin_with_store(sub_origin):
    """The same remote, plus a `projectman` branch carrying a real store.

    This is what a subproject that has already been migrated (US-PM-19) looks
    like from the outside: an orphan branch whose root *is* the PM store.
    """
    bare, work = sub_origin
    git("checkout", "--orphan", "projectman", cwd=work)
    git("rm", "-rf", ".", cwd=work, check=False)
    (work / "config.yaml").write_text(REMOTE_CONFIG)
    (work / "stories").mkdir(exist_ok=True)
    (work / "stories" / "US-RMT-3.md").write_text(REMOTE_STORY)
    git("add", "-A", cwd=work)
    git("commit", "-m", "PM store", cwd=work)
    git("push", "origin", "projectman", cwd=work)
    git("checkout", "main", cwd=work)
    return bare, work


@pytest.fixture
def hub(_git_env, tmp_git_hub):
    """A hub that is a real git repo — `git submodule add` needs one."""
    return tmp_git_hub


# ─── Helpers ────────────────────────────────────────────────────────────────


def store_of(hub: Path, name: str = "widget") -> Path:
    return store_path(hub, name)


def sub_of(hub: Path, name: str = "widget") -> Path:
    return subproject_path(hub, name)


def entry_for(hub: Path, name: str = "widget") -> dict:
    for entry in hub_stores(hub):
        if entry["name"] == name:
            return entry
    raise AssertionError(f"{name} not in hub_stores: {hub_stores(hub)}")


def tracked_on(repo: Path, branch: str) -> set[str]:
    """The paths `branch` tracks, as a set."""
    listing = out("ls-tree", "-r", "--name-only", branch, cwd=repo)
    return set(listing.splitlines()) if listing else set()


# ─── Half one: the branch already exists on origin → attach ─────────────────


class TestAttachesTheRemoteBranch:
    """`origin/projectman` came down with the clone, so it is mounted as-is."""

    def test_the_store_is_a_worktree_of_the_projectman_branch(
        self, hub, sub_origin_with_store
    ):
        bare, _ = sub_origin_with_store
        result = add_project("widget", str(bare), root=hub)
        assert not result.startswith("error"), result

        store, sub = store_of(hub), sub_of(hub)
        assert worktree.is_worktree(store), f"{store} is not a worktree"
        assert worktree_branch_for(sub, store) == "refs/heads/projectman"

    def test_the_mounted_store_is_the_remotes_own(self, hub, sub_origin_with_store):
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)

        store = store_of(hub)
        assert store.joinpath("config.yaml").read_text() == REMOTE_CONFIG
        assert store.joinpath("stories/US-RMT-3.md").read_text() == REMOTE_STORY
        # Nothing was scaffolded over the top of it.
        assert not store.joinpath("PROJECT.md").exists()
        assert yaml.safe_load(store.joinpath("config.yaml").read_text())["prefix"] == "RMT"

    def test_the_local_branch_tracks_the_remote_one(self, hub, sub_origin_with_store):
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)

        sub = sub_of(hub)
        assert worktree.branch_exists(sub, "projectman")
        assert worktree.upstream_of(sub, "projectman") == "origin/projectman"

    def test_hub_stores_lists_it_attached_with_the_remotes_prefix(
        self, hub, sub_origin_with_store
    ):
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)

        entry = entry_for(hub)
        assert entry["attached"] is True
        assert entry["prefix"] == "RMT"
        assert entry["path"] == store_of(hub)

    def test_it_says_it_attached_rather_than_scaffolded(
        self, hub, sub_origin_with_store
    ):
        bare, _ = sub_origin_with_store
        result = add_project("widget", str(bare), root=hub)
        assert "ttached" in result
        assert "scaffolded" not in result

    def test_no_commit_is_made_on_the_attached_branch(
        self, hub, sub_origin_with_store
    ):
        """Attaching mounts what is there; it must not add a commit of its own."""
        bare, work = sub_origin_with_store
        before = out("rev-parse", "projectman", cwd=work)
        add_project("widget", str(bare), root=hub)
        assert out("rev-parse", "projectman", cwd=sub_of(hub)) == before


# ─── Half two: no such branch → create, mount, scaffold, commit ─────────────


class TestCreatesTheOrphanBranch:
    """Nothing came down with the clone, so the store is conjured."""

    def test_the_store_is_a_worktree_of_a_new_projectman_branch(
        self, hub, sub_origin
    ):
        bare, _ = sub_origin
        result = add_project("widget", str(bare), root=hub)
        assert not result.startswith("error"), result

        store, sub = store_of(hub), sub_of(hub)
        assert worktree.is_worktree(store), f"{store} is not a worktree"
        assert worktree_branch_for(sub, store) == "refs/heads/projectman"

    def test_a_fresh_store_is_scaffolded_with_the_derived_name_and_prefix(
        self, hub, sub_origin
    ):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        config = yaml.safe_load(store_of(hub).joinpath("config.yaml").read_text())
        assert config["name"] == "widget"
        assert config["prefix"] == "WID"
        assert config["hub"] is False

    def test_the_scaffolded_store_has_its_docs_and_directories(self, hub, sub_origin):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        store = store_of(hub)
        for doc in ("PROJECT.md", "INFRASTRUCTURE.md", "SECURITY.md"):
            assert store.joinpath(doc).is_file(), doc
        for sub_dir in ("stories", "tasks", "epics"):
            assert store.joinpath(sub_dir).is_dir(), sub_dir

    def test_the_derived_index_gitignore_is_written(self, hub, sub_origin):
        """US-PM-29-6: the five rendered index files are not tracked."""
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        ignored = store_of(hub).joinpath(".gitignore").read_text()
        for name in DERIVED_INDEX_FILES:
            assert name in ignored, name

    def test_the_scaffold_is_committed_on_the_branch(self, hub, sub_origin):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        store, sub = store_of(hub), sub_of(hub)
        # A clean worktree: everything the scaffold wrote is either committed
        # or deliberately ignored.
        assert out("status", "--porcelain", cwd=store) == ""
        tracked = tracked_on(sub, "projectman")
        assert {"config.yaml", "PROJECT.md", ".gitignore"} <= tracked
        # The derived indexes are ignored, not committed.
        assert tracked.isdisjoint(set(DERIVED_INDEX_FILES))

    def test_the_branch_is_an_orphan_unrelated_to_main(self, hub, sub_origin):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        sub = sub_of(hub)
        # Root commit + scaffold commit, and no shared history with main.
        assert out("rev-list", "--count", "projectman", cwd=sub) == "2"
        assert git(
            "merge-base", "main", "projectman", cwd=sub, check=False
        ).returncode != 0
        # The submodule's own checkout is untouched: still on main.  (Asked
        # via rev-parse, not `worktree list`: inside a submodule git reports
        # the main worktree by its gitdir under the hub's .git/modules/, so
        # the checkout path never matches there.)
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=sub) == "main"
        assert sub.joinpath("widget.py").is_file()

    def test_hub_stores_lists_it_attached_with_the_derived_prefix(
        self, hub, sub_origin
    ):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        entry = entry_for(hub)
        assert entry["attached"] is True
        assert entry["prefix"] == "WID"

    def test_it_says_it_created_and_scaffolded(self, hub, sub_origin):
        bare, _ = sub_origin
        result = add_project("widget", str(bare), root=hub)
        assert "scaffolded" in result
        assert "projectman" in result


# ─── Invariants that hold either way ───────────────────────────────────────


@pytest.mark.parametrize("with_store", [False, True])
def test_nothing_is_written_under_the_hubs_own_project_projects(
    hub, sub_origin, sub_origin_with_store, with_store, request
):
    """The old layout is dead: the hub store gains no `projects/` subtree."""
    bare, _ = request.getfixturevalue(
        "sub_origin_with_store" if with_store else "sub_origin"
    )
    add_project("widget", str(bare), root=hub)

    assert not (hub / ".project" / "projects").exists()
    # And the hub store is exactly the files it started with, plus nothing.
    hub_files = {p.name for p in (hub / ".project").iterdir()}
    assert "projects" not in hub_files


@pytest.mark.parametrize("with_store", [False, True])
def test_dot_project_is_gitignored_on_the_submodules_main_branch(
    hub, sub_origin, sub_origin_with_store, with_store, request
):
    """A mounted worktree would otherwise be untracked noise in the checkout."""
    bare, _ = request.getfixturevalue(
        "sub_origin_with_store" if with_store else "sub_origin"
    )
    add_project("widget", str(bare), root=hub)

    sub = sub_of(hub)
    lines = [line.strip().strip("/") for line in (sub / ".gitignore").read_text().splitlines()]
    assert ".project" in lines
    # git agrees: the store does not show up as untracked in the checkout.
    status = out("status", "--porcelain", cwd=sub)
    assert ".project" not in status, status


@pytest.mark.parametrize("with_store", [False, True])
def test_the_project_is_registered_in_the_hub_config(
    hub, sub_origin, sub_origin_with_store, with_store, request
):
    bare, _ = request.getfixturevalue(
        "sub_origin_with_store" if with_store else "sub_origin"
    )
    add_project("widget", str(bare), root=hub)
    assert load_config(hub).projects == ["widget"]


# ─── A local-only projectman branch ────────────────────────────────────────


class TestLocalBranchWithoutOrigin:
    """The branch exists locally but was never pushed — attach it, don't recreate.

    This one cannot be staged through `add-project`: `git submodule add`
    always clones, and a clone that has `projectman` locally necessarily has
    `origin/projectman` too.  So it is pinned on
    `worktree.ensure_store_branch`, the single helper `add_project` delegates
    the whole decision to — the case reaches production through a repo whose
    branch was created locally by `migrate-worktree --no-push`.
    """

    @pytest.fixture
    def repo_with_local_branch(self, _git_env, tmp_path):
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


class TestMountFailureIsNotRegistered:
    """When the git plumbing fails midway, no half-project is left registered.

    The choice made in `add_project`: a project whose store never mounted is
    *not* written to `config.projects`, because every reader that walks that
    list would then have to cope with a name that has no store.  The failure
    is reported instead, with the command to undo the submodule.
    """

    @pytest.fixture
    def exploding_mount(self, monkeypatch):
        def boom(*args, **kwargs):
            raise worktree.MigrationError("git worktree add failed: disk on fire")

        monkeypatch.setattr(worktree, "ensure_store_branch", boom)

    def test_it_reports_the_failure_and_names_git_error(
        self, hub, sub_origin, exploding_mount
    ):
        bare, _ = sub_origin
        result = add_project("widget", str(bare), root=hub)
        assert result.startswith("error")
        assert "disk on fire" in result
        assert "NOT registered" in result

    def test_the_project_is_not_registered(self, hub, sub_origin, exploding_mount):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)

        assert load_config(hub).projects == []
        assert hub_stores(hub) == []

    def test_no_store_is_left_behind(self, hub, sub_origin, exploding_mount):
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)
        assert not store_of(hub).joinpath("config.yaml").exists()


class TestCreateStoreBranchRollsBack:
    """`create_store_branch` puts the repo back when the scaffold blows up."""

    @pytest.fixture
    def plain_repo(self, _git_env, tmp_path):
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


# ─── Re-running add-project ────────────────────────────────────────────────


def test_add_project_twice_is_refused_without_touching_the_store(
    hub, sub_origin_with_store
):
    bare, _ = sub_origin_with_store
    add_project("widget", str(bare), root=hub)
    head = out("rev-parse", "HEAD", cwd=store_of(hub))

    result = add_project("widget", str(bare), root=hub)

    assert result.startswith("error")
    assert "already exists" in result
    assert out("rev-parse", "HEAD", cwd=store_of(hub)) == head
    assert load_config(hub).projects == ["widget"]


def test_submodule_add_failure_registers_nothing(hub, tmp_path):
    """A git_url that is not a repository fails before anything is mounted."""
    result = add_project("widget", str(tmp_path / "nope.git"), root=hub)
    assert result.startswith("error")
    assert load_config(hub).projects == []
    assert not subproject_path(hub, "widget").exists()


# ─── `projectman sync` puts a missing store back ────────────────────────────


class TestSyncReattachesAMissingStore:
    """US-PM-35 criterion (task US-PM-35-8, verified by US-PM-35-4):

        > projectman sync pulls every submodule and re-attaches any store
        > whose worktree is missing

    `add-project` is what mounts a store in the first place, so this is the
    natural place to pin the repair: the same fixtures, one `git worktree
    remove` in between.  A store worktree disappears the ordinary ways — a
    `git clean -ffdx`, a fresh clone of the submodule, a pruned checkout —
    and until it is back every hub read of that project says "not attached".
    """

    def _unmount(self, hub: Path) -> None:
        git("worktree", "remove", "--force", ".project", cwd=sub_of(hub))
        invalidate_store_map(hub)
        assert not store_of(hub).exists()

    def test_a_removed_store_worktree_is_mounted_again_and_reported(
        self, hub, sub_origin_with_store
    ):
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)
        head_before = out("rev-parse", "HEAD", cwd=store_of(hub))
        self._unmount(hub)

        result = sync(root=hub)

        assert worktree.is_worktree(store_of(hub))
        assert "1 stores attached" in result
        assert "widget: re-attached store at projects/widget/.project" in result
        # The branch was mounted, not rebuilt: same commit, same content.
        assert out("rev-parse", "HEAD", cwd=store_of(hub)) == head_before
        assert (store_of(hub) / "stories" / "US-RMT-3.md").exists()
        assert entry_for(hub)["attached"] is True

    def test_a_dirty_submodule_is_skipped_for_the_pull_and_still_re_attached(
        self, hub, sub_origin_with_store
    ):
        """The two passes are independent: an unpullable submodule is repaired."""
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)
        # add-project leaves `.gitignore` modified on the submodule's main
        # branch, so the pull pass skips it — the attach pass must not care.
        self._unmount(hub)

        result = sync(root=hub)

        assert "widget: dirty working tree, skipped" in result
        assert "1 stores attached" in result
        assert worktree.is_worktree(store_of(hub))

    def test_an_attached_store_is_left_exactly_as_it_was(
        self, hub, sub_origin_with_store
    ):
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)
        head_before = out("rev-parse", "HEAD", cwd=store_of(hub))

        result = sync(root=hub)

        assert "0 stores attached" in result
        assert "stores:" not in result
        assert out("rev-parse", "HEAD", cwd=store_of(hub)) == head_before

    def test_a_subproject_with_no_projectman_branch_gets_one_created(
        self, hub, sub_origin
    ):
        """No branch to attach, so `ensure_store_branch` makes and mounts one."""
        bare, _ = sub_origin
        add_project("widget", str(bare), root=hub)
        self._unmount(hub)
        # Drop the local branch too, so neither it nor origin/projectman exists.
        git("branch", "-D", "projectman", cwd=sub_of(hub))

        result = sync(root=hub)

        assert "created and mounted the 'projectman' store" in result
        assert "1 stores attached" in result
        assert worktree_branch_for(sub_of(hub), store_of(hub)).endswith("projectman")
        assert worktree.is_worktree(store_of(hub))

    def test_an_unmountable_store_is_reported_and_the_sync_continues(
        self, hub, sub_origin_with_store
    ):
        """PM data copied into the directory is migrate-hub's job, not sync's."""
        bare, _ = sub_origin_with_store
        add_project("widget", str(bare), root=hub)
        self._unmount(hub)
        store_of(hub).mkdir()
        (store_of(hub) / "config.yaml").write_text("name: widget\nprefix: WID\n")

        result = sync(root=hub)

        assert "0 stores attached" in result
        assert "widget: store not attached" in result
        assert result.startswith("sync complete:")
        # Nothing of the copied store was touched.
        assert (store_of(hub) / "config.yaml").read_text().startswith("name: widget")
