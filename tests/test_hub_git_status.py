"""`pm_git_status` in a hub reports each subproject's **store**, not its code.

US-PM-35 criterion (task US-PM-35-8, verified by US-PM-35-3):

    > pm_git_status in a hub reports each subproject store's branch and dirty
    > and ahead-behind state through the worktree helpers

The hub is a read-only rollup.  What it can honestly say about a repo it does
not own is what that repo's `projectman` branch says: which branch owns the
PM store, whether that store has uncommitted changes, how far it has drifted
from its own origin, and when it last changed.  The submodule's checked-out
*code* branch rides along as a second column because it is a different fact —
conflating the two is exactly what the deleted deploy-branch alignment
scoring did, and it is why a hub used to report "not on deploy branch main"
about a store that was perfectly healthy on `projectman`.

Everything here runs against real git repositories under `tmp_path` — a bare
origin per subproject, a real `git submodule add`, and stores that are real
worktrees of each submodule's `projectman` branch — because "which branch
owns this store" cannot be answered by a mock of `subprocess.run`.  The
fixture is the one `tests/test_hub_commit_push_prefix.py` (US-PM-35-7) built,
whose `_sub_origin` is reused here so a subproject remote is spelled once.

Two environment details keep it hermetic: `protocol.file.allow=always` (git
refuses to clone a submodule over the `file` transport by default) and a git
identity in the environment, since commits happen inside freshly cloned
submodules with no local identity.
"""

from pathlib import Path

import pytest
import yaml

from projectman import worktree
from projectman.hub import registry
from projectman.hub.registry import format_git_status, git_status_all
from projectman.hub.stores import store_path, subproject_path
from projectman.store import clear_all_caches

from test_migrate_worktree import git, out
from test_hub_commit_push_prefix import _sub_origin


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


@pytest.fixture
def hub(tmp_git_hub, tmp_path_factory, monkeypatch):
    """A real hub with two attached subproject stores, API and WEB."""
    from projectman.hub.registry import add_project

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


def rows(root: Path) -> dict[str, dict]:
    """`git_status_all` rows by project name."""
    return {p["name"]: p for p in git_status_all(root=root)["projects"]}


def story(root: Path, story_id: str, name: str) -> Path:
    """Write a story into one subproject's store."""
    path = store_path(root, name) / "stories" / f"{story_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {story_id}\ntitle: A story\nstatus: backlog\n---\n\nBody.\n")
    return path


def commit_store(root: Path, name: str, message: str = "pm: a story") -> None:
    store = store_path(root, name)
    git("add", "-A", cwd=store)
    git("commit", "-m", message, cwd=store)


def unmount(root: Path, name: str) -> None:
    """Remove the store worktree the way a `git clean -ffdx` would."""
    git("worktree", "remove", "--force", ".project", cwd=subproject_path(root, name))
    assert not store_path(root, name).exists()
    _reset_caches()


# ─── The row is the store's state ───────────────────────────────────────────


