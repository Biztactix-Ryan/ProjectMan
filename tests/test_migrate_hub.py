"""`projectman migrate-hub` moves the hub's subproject stores onto the subprojects.

US-PM-31 criteria (task US-PM-31-8; verified by US-PM-31-3 and US-PM-31-4):

  > projectman migrate-hub moves every .project/projects/{name} store onto that
  > submodule's projectman branch worktree and removes the hub copy leaving
  > item files byte-identical

  > migrate-hub refuses to run on a dirty hub or subproject tree and is a
  > friendly no-op when nothing is left to migrate

The first criterion is pinned by ``TestTheHappyPath`` (both origin shapes) and
``TestPushing``; the second by ``TestRefusesADirtyTree``, ``TestNoOp`` and
``TestRefusesToMergeTwoStores``, with ``TestDryRun`` proving the
nothing-was-touched half a third way.

Everything is built out of real git repositories under ``tmp_path``: a bare
"origin" per subproject, a real ``git submodule add`` into a real hub, real
worktrees.  Nothing here may be pointed at a checkout anyone cares about.  The
``_git_env`` fixture is the recipe from ``tests/test_add_project_worktree.py``:
``protocol.file.allow`` so git will clone a submodule over the ``file``
transport, and an author identity for the commits made inside freshly cloned
submodules that have none configured.
"""

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from projectman import worktree
from projectman.cli import cli
from projectman.config import load_config, save_config
from projectman.hub.migrate import (
    EPICS_COMMIT_MESSAGE,
    HUB_REMOVAL_MESSAGE,
    NOTHING_TO_MIGRATE,
    format_migration,
    legacy_store_path,
    migrate_hub,
)
from projectman.hub.stores import (
    PROJECTS_DIRNAME,
    STORE_DIRNAME,
    hub_stores,
    invalidate,
    store_path,
    subproject_path,
)
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


@pytest.fixture(autouse=True)
def _fresh_store_map():
    """The store map caches per root and every test rebuilds the tree."""
    invalidate()
    yield
    invalidate()


# ─── Helpers ────────────────────────────────────────────────────────────────


def sha256_map(root: Path) -> dict[str, str]:
    """``{relative posix path: sha256}`` for every file under ``root``.

    Git's own bookkeeping is skipped: ``.git`` is a marker *file* in a mounted
    worktree and a directory in a checkout, and neither is PM data.
    """
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or path.name == ".git":
            continue
        if path.is_file():
            digests[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digests


def tree_hash(root: Path) -> dict[str, str]:
    """Hash every file under a whole checkout — the before/after of a refusal."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        if path.is_file():
            digests[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digests


def make_bare_origin(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A bare repo with a `main` branch, plus the checkout that feeds it."""
    bare = tmp_path / f"{name}-origin.git"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    work = init_repo(tmp_path / f"{name}-work")
    (work / "README.md").write_text(f"# {name}\n")
    (work / f"{name}.py").write_text("print('hi')\n")
    git("add", "-A", cwd=work)
    git("commit", "-m", "initial", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "origin", "main", cwd=work)
    return bare, work


def push_empty_projectman_branch(work: Path) -> None:
    """Give the origin a `projectman` branch whose root commit is empty.

    The awkward middle case: the branch exists (so migrate-hub *attaches*
    rather than creating), but there is no store on it, so the hub's copy is
    what fills it.
    """
    worktree._create_orphan_branch(work, "projectman")
    git("push", "origin", "projectman", cwd=work)


# The item files a legacy hub-side store holds.  Deliberately *without* an
# epic: since US-PM-36-8 the migration has a second half that carries
# subproject epics up to the hub, which is a move rather than a copy and adds
# a commit on both sides.  Keeping it out of here leaves the US-PM-31
# byte-identical/one-commit assertions below testing the store move alone;
# ``TestEpicsMoveUpToTheHub`` builds its own store with epics in it.
ITEMS = {
    "config.yaml": None,  # written per-project below
    "stories/US-{prefix}-1.md": (
        "---\nid: US-{prefix}-1\nstatus: active\n---\n\n"
        "# A story with — an em dash and a trailing space \n"
    ),
    "tasks/US-{prefix}-1-1.md": (
        "---\nid: US-{prefix}-1-1\nstatus: todo\n---\n\nDo the thing.\n"
    ),
    "logs/US-{prefix}-1-1.jsonl": (
        '{{"event":"claimed","task":"US-{prefix}-1-1"}}\n{{"event":"done"}}\n'
    ),
}


def write_legacy_store(hub: Path, name: str, prefix: str) -> Path:
    """The pre-US-PM-31 hub-side store, with real item files in it."""
    legacy = legacy_store_path(hub, name)
    legacy.mkdir(parents=True, exist_ok=True)
    for template, body in ITEMS.items():
        rel = template.format(prefix=prefix)
        path = legacy / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if body is None:
            path.write_text(
                yaml.dump(
                    {
                        "name": name,
                        "prefix": prefix,
                        "description": "",
                        "hub": False,
                        "next_story_id": 2,
                        "projects": [],
                    }
                )
            )
        else:
            path.write_text(body.format(prefix=prefix))
    # A binary file too: the criterion says *byte*-identical.
    (legacy / "dashboards").mkdir(exist_ok=True)
    (legacy / "dashboards" / "sparkline.png").write_bytes(bytes(range(256)))
    return legacy


def register(hub: Path, *names: str) -> None:
    config = load_config(hub)
    for name in names:
        if name not in config.projects:
            config.projects.append(name)
    save_config(config, hub)
    invalidate(hub)


def add_submodule(hub: Path, name: str, bare: Path) -> None:
    git("submodule", "add", str(bare), f"{PROJECTS_DIRNAME}/{name}", cwd=hub)


def commit_hub(hub: Path, message: str = "hub state") -> None:
    git("add", "-A", cwd=hub)
    git("commit", "-m", message, cwd=hub)


def entry_for(results: list[dict], name: str) -> dict:
    for entry in results:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"{name} not in {[e['name'] for e in results]}")


