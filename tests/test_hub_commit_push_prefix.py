"""`pm_commit` / `pm_push` in a hub act on the one store a prefix names.

US-PM-35 criterion (task US-PM-35-7, verified by US-PM-35-2):

    > pm_commit and pm_push in a hub act on the one store named by prefix and
    > land commits on that subproject's projectman branch

The hub is a read-only rollup.  There is no `scope`, no fan-out and no
cross-repo orchestration left: a write to `US-API-3` is committed and pushed
*inside* `projects/api`, by the ordinary verbs pointed at that store with
`prefix="API"`, exactly as single-project mode does.

Everything here runs against real git repositories under `tmp_path` — a bare
origin per subproject, a real `git submodule add` into a real hub, and stores
that are real worktrees of each submodule's `projectman` branch — because the
whole question is which *branch in which repository* a commit lands on, and
no fake can answer it.

Two environment details keep it hermetic, both borrowed from
`tests/test_add_project_worktree.py`: `protocol.file.allow=always` (git
refuses to clone a submodule over the `file` transport by default) and a git
identity in the environment, since the store commit happens inside a freshly
cloned submodule with no local identity.
"""

from pathlib import Path

import pytest
import yaml

from projectman import worktree
from projectman.hub.registry import add_project
from projectman.hub.stores import store_path, subproject_path
from projectman.indexer import write_store_gitignore
from projectman.store import clear_all_caches

from test_migrate_worktree import git, init_repo, out


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


def _reset_caches() -> None:
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _sub_origin(tmp_path: Path, name: str, prefix: str) -> Path:
    """A bare remote for one subproject, carrying a store on `projectman`.

    This is what a migrated subproject looks like from the outside: `main`
    with the code, and an orphan `projectman` branch whose root *is* the PM
    store.  `add_project` clones it and mounts that branch as the store.
    """
    bare = tmp_path / f"{name}-origin.git"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)

    work = init_repo(tmp_path / f"{name}-work")
    (work / f"{name}.py").write_text(f"print('{name}')\n")
    git("add", "-A", cwd=work)
    git("commit", "-m", "initial", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "origin", "main", cwd=work)

    git("checkout", "--orphan", "projectman", cwd=work)
    git("rm", "-rf", ".", cwd=work, check=False)
    (work / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "prefix": prefix,
                "description": "",
                "hub": False,
                "next_story_id": 1,
            }
        )
    )
    (work / "stories").mkdir(exist_ok=True)
    (work / "tasks").mkdir(exist_ok=True)
    (work / "PROJECT.md").write_text(f"# {name}\n")
    # A scaffolded store gitignores its five derived index files (US-PM-29-6),
    # so this one does too — otherwise the rebuild pm_commit does before
    # staging would put five files behind every commit.
    write_store_gitignore(work)
    git("add", "-A", cwd=work)
    git("commit", "-m", "PM store", cwd=work)
    git("push", "origin", "projectman", cwd=work)
    git("checkout", "main", cwd=work)
    return bare


@pytest.fixture
def hub(tmp_git_hub, tmp_path_factory, monkeypatch):
    """A real hub repo with two attached subproject stores, API and WEB.

    Both are worktrees of their *own* submodule's `projectman` branch, each
    with its own bare origin, which is the layout US-PM-31 established and the
    only one in which "landed on that subproject's branch" means anything.
    """
    remotes = tmp_path_factory.mktemp("remotes")
    for name, prefix in (("api", "API"), ("web", "WEB")):
        bare = _sub_origin(remotes, name, prefix)
        result = add_project(name, str(bare), root=tmp_git_hub)
        assert not result.startswith("error"), result
        assert worktree.is_worktree(store_path(tmp_git_hub, name))

    git("add", "-A", cwd=tmp_git_hub)
    git("commit", "-m", "add subprojects", cwd=tmp_git_hub)

    monkeypatch.chdir(tmp_git_hub)
    _reset_caches()
    yield tmp_git_hub
    _reset_caches()


# ─── Helpers ────────────────────────────────────────────────────────────────


def story(root: Path, story_id: str, name: str | None = None) -> Path:
    """Write a story into the hub's own store, or into a subproject's."""
    base = store_path(root, name) if name else root / ".project"
    path = base / "stories" / f"{story_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {story_id}\ntitle: A story\nstatus: backlog\n---\n\nBody.\n")
    return path


def head(repo: Path, ref: str = "HEAD") -> str:
    return out("rev-parse", ref, cwd=repo)


def porcelain(repo: Path) -> str:
    return out("status", "--porcelain", "--untracked-files=all", cwd=repo)


def ls_remote(repo: Path, ref: str) -> str:
    line = out("ls-remote", "origin", ref, cwd=repo)
    return line.split()[0] if line else ""


def committed(result: str) -> dict:
    return yaml.safe_load(result)["committed"]


def pushed(result: str) -> dict:
    return yaml.safe_load(result)["pushed"]


# ─── Commit ─────────────────────────────────────────────────────────────────