class TestEachRowComesFromTheStore:
    def test_the_branch_reported_is_the_stores_not_the_checkouts(self, hub):
        api = rows(hub)["api"]

        assert api["attached"] is True
        assert api["worktree"] is True
        assert api["branch"] == "projectman"
        # The submodule's own code branch is a separate column, not the branch.
        assert api["checkout_branch"] == "main"
        assert out("rev-parse", "--abbrev-ref", "HEAD", cwd=subproject_path(hub, "api")) == "main"
        assert api["prefix"] == "API"

    def test_every_registered_project_gets_a_row_in_hub_order(self, hub):
        data = git_status_all(root=hub)

        assert [p["name"] for p in data["projects"]] == ["api", "web"]
        assert data["total"] == 2
        assert data["ok"] is True
        assert data["issues"] == 0
        assert data["pm_store"]["path"] == ".project"

    def test_an_unpushed_store_commit_shows_as_ahead(self, hub):
        story(hub, "US-API-1", "api")
        commit_store(hub, "api")

        api, web = rows(hub)["api"], rows(hub)["web"]

        assert api["ahead"] == 1 and api["behind"] == 0
        assert api["upstream"] == "origin/projectman"
        # One project's drift is never another's.
        assert (web["ahead"], web["behind"]) == (0, 0)
        assert git_status_all(root=hub)["ok"] is True  # ahead is not an issue

    def test_a_behind_store_is_an_issue(self, hub):
        # Advance origin/projectman behind the hub's back, then fetch.
        store = store_path(hub, "api")
        story(hub, "US-API-2", "api")
        commit_store(hub, "api", "pm: pushed elsewhere")
        git("push", "origin", "projectman", cwd=store)
        git("reset", "--hard", "HEAD~1", cwd=store)
        git("fetch", "origin", cwd=store)

        api = rows(hub)["api"]

        assert api["behind"] == 1 and api["ahead"] == 0
        assert any("behind" in issue for issue in api["issues"])
        assert git_status_all(root=hub)["ok"] is False

    def test_dirty_counts_the_store_only_never_the_code_checkout(self, hub):
        story(hub, "US-API-1", "api")
        (subproject_path(hub, "api") / "untracked.py").write_text("x = 1\n")

        api = rows(hub)["api"]

        assert api["dirty"] is True
        assert api["dirty_count"] == 1  # the story, not the stray .py
        assert api["issues"] == ["Store has 1 uncommitted file"]
        assert rows(hub)["web"]["dirty"] is False

    def test_last_commit_is_the_stores_last_pm_change(self, hub):
        story(hub, "US-API-1", "api")
        commit_store(hub, "api", "pm: US-API-1")

        api = rows(hub)["api"]

        assert api["last_commit"]["message"] == "pm: US-API-1"
        assert api["last_commit"]["sha"] == out("rev-parse", "HEAD", cwd=store_path(hub, "api"))
        # The web store never moved, so its last commit is the scaffolded one.
        assert rows(hub)["web"]["last_commit"]["message"] == "PM store"

    def test_the_dropped_alignment_fields_are_gone_from_every_row(self, hub):
        for row in git_status_all(root=hub)["projects"]:
            assert "aligned" not in row
            assert "deploy_branch" not in row
            assert "branch_ok" not in row
            assert "tracking_branch" not in row


# ─── Unattached and missing subprojects ─────────────────────────────────────


class TestAnUnattachedStoreIsARowNotAnError:
    def test_a_removed_worktree_reports_the_attach_hint(self, hub):
        unmount(hub, "api")

        api = rows(hub)["api"]

        assert api["attached"] is False
        assert api["exists"] is True
        assert api["status"] == "not attached"
        assert "projects/api/.project" in api["hint"]
        assert "migrate-hub" in api["hint"] and "add-project" in api["hint"]
        assert api["branch"] == ""
        assert api["checkout_branch"] == "main"
        assert api["issues"] == [api["hint"]]

    def test_it_is_an_issue_but_does_not_stop_the_other_projects(self, hub):
        unmount(hub, "api")

        data = git_status_all(root=hub)

        assert data["ok"] is False and data["issues"] == 1
        assert data["total"] == 2
        assert rows(hub)["web"]["branch"] == "projectman"

    def test_a_missing_project_directory_is_a_row_too(self, hub):
        import shutil

        shutil.rmtree(subproject_path(hub, "api"))
        _reset_caches()

        api = rows(hub)["api"]

        assert api["exists"] is False and api["attached"] is False
        assert api["issues"] == ["Project directory missing"]
        assert api["checkout_branch"] == ""
        assert git_status_all(root=hub)["issues"] == 1


# ─── Rendering ──────────────────────────────────────────────────────────────


class TestFormatGitStatus:
    def test_the_table_has_a_store_branch_and_a_checkout_column(self, hub):
        text = format_git_status(git_status_all(root=hub))

        assert text.splitlines()[0] == "Hub Git Status (2 projects)"
        assert "Store branch" in text and "Checkout" in text
        assert "Deploy" not in text
        api_line = next(line for line in text.splitlines() if line.strip().startswith("api"))
        assert "projectman" in api_line and "main" in api_line
        assert text.strip().endswith("All 2 projects clean.")

    def test_rows_stay_in_hub_order(self, hub):
        story(hub, "US-WEB-1", "web")  # would have sorted first under severity

        listed = [
            line.split()[0]
            for line in format_git_status(git_status_all(root=hub)).splitlines()
            if line.startswith("  ") and line.split() and line.split()[0] in ("api", "web")
        ]

        assert listed == ["api", "web"]

    def test_an_unattached_store_says_so_in_the_table(self, hub):
        unmount(hub, "api")

        text = format_git_status(git_status_all(root=hub), verbose=True)

        api_line = next(line for line in text.splitlines() if line.strip().startswith("api"))
        assert "not attached" in api_line
        assert "1 issue found" in text