# ─── Fixtures: a hub mid-migration ──────────────────────────────────────────


@pytest.fixture
def hub(_git_env, tmp_git_hub):
    """A hub that is a real git repo — `git submodule add` needs one."""
    return tmp_git_hub


@pytest.fixture
def hub_to_migrate(hub, tmp_path):
    """Two registered submodules whose PM data is still in the hub.

    `alpha`'s origin already has a `projectman` branch (an empty orphan root,
    so there is no store on it) — migrate-hub must *attach* that one.
    `beta`'s origin has no such branch — migrate-hub must *create* it.
    Everything is committed, so the hub starts clean.
    """
    alpha_bare, alpha_work = make_bare_origin(tmp_path, "alpha")
    push_empty_projectman_branch(alpha_work)
    beta_bare, _ = make_bare_origin(tmp_path, "beta")

    add_submodule(hub, "alpha", alpha_bare)
    add_submodule(hub, "beta", beta_bare)

    write_legacy_store(hub, "alpha", "ALP")
    write_legacy_store(hub, "beta", "BET")
    register(hub, "alpha", "beta")

    commit_hub(hub, "hub with submodules and legacy PM data")
    assert worktree.dirty_paths(hub, STORE_DIRNAME) == []
    return hub


# ─── The happy path ─────────────────────────────────────────────────────────