class TestCommitActsOnTheStoreThePrefixNames:
    def test_the_commit_lands_on_that_subprojects_projectman_branch(self, hub):
        from projectman.server import pm_commit

        story(hub, "US-API-1", "api")
        api = store_path(hub, "api")
        before = head(api)

        result = committed(pm_commit(prefix="API"))

        assert result["on_branch"] == "projectman"
        assert result["files_committed"] == 1
        assert result["commit_hash"] == head(api)
        assert result["commit_hash"] != before
        # The branch that moved is the submodule's own, not the hub's.
        assert head(api) == out(
            "rev-parse", "projectman", cwd=subproject_path(hub, "api")
        )
        assert "US-API-1.md" in out(
            "show", "--name-only", "--format=", "HEAD", cwd=api
        )

    def test_the_other_store_and_the_hub_are_left_untouched(self, hub):
        from projectman.server import pm_commit

        story(hub, "US-API-1", "api")
        story(hub, "US-WEB-1", "web")
        story(hub, "US-HUB-1")

        hub_head, web_head = head(hub), head(store_path(hub, "web"))
        pointer_before = out("rev-parse", "HEAD:projects/api", cwd=hub)
        hub_status_before = porcelain(hub)

        pm_commit(prefix="API")

        assert head(hub) == hub_head
        assert head(store_path(hub, "web")) == web_head
        # Both of the untouched stores still have their story uncommitted.
        assert "US-WEB-1.md" in porcelain(store_path(hub, "web"))
        assert "US-HUB-1.md" in porcelain(hub / ".project")
        # And the submodule pointer never moved: PM data is not hub data.
        assert out("rev-parse", "HEAD:projects/api", cwd=hub) == pointer_before
        assert porcelain(hub) == hub_status_before

    def test_an_omitted_prefix_commits_the_hubs_own_store(self, hub):
        from projectman.server import pm_commit

        story(hub, "US-HUB-1")
        story(hub, "US-API-1", "api")
        api_head = head(store_path(hub, "api"))

        result = committed(pm_commit())

        assert "US-HUB-1.md" in out(
            "show", "--name-only", "--format=", result["commit_hash"], cwd=hub
        )
        assert head(store_path(hub, "api")) == api_head
        assert "US-API-1.md" in porcelain(store_path(hub, "api"))

    def test_a_clean_store_is_the_expected_negative(self, hub):
        from projectman.server import pm_commit

        body = yaml.safe_load(pm_commit(prefix="WEB"))

        assert body["outcome"] == "expected_negative"
        assert body["status"] == "nothing_to_commit"

    def test_an_unknown_prefix_is_the_coded_not_found(self, hub):
        from mcp.server.fastmcp.exceptions import ToolError

        from projectman.server import pm_commit

        story(hub, "US-API-1", "api")

        with pytest.raises(ToolError) as excinfo:
            pm_commit(prefix="NOPE")

        assert "NOPE" in str(excinfo.value)
        assert "API" in str(excinfo.value) and "WEB" in str(excinfo.value)
        assert "[code: not_found]" in str(excinfo.value)
        # Refused before any git ran: the story is still uncommitted.
        assert "US-API-1.md" in porcelain(store_path(hub, "api"))

    def test_the_prefix_is_case_insensitive(self, hub):
        from projectman.server import pm_commit

        story(hub, "US-WEB-1", "web")

        assert committed(pm_commit(prefix="web"))["on_branch"] == "projectman"


# ─── Push ───────────────────────────────────────────────────────────────────


class TestPushActsOnTheStoreThePrefixNames:
    def test_it_updates_that_submodules_origin_projectman_branch(self, hub):
        from projectman.server import pm_commit, pm_push

        story(hub, "US-API-1", "api")
        commit = committed(pm_commit(prefix="API"))["commit_hash"]
        api_sub = subproject_path(hub, "api")
        assert ls_remote(api_sub, "refs/heads/projectman") != commit

        result = pushed(pm_push(prefix="API"))

        assert result["pushed"] is True
        assert result["branch"] == "projectman"
        assert result["worktree"] is True
        assert ls_remote(api_sub, "refs/heads/projectman") == commit

    def test_it_pushes_nothing_else(self, hub):
        from projectman.server import pm_commit, pm_push

        story(hub, "US-API-1", "api")
        story(hub, "US-WEB-1", "web")
        pm_commit(prefix="API")
        web_commit = committed(pm_commit(prefix="WEB"))["commit_hash"]
        web_sub = subproject_path(hub, "web")
        web_remote_before = ls_remote(web_sub, "refs/heads/projectman")

        pm_push(prefix="API")

        assert ls_remote(web_sub, "refs/heads/projectman") == web_remote_before
        assert ls_remote(web_sub, "refs/heads/projectman") != web_commit
        # The submodule's own main is not ProjectMan's business either.
        assert ls_remote(subproject_path(hub, "api"), "refs/heads/main") == out(
            "rev-parse", "origin/main", cwd=subproject_path(hub, "api")
        )

    def test_an_unknown_prefix_is_the_coded_not_found(self, hub):
        from mcp.server.fastmcp.exceptions import ToolError

        from projectman.server import pm_push

        with pytest.raises(ToolError) as excinfo:
            pm_push(prefix="NOPE")

        assert "[code: not_found]" in str(excinfo.value)

    def test_a_registered_but_unmounted_project_is_refused_with_the_hint(self, hub):
        """The store map's own answer, unchanged by the verb (US-PM-31-9)."""
        from mcp.server.fastmcp.exceptions import ToolError

        from conftest import make_unattached_hub_subproject
        from projectman.server import pm_push

        make_unattached_hub_subproject(hub, "copied", "COP")
        _reset_caches()

        with pytest.raises(ToolError) as excinfo:
            pm_push(prefix="COP")

        assert "not attached" in str(excinfo.value) or "no store mounted" in str(
            excinfo.value
        )
        assert "[code: not_found]" in str(excinfo.value)