# ─── The MCP surface ────────────────────────────────────────────────────────


class TestPmGitStatusPrefixFilter:
    def test_a_prefix_narrows_the_dashboard_to_one_store(self, hub):
        from projectman.server import pm_git_status

        data = yaml.safe_load(pm_git_status(prefix="API"))

        assert data["total"] == 1
        assert [p["name"] for p in data["projects"]] == ["api"]
        assert data["projects"][0]["branch"] == "projectman"
        assert data["summary"] == "Status for api"
        assert data["pm_store"]["path"] == ".project"

    def test_no_prefix_reports_every_subproject(self, hub):
        from projectman.server import pm_git_status

        data = yaml.safe_load(pm_git_status())

        assert data["total"] == 2
        assert [p["name"] for p in data["projects"]] == ["api", "web"]

    def test_an_unattached_store_is_reported_by_the_whole_dashboard(self, hub):
        from projectman.server import pm_git_status

        unmount(hub, "api")

        data = yaml.safe_load(pm_git_status())

        api = next(p for p in data["projects"] if p["name"] == "api")
        assert api["attached"] is False and api["status"] == "not attached"

    def test_an_unknown_prefix_is_not_found(self, hub):
        from projectman.errors import NotFoundError
        from projectman.server import pm_git_status

        with pytest.raises((NotFoundError, Exception)) as exc:
            pm_git_status(prefix="NOPE")
        assert "NOPE" in str(exc.value)


# ─── Scale, and the copied-store case ───────────────────────────────────────


class TestManySubprojects:
    """The parallel collection at hub scale, on the cheap plain-directory
    fixture: 25 registered projects, one row each, in order, no crash.

    A store copied into a real checkout rather than mounted is the case
    ``projectman migrate-hub`` exists to fix (US-PM-31-8), and the dashboard
    has to report it as a row like any other unattached store.
    """

    def test_twenty_five_projects_each_get_their_own_row(self, tmp_hub):
        from conftest import make_hub_subproject

        names = [f"proj-{i:02d}" for i in range(25)]
        for i, name in enumerate(names):
            make_hub_subproject(tmp_hub, name, prefix=f"P{i:02d}")

        data = git_status_all(root=tmp_hub)

        assert [p["name"] for p in data["projects"]] == names
        assert data["total"] == 25
        assert all(p["attached"] for p in data["projects"])
        assert data["ok"] is True
        assert format_git_status(data).splitlines()[0] == "Hub Git Status (25 projects)"

    def test_a_copied_store_inside_a_real_checkout_reads_as_not_attached(self, tmp_hub):
        from conftest import make_hub_subproject

        make_hub_subproject(tmp_hub, "copied", prefix="CPY", attached=False)
        make_hub_subproject(tmp_hub, "mounted", prefix="MNT")

        by_name = rows(tmp_hub)

        assert by_name["copied"]["attached"] is False
        assert by_name["copied"]["status"] == "not attached"
        assert "migrate-hub" in by_name["copied"]["hint"]
        assert by_name["mounted"]["attached"] is True
        assert git_status_all(root=tmp_hub)["issues"] == 1


# ─── The helper the rows come from ──────────────────────────────────────────


def test_the_row_matches_store_git_state_directly(hub):
    """No second implementation: the row *is* what the worktree helper says."""
    story(hub, "US-API-1", "api")
    commit_store(hub, "api")

    state = worktree.store_git_state(subproject_path(hub, "api"), ".project")
    row = rows(hub)["api"]

    for key in ("branch", "worktree", "detached", "upstream", "dirty", "dirty_count", "ahead", "behind"):
        assert row[key] == state[key], key
    assert registry._collect_project_status("api", hub)["branch"] == state["branch"]