class TestTheHappyPath:
    """US-PM-31-3: every store moves onto its branch, byte for byte."""

    def test_each_store_is_a_worktree_of_the_submodules_projectman_branch(
        self, hub_to_migrate
    ):
        hub = hub_to_migrate
        migrate_hub(hub)

        for name in ("alpha", "beta"):
            store, sub = store_path(hub, name), subproject_path(hub, name)
            assert worktree.is_worktree(store), f"{store} is not a worktree"
            assert worktree_branch_for(sub, store) == "refs/heads/projectman"

    def test_every_item_file_is_byte_identical(self, hub_to_migrate, tmp_path):
        hub = hub_to_migrate
        # Snapshot the source before it is removed.
        before = {
            name: sha256_map(legacy_store_path(hub, name))
            for name in ("alpha", "beta")
        }
        assert before["alpha"], "the fixture wrote no files"

        migrate_hub(hub)

        for name in ("alpha", "beta"):
            after = sha256_map(store_path(hub, name))
            assert after == before[name], name

    def test_the_binary_file_survives_byte_for_byte(self, hub_to_migrate):
        hub = hub_to_migrate
        migrate_hub(hub)
        blob = store_path(hub, "alpha") / "dashboards" / "sparkline.png"
        assert blob.read_bytes() == bytes(range(256))

    def test_the_hub_copy_is_gone_and_committed_away(self, hub_to_migrate):
        hub = hub_to_migrate
        head_before = out("rev-parse", "HEAD", cwd=hub)

        results = migrate_hub(hub)

        for name in ("alpha", "beta"):
            assert not legacy_store_path(hub, name).exists()
        # And it is *committed*, not merely deleted from the worktree.
        head_after = out("rev-parse", "HEAD", cwd=hub)
        assert head_after != head_before
        tracked = out("ls-files", cwd=hub).splitlines()
        assert not [p for p in tracked if p.startswith(f"{STORE_DIRNAME}/{PROJECTS_DIRNAME}/")]
        assert results[0]["hub_commit"] == head_after

    def test_the_hub_commit_message_names_the_projects_moved(self, hub_to_migrate):
        hub = hub_to_migrate
        migrate_hub(hub)
        message = out("log", "-1", "--pretty=%B", cwd=hub)
        assert HUB_REMOVAL_MESSAGE in message
        assert "alpha" in message and "beta" in message

    def test_the_branch_commit_message_names_the_source(self, hub_to_migrate):
        hub = hub_to_migrate
        results = migrate_hub(hub)

        for name in ("alpha", "beta"):
            message = out("log", "-1", "--pretty=%B", cwd=store_path(hub, name))
            assert f"{STORE_DIRNAME}/{PROJECTS_DIRNAME}/{name}" in message, message
            assert entry_for(results, name)["source_rel"] in message

    def test_the_files_are_committed_on_the_branch_not_just_sitting_there(
        self, hub_to_migrate
    ):
        hub = hub_to_migrate
        migrate_hub(hub)

        for name, prefix in (("alpha", "ALP"), ("beta", "BET")):
            sub = subproject_path(hub, name)
            tracked = set(out("ls-tree", "-r", "--name-only", "projectman", cwd=sub).splitlines())
            assert "config.yaml" in tracked
            assert f"stories/US-{prefix}-1.md" in tracked
            assert f"tasks/US-{prefix}-1-1.md" in tracked
            # Nothing left uncommitted in the mounted store.
            assert out("status", "--porcelain", cwd=store_path(hub, name)) == ""

    def test_hub_stores_lists_both_attached_with_their_own_prefixes(
        self, hub_to_migrate
    ):
        hub = hub_to_migrate
        migrate_hub(hub)

        entries = {e["name"]: e for e in hub_stores(hub)}
        assert set(entries) == {"alpha", "beta"}
        assert entries["alpha"]["attached"] is True
        assert entries["beta"]["attached"] is True
        assert entries["alpha"]["prefix"] == "ALP"
        assert entries["beta"]["prefix"] == "BET"

    def test_the_existing_branch_is_attached_and_the_missing_one_created(
        self, hub_to_migrate
    ):
        hub = hub_to_migrate
        results = migrate_hub(hub)

        assert entry_for(results, "alpha")["store_source"] == "attached"
        assert entry_for(results, "beta")["store_source"] == "created"
        # alpha's branch keeps the origin's root commit as its ancestor.
        alpha = subproject_path(hub, "alpha")
        assert out("rev-list", "--count", "projectman", cwd=alpha) == "2"
        assert worktree.upstream_of(alpha, "projectman") == "origin/projectman"

    def test_the_store_is_gitignored_in_each_submodule_checkout(
        self, hub_to_migrate
    ):
        """A mounted worktree would otherwise be untracked noise in the checkout."""
        hub = hub_to_migrate
        migrate_hub(hub)

        for name in ("alpha", "beta"):
            sub = subproject_path(hub, name)
            lines = [
                line.strip().strip("/")
                for line in (sub / ".gitignore").read_text().splitlines()
            ]
            assert STORE_DIRNAME in lines
            assert STORE_DIRNAME not in out("status", "--porcelain", cwd=sub)

    def test_the_submodule_source_code_is_untouched(self, hub_to_migrate):
        hub = hub_to_migrate
        migrate_hub(hub)

        for name in ("alpha", "beta"):
            sub = subproject_path(hub, name)
            assert (sub / f"{name}.py").read_text() == "print('hi')\n"
            assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=sub) == "main"

    def test_the_hubs_own_pm_data_is_left_alone(self, hub_to_migrate):
        hub = hub_to_migrate
        before = (hub / STORE_DIRNAME / "config.yaml").read_bytes()
        migrate_hub(hub)
        assert (hub / STORE_DIRNAME / "config.yaml").read_bytes() == before
        assert not (hub / STORE_DIRNAME / PROJECTS_DIRNAME).exists()

    def test_the_summary_names_every_project_and_both_paths(self, hub_to_migrate):
        hub = hub_to_migrate
        text = format_migration(migrate_hub(hub))
        assert "Migrated 2 subproject stores" in text
        for name in ("alpha", "beta"):
            assert name in text
            assert f"{PROJECTS_DIRNAME}/{name}/{STORE_DIRNAME}" in text


# ─── Pushing ────────────────────────────────────────────────────────────────