# ─── Outside a hub the prefix is ignored ────────────────────────────────────


class TestSingleProjectModeIsUnchanged:
    """US-PM-34-5's rule, applied to the two git verbs: outside a hub there is
    one store, `prefix` is ignored outright, and a confused caller who passes
    one gets exactly the answer they would have got without it."""

    @pytest.fixture
    def project(self, tmp_git_project, monkeypatch):
        monkeypatch.chdir(tmp_git_project)
        _reset_caches()
        yield tmp_git_project
        _reset_caches()

    def test_a_prefix_is_ignored_by_commit(self, project):
        from projectman.server import pm_commit

        (project / ".project" / "stories" / "US-TST-1.md").write_text(
            "---\nid: US-TST-1\ntitle: A story\nstatus: backlog\n---\n\nBody.\n"
        )

        result = committed(pm_commit(prefix="NOT-A-PREFIX"))

        assert result["on_branch"] == "main"
        assert any(
            "US-TST-1.md" in line
            for line in out(
                "show", "--name-only", "--format=", result["commit_hash"], cwd=project
            ).splitlines()
        )

    def test_a_prefix_is_ignored_by_the_expected_negative_too(self, project):
        from projectman.server import pm_commit

        pm_commit()  # drain whatever the fixture left dirty

        with_prefix = yaml.safe_load(pm_commit(prefix="NOT-A-PREFIX"))
        without = yaml.safe_load(pm_commit())

        assert with_prefix == without
        assert with_prefix["status"] == "nothing_to_commit"

    def test_a_prefix_is_ignored_by_push(self, project, tmp_path):
        from projectman.server import pm_commit, pm_push

        bare = tmp_path / "plain-origin.git"
        git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
        git("remote", "add", "origin", str(bare), cwd=project)

        (project / ".project" / "stories" / "US-TST-1.md").write_text(
            "---\nid: US-TST-1\ntitle: A story\nstatus: backlog\n---\n\nBody.\n"
        )
        commit = committed(pm_commit())["commit_hash"]

        result = pushed(pm_push(prefix="NOT-A-PREFIX"))

        assert result["branch"] == "main"
        assert ls_remote(project, "refs/heads/main") == commit


# ─── The CLI takes the same prefix ──────────────────────────────────────────


class TestTheCliAddressesTheSameStore:
    def test_commit_and_push_prefix_move_only_that_subproject(self, hub):
        from click.testing import CliRunner

        from projectman.cli import cli

        story(hub, "US-API-1", "api")
        story(hub, "US-WEB-1", "web")
        runner = CliRunner()

        result = runner.invoke(cli, ["commit", "--prefix", "API"])
        assert result.exit_code == 0, result.output
        assert "Branch: projectman" in result.output

        api = store_path(hub, "api")
        result = runner.invoke(cli, ["push", "--prefix", "API"])
        assert result.exit_code == 0, result.output
        assert "Pushed projectman to origin" in result.output
        assert ls_remote(subproject_path(hub, "api"), "refs/heads/projectman") == head(api)

        assert "US-WEB-1.md" in porcelain(store_path(hub, "web"))

    def test_an_unknown_prefix_exits_non_zero(self, hub):
        from click.testing import CliRunner

        from projectman.cli import cli

        result = CliRunner().invoke(cli, ["commit", "--prefix", "NOPE"])

        assert result.exit_code == 1
        assert "NOPE" in result.output


def test_registry_commit_and_push_no_longer_take_a_scope():
    """The parameter is gone, not defaulted — nothing can pass `scope` again."""
    import inspect

    from projectman.hub import registry
    from projectman import cli as cli_module
    from projectman import server

    for fn in (registry.pm_commit, registry.pm_push, server.pm_commit, server.pm_push):
        assert "scope" not in inspect.signature(fn).parameters, fn

    for command in (cli_module.commit, cli_module.push):
        names = {param.name for param in command.params}
        assert "scope" not in names, command
        assert "prefix" in names, command


def test_the_removed_multi_store_helpers_are_gone():
    """US-PM-35-7 deletes what the fan-out needed; a leftover is dead code."""
    from projectman.hub import registry

    for name in (
        "_rebuild_indexes_for_scope",
        "_git_repo_key",
        "_changed_store_files",
        "_with_skips",
        "_push_store_branch",
    ):
        assert not hasattr(registry, name), name