class TestPushing:
    def test_the_branch_is_pushed_to_each_origin(self, hub_to_migrate, tmp_path):
        hub = hub_to_migrate
        results = migrate_hub(hub)

        for name in ("alpha", "beta"):
            entry = entry_for(results, name)
            assert entry["pushed"] is True, entry
            bare = tmp_path / f"{name}-origin.git"
            remote_head = out("rev-parse", "projectman", cwd=bare)
            assert remote_head == entry["commit"]

    def test_no_push_leaves_the_branch_local(self, hub_to_migrate, tmp_path):
        hub = hub_to_migrate
        results = migrate_hub(hub, push=False)

        for name in ("alpha", "beta"):
            assert entry_for(results, name)["pushed"] is False
        # beta's origin never heard of the branch...
        beta_bare = tmp_path / "beta-origin.git"
        assert git(
            "rev-parse", "--verify", "projectman", cwd=beta_bare, check=False
        ).returncode != 0
        # ...and alpha's still points at the empty root it started with.
        alpha_bare = tmp_path / "alpha-origin.git"
        assert out("rev-parse", "projectman", cwd=alpha_bare) != entry_for(
            results, "alpha"
        )["commit"]
        # The local move happened all the same.
        assert worktree.is_worktree(store_path(hub, "beta"))

    def test_no_push_still_says_so_in_the_summary(self, hub_to_migrate):
        text = format_migration(migrate_hub(hub_to_migrate, push=False))
        assert "--no-push" in text

    def test_a_subproject_without_a_remote_is_not_a_failure(
        self, hub_to_migrate, tmp_path
    ):
        hub = hub_to_migrate
        git("remote", "remove", "origin", cwd=subproject_path(hub, "beta"))

        results = migrate_hub(hub)

        beta = entry_for(results, "beta")
        assert beta["remote"] is None
        assert beta["pushed"] is False
        assert beta["push_error"] is None
        assert entry_for(results, "alpha")["pushed"] is True

    def test_a_push_failure_only_warns(self, hub_to_migrate, tmp_path):
        hub = hub_to_migrate
        git(
            "remote", "set-url", "origin", str(tmp_path / "gone.git"),
            cwd=subproject_path(hub, "beta"),
        )

        results = migrate_hub(hub)

        beta = entry_for(results, "beta")
        assert beta["pushed"] is False
        assert beta["push_error"]
        # The local migration is complete regardless.
        assert worktree.is_worktree(store_path(hub, "beta"))
        assert not legacy_store_path(hub, "beta").exists()
        assert "WARNING: push failed" in format_migration(results)


# ─── The refusals ───────────────────────────────────────────────────────────


class TestRefusesADirtyTree:
    """US-PM-31-4, first half: refuse before mutating anything."""

    def test_a_dirty_hub_tree_is_refused(self, hub_to_migrate):
        hub = hub_to_migrate
        # A tracked file inside the hub's own store — the case a user hits by
        # editing PM data and forgetting to commit it.
        tracked = [
            line
            for line in out("ls-files", "--", STORE_DIRNAME, cwd=hub).splitlines()
            if not line.endswith("config.yaml")
        ]
        assert tracked, "the hub store tracks nothing to dirty"
        (hub / tracked[0]).write_text("dirtied\n")

        with pytest.raises(worktree.MigrationError, match="uncommitted changes"):
            migrate_hub(hub)
        assert tracked[0] in str(
            pytest.raises(worktree.MigrationError, migrate_hub, hub).value
        )

    def test_a_dirty_hub_tree_mutates_nothing(self, hub_to_migrate):
        hub = hub_to_migrate
        (hub / "README.md").write_text("# touched\n")
        git("add", "README.md", cwd=hub)

        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        with pytest.raises(worktree.MigrationError):
            migrate_hub(hub)

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head
        for name in ("alpha", "beta"):
            assert legacy_store_path(hub, name).is_dir()
            assert not store_path(hub, name).exists()
            assert not worktree.branch_exists(subproject_path(hub, name), "projectman")

    def test_a_dirty_subproject_tree_is_refused(self, hub_to_migrate):
        hub = hub_to_migrate
        beta = subproject_path(hub, "beta")
        (beta / "beta.py").write_text("print('edited')\n")

        with pytest.raises(worktree.MigrationError, match="subproject 'beta'"):
            migrate_hub(hub)

    def test_a_dirty_subproject_mutates_nothing_not_even_the_clean_one(
        self, hub_to_migrate
    ):
        """The run is abandoned whole: `alpha` is clean but is not migrated."""
        hub = hub_to_migrate
        (subproject_path(hub, "beta") / "beta.py").write_text("print('edited')\n")

        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        with pytest.raises(worktree.MigrationError):
            migrate_hub(hub)

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head
        assert legacy_store_path(hub, "alpha").is_dir()
        assert not store_path(hub, "alpha").exists()
        alpha = subproject_path(hub, "alpha")
        # alpha's branch came from origin and must not have gained a commit.
        assert worktree_branch_for(alpha, store_path(hub, "alpha")) is None

    def test_the_refusal_names_the_offending_paths(self, hub_to_migrate):
        hub = hub_to_migrate
        (subproject_path(hub, "alpha") / "alpha.py").write_text("x = 1\n")

        with pytest.raises(worktree.MigrationError) as exc:
            migrate_hub(hub)
        assert "alpha.py" in str(exc.value)

    def test_a_missing_submodule_checkout_is_refused(self, hub_to_migrate):
        hub = hub_to_migrate
        shutil.rmtree(subproject_path(hub, "beta"))

        with pytest.raises(worktree.MigrationError, match="not checked out"):
            migrate_hub(hub)

        assert legacy_store_path(hub, "alpha").is_dir()


class TestRefusesToMergeTwoStores:
    """An attached branch that already has a store is a merge, not a move."""

    @pytest.fixture
    def hub_with_a_populated_branch(self, hub, tmp_path):
        bare, work = make_bare_origin(tmp_path, "gamma")
        git("checkout", "--orphan", "projectman", cwd=work)
        git("rm", "-rf", ".", cwd=work, check=False)
        (work / "config.yaml").write_text("name: gamma\nprefix: GAM\nhub: false\n")
        git("add", "-A", cwd=work)
        git("commit", "-m", "PM store", cwd=work)
        git("push", "origin", "projectman", cwd=work)
        git("checkout", "main", cwd=work)

        add_submodule(hub, "gamma", bare)
        write_legacy_store(hub, "gamma", "GAM")
        register(hub, "gamma")
        commit_hub(hub, "hub with a subproject that already has a store")
        return hub

    def test_it_refuses_rather_than_clobbering(self, hub_with_a_populated_branch):
        hub = hub_with_a_populated_branch
        with pytest.raises(worktree.MigrationError, match="already has a store"):
            migrate_hub(hub)

    def test_nothing_is_touched_on_either_side(self, hub_with_a_populated_branch):
        hub = hub_with_a_populated_branch
        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        with pytest.raises(worktree.MigrationError):
            migrate_hub(hub)

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head
        assert legacy_store_path(hub, "gamma").is_dir()
        assert not store_path(hub, "gamma").exists()

    def test_the_message_says_what_to_do(self, hub_with_a_populated_branch):
        with pytest.raises(worktree.MigrationError) as exc:
            migrate_hub(hub_with_a_populated_branch)
        text = str(exc.value)
        assert "config.yaml" in text
        assert "will not merge" in text


class TestRefusesAnUnmountedCopy:
    """A store copied into the checkout is not ours to overwrite."""

    def test_it_refuses_when_the_target_holds_content(self, hub_to_migrate):
        hub = hub_to_migrate
        target = store_path(hub, "beta")
        target.mkdir(parents=True)
        (target / "config.yaml").write_text("name: someone-elses\n")

        with pytest.raises(worktree.MigrationError, match="not a mounted worktree"):
            migrate_hub(hub)

        assert (target / "config.yaml").read_text() == "name: someone-elses\n"
        assert legacy_store_path(hub, "alpha").is_dir()


# ─── The no-op ──────────────────────────────────────────────────────────────


class TestNoOp:
    """US-PM-31-4, second half: nothing left to migrate is a success."""

    def test_a_hub_with_nothing_left_returns_no_results(self, hub_to_migrate):
        hub = hub_to_migrate
        migrate_hub(hub)
        assert migrate_hub(hub) == []

    def test_running_it_twice_changes_nothing_the_second_time(self, hub_to_migrate):
        hub = hub_to_migrate
        migrate_hub(hub)
        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        assert migrate_hub(hub) == []

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head

    def test_a_hub_that_never_had_the_old_layout_is_a_no_op(self, hub, tmp_path):
        bare, _ = make_bare_origin(tmp_path, "delta")
        add_submodule(hub, "delta", bare)
        register(hub, "delta")
        commit_hub(hub)
        assert migrate_hub(hub) == []

    def test_the_no_op_message_is_friendly_and_says_where_the_data_lives(self):
        text = format_migration([])
        assert "Nothing to migrate" in text
        assert not text.lower().startswith("error")
        assert f"{PROJECTS_DIRNAME}/{{name}}/{STORE_DIRNAME}" in text

    def test_a_non_hub_project_is_refused_not_silently_skipped(self, tmp_project):
        with pytest.raises(worktree.MigrationError, match="not a hub"):
            migrate_hub(tmp_project)


# ─── The dry run ────────────────────────────────────────────────────────────


class TestDryRun:
    def test_it_reports_the_plan(self, hub_to_migrate):
        results = migrate_hub(hub_to_migrate, dry_run=True)
        assert [e["name"] for e in results] == ["alpha", "beta"]
        assert all(e["dry_run"] is True for e in results)
        assert entry_for(results, "alpha")["store_source"] == "attached"
        assert entry_for(results, "beta")["store_source"] == "created"
        assert entry_for(results, "alpha")["files"] == len(ITEMS) + 1

    def test_it_mutates_nothing(self, hub_to_migrate):
        hub = hub_to_migrate
        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        migrate_hub(hub, dry_run=True)

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head
        for name in ("alpha", "beta"):
            assert legacy_store_path(hub, name).is_dir()
            assert not store_path(hub, name).exists()
        assert not worktree.branch_exists(subproject_path(hub, "beta"), "projectman")

    def test_it_still_refuses_a_dirty_tree(self, hub_to_migrate):
        hub = hub_to_migrate
        (hub / "README.md").write_text("# touched\n")
        git("add", "README.md", cwd=hub)
        with pytest.raises(worktree.MigrationError):
            migrate_hub(hub, dry_run=True)

    def test_the_summary_says_it_changed_nothing(self, hub_to_migrate):
        text = format_migration(migrate_hub(hub_to_migrate, dry_run=True))
        assert "Would migrate 2" in text
        assert "--dry-run" in text


# ─── The epics step (US-PM-36-8) ────────────────────────────────────────────


EPIC_FILE = (
    "---\n"
    "id: {epic_id}\n"
    "title: {title}\n"
    "status: active\n"
    "priority: must\n"
    "points: null\n"
    "target_date: null\n"
    "tags: []\n"
    "created: '2026-01-01'\n"
    "updated: '2026-01-01'\n"
    "---\n\n"
    "## Vision\n\n{title}, across every repo.\n"
)

LINKED_STORY_FILE = (
    "---\n"
    "id: {story_id}\n"
    "title: {title}\n"
    "status: active\n"
    "priority: must\n"
    "points: 3\n"
    "epic_id: {epic_id}\n"
    "tags: []\n"
    "acceptance_criteria: []\n"
    "depends_on: []\n"
    "created: '2026-01-01'\n"
    "updated: '2026-01-01'\n"
    "---\n\n"
    "A story that belongs to an epic.\n"
)


def write_epic(store: Path, epic_id: str, title: str) -> Path:
    path = store / "epics" / f"{epic_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EPIC_FILE.format(epic_id=epic_id, title=title))
    return path


def write_linked_story(store: Path, story_id: str, epic_id: str) -> Path:
    path = store / "stories" / f"{story_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        LINKED_STORY_FILE.format(
            story_id=story_id, title=f"{story_id} work", epic_id=epic_id
        )
    )
    return path


def epic_ids_in(store: Path) -> list[str]:
    epics = store / "epics"
    return sorted(p.stem for p in epics.glob("EPIC-*.md")) if epics.is_dir() else []


def epic_link_of(store: Path, story_id: str) -> str:
    from projectman.hub.migrate import read_field

    return read_field((store / "stories" / f"{story_id}.md").read_text(), "epic_id")


@pytest.fixture
def hub_with_subproject_epics(hub_to_migrate):
    """The legacy hub, plus an epic per subproject and stories linked to them.

    ``US-ALP-3`` is the awkward one: it lives in *alpha* and links to an epic
    that lives in *beta*, which only a hub-wide mapping gets right.
    """
    hub = hub_to_migrate
    alpha, beta = (legacy_store_path(hub, n) for n in ("alpha", "beta"))

    write_epic(alpha, "EPIC-ALP-1", "Unified auth")
    write_epic(beta, "EPIC-BET-1", "Fleet telemetry")
    write_linked_story(alpha, "US-ALP-2", "EPIC-ALP-1")
    write_linked_story(alpha, "US-ALP-3", "EPIC-BET-1")
    write_linked_story(beta, "US-BET-2", "EPIC-BET-1")

    commit_hub(hub, "legacy stores with epics")
    assert worktree.dirty_paths(hub, STORE_DIRNAME) == []
    return hub


class TestEpicsMoveUpToTheHub:
    """US-PM-36: epics live at hub level, so the migration carries them up."""

    def test_each_subproject_epic_becomes_a_hub_epic(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)

        assert epic_ids_in(hub / STORE_DIRNAME) == ["EPIC-HUB-1", "EPIC-HUB-2"]
        for name in ("alpha", "beta"):
            assert epic_ids_in(store_path(hub, name)) == []

    def test_the_epic_body_survives_the_rename(self, hub_with_subproject_epics):
        hub = hub_with_subproject_epics
        migrate_hub(hub)

        text = (hub / STORE_DIRNAME / "epics" / "EPIC-HUB-1.md").read_text()
        assert "id: EPIC-HUB-1" in text
        assert "EPIC-ALP-1" not in text
        assert "title: Unified auth" in text
        assert "Unified auth, across every repo." in text

    def test_every_linked_story_is_rewritten_including_across_projects(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)

        alpha, beta = (store_path(hub, n) for n in ("alpha", "beta"))
        assert epic_link_of(alpha, "US-ALP-2") == "EPIC-HUB-1"
        # alpha's story pointed at an epic that lived in beta.
        assert epic_link_of(alpha, "US-ALP-3") == "EPIC-HUB-2"
        assert epic_link_of(beta, "US-BET-2") == "EPIC-HUB-2"

    def test_the_hub_counter_advances_so_the_next_epic_is_fresh(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)
        assert load_config(hub).next_epic_id == 3

    def test_the_mapping_is_returned_old_to_new(self, hub_with_subproject_epics):
        hub = hub_with_subproject_epics
        results = migrate_hub(hub)

        assert [(m["old_id"], m["new_id"]) for m in results.epics] == [
            ("EPIC-ALP-1", "EPIC-HUB-1"),
            ("EPIC-BET-1", "EPIC-HUB-2"),
        ]
        by_old = {m["old_id"]: m for m in results.epics}
        assert by_old["EPIC-ALP-1"]["stories"] == ["US-ALP-2"]
        assert sorted(by_old["EPIC-BET-1"]["stories"]) == ["US-ALP-3", "US-BET-2"]

    def test_the_mapping_is_printed(self, hub_with_subproject_epics):
        text = format_migration(migrate_hub(hub_with_subproject_epics))
        assert "EPIC-ALP-1 -> EPIC-HUB-1" in text
        assert "EPIC-BET-1 -> EPIC-HUB-2" in text
        assert "US-ALP-3" in text

    def test_each_side_is_committed_with_the_mapping_in_the_message(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)

        for cwd in (hub, store_path(hub, "alpha"), store_path(hub, "beta")):
            message = out("log", "-1", "--pretty=%B", cwd=cwd)
            assert EPICS_COMMIT_MESSAGE in message, cwd
            assert "EPIC-ALP-1 -> EPIC-HUB-1" in message, cwd
        # Nothing left uncommitted on either side.
        for name in ("alpha", "beta"):
            assert out("status", "--porcelain", cwd=store_path(hub, name)) == ""

    def test_the_hub_epic_is_tracked_not_merely_on_disk(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)
        tracked = out("ls-files", cwd=hub).splitlines()
        assert f"{STORE_DIRNAME}/epics/EPIC-HUB-1.md" in tracked

    def test_the_hub_index_is_rebuilt_over_the_new_epics(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        migrate_hub(hub)
        index = yaml.safe_load((hub / STORE_DIRNAME / "index.yaml").read_text())
        assert "EPIC-HUB-1" in yaml.dump(index)

    def test_pm_epic_can_read_the_moved_epic_back(self, hub_with_subproject_epics):
        """The output has to be what US-PM-36-6/-7 expect: a hub-prefixed ID."""
        from projectman.store import Store

        hub = hub_with_subproject_epics
        migrate_hub(hub)
        meta, _ = Store(hub).get_epic("EPIC-HUB-1")
        assert meta.title == "Unified auth"

    def test_re_running_is_a_no_op(self, hub_with_subproject_epics):
        hub = hub_with_subproject_epics
        migrate_hub(hub)
        before = tree_hash(hub)
        heads = {
            "hub": out("rev-parse", "HEAD", cwd=hub),
            "alpha": out("rev-parse", "HEAD", cwd=store_path(hub, "alpha")),
        }

        again = migrate_hub(hub)

        assert again == []
        assert again.epics == []
        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == heads["hub"]
        assert out("rev-parse", "HEAD", cwd=store_path(hub, "alpha")) == heads["alpha"]

    def test_dry_run_reports_the_mapping_and_changes_nothing(
        self, hub_with_subproject_epics
    ):
        hub = hub_with_subproject_epics
        before = tree_hash(hub)
        head = out("rev-parse", "HEAD", cwd=hub)

        results = migrate_hub(hub, dry_run=True)

        assert [(m["old_id"], m["new_id"]) for m in results.epics] == [
            ("EPIC-ALP-1", "EPIC-HUB-1"),
            ("EPIC-BET-1", "EPIC-HUB-2"),
        ]
        text = format_migration(results)
        assert "Would move 2 subproject epics" in text
        assert "EPIC-BET-1 -> EPIC-HUB-2" in text

        assert tree_hash(hub) == before
        assert out("rev-parse", "HEAD", cwd=hub) == head
        assert load_config(hub).next_epic_id == 1
        assert not (hub / STORE_DIRNAME / "epics").exists()


class TestEpicsOnAHubAlreadyAtTheNewLayout:
    """The step has to be runnable on its own — US-PM-31 is long since done."""

    @pytest.fixture
    def migrated_hub_with_an_epic(self, hub_to_migrate):
        hub = hub_to_migrate
        # push=False: the bare origins live under tmp_path, which *is* the hub
        # repo here, so a push would leave their refs as changes in the hub's
        # own tree and the next run would refuse a dirty hub.
        migrate_hub(hub, push=False)
        assert not legacy_store_path(hub, "alpha").exists()

        alpha = store_path(hub, "alpha")
        write_epic(alpha, "EPIC-ALP-1", "Unified auth")
        write_linked_story(alpha, "US-ALP-2", "EPIC-ALP-1")
        git("add", "-A", cwd=alpha)
        git("commit", "-m", "an epic of alpha's own", cwd=alpha)
        return hub

    def test_only_the_epics_step_runs(self, migrated_hub_with_an_epic):
        hub = migrated_hub_with_an_epic
        results = migrate_hub(hub)

        assert results == []  # no store move left to make
        assert [(m["old_id"], m["new_id"]) for m in results.epics] == [
            ("EPIC-ALP-1", "EPIC-HUB-1")
        ]
        assert epic_ids_in(hub / STORE_DIRNAME) == ["EPIC-HUB-1"]
        assert epic_ids_in(store_path(hub, "alpha")) == []
        assert epic_link_of(store_path(hub, "alpha"), "US-ALP-2") == "EPIC-HUB-1"

    def test_the_summary_says_only_the_epics_needed_moving(
        self, migrated_hub_with_an_epic
    ):
        text = format_migration(migrate_hub(migrated_hub_with_an_epic))
        assert "Moved 1 subproject epic up to the hub" in text
        assert "EPIC-ALP-1 -> EPIC-HUB-1" in text
        assert "Migrated" not in text

    def test_a_dirty_subproject_store_is_refused_and_mutates_nothing(
        self, migrated_hub_with_an_epic
    ):
        hub = migrated_hub_with_an_epic
        (store_path(hub, "alpha") / "stories" / "US-ALP-2.md").write_text(
            "---\nid: US-ALP-2\n---\n\ntouched\n"
        )
        before = tree_hash(hub)

        with pytest.raises(worktree.MigrationError, match="uncommitted changes"):
            migrate_hub(hub)

        assert tree_hash(hub) == before
        assert epic_ids_in(hub / STORE_DIRNAME) == []

    def test_a_hub_with_no_subproject_epics_is_the_friendly_no_op(
        self, hub_to_migrate
    ):
        hub = hub_to_migrate
        migrate_hub(hub)
        assert migrate_hub(hub) == []
        assert format_migration(migrate_hub(hub)) == NOTHING_TO_MIGRATE


# ─── The CLI ────────────────────────────────────────────────────────────────


class TestTheCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _invoke(self, runner, hub, *args):
        return runner.invoke(cli, ["migrate-hub", *args], catch_exceptions=False)

    def test_it_migrates_and_exits_zero(self, runner, hub_to_migrate, monkeypatch):
        hub = hub_to_migrate
        monkeypatch.chdir(hub)
        result = self._invoke(runner, hub)

        assert result.exit_code == 0, result.output
        assert "Migrated 2 subproject stores" in result.output
        assert worktree.is_worktree(store_path(hub, "alpha"))
        assert not legacy_store_path(hub, "beta").exists()

    def test_no_push_is_wired_through(self, runner, hub_to_migrate, monkeypatch, tmp_path):
        hub = hub_to_migrate
        monkeypatch.chdir(hub)
        result = self._invoke(runner, hub, "--no-push")

        assert result.exit_code == 0, result.output
        assert "--no-push" in result.output
        beta_bare = tmp_path / "beta-origin.git"
        assert git(
            "rev-parse", "--verify", "projectman", cwd=beta_bare, check=False
        ).returncode != 0

    def test_dry_run_is_wired_through(self, runner, hub_to_migrate, monkeypatch):
        hub = hub_to_migrate
        monkeypatch.chdir(hub)
        result = self._invoke(runner, hub, "--dry-run")

        assert result.exit_code == 0, result.output
        assert "Would migrate 2" in result.output
        assert not store_path(hub, "alpha").exists()

    def test_the_no_op_exits_zero_with_a_friendly_message(
        self, runner, hub_to_migrate, monkeypatch
    ):
        hub = hub_to_migrate
        migrate_hub(hub)
        monkeypatch.chdir(hub)

        result = self._invoke(runner, hub)

        assert result.exit_code == 0, result.output
        assert "Nothing to migrate" in result.output

    def test_a_refusal_exits_one_with_the_reason_on_stderr(
        self, runner, hub_to_migrate, monkeypatch
    ):
        hub = hub_to_migrate
        (hub / "README.md").write_text("# touched\n")
        git("add", "README.md", cwd=hub)
        monkeypatch.chdir(hub)

        result = self._invoke(runner, hub)

        assert result.exit_code == 1
        assert "uncommitted changes" in result.output
        assert legacy_store_path(hub, "alpha").is_dir()

    def test_the_command_is_registered_with_help(self, runner):
        result = runner.invoke(cli, ["migrate-hub", "--help"])
        assert result.exit_code == 0
        assert "--no-push" in result.output
        assert "--dry-run" in result.output
