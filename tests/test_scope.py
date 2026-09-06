"""Tests that hub vs subproject scope is configurable.

Verifies acceptance criterion for US-PRJ-3:
  > Hub vs subproject scope is configurable

Covers:
- Store(root) defaults to hub-level .project/
- Store(root, project_dir=...) scopes to subproject
- _store_for_prefix('API') resolves the hub subproject correctly
- _store() and an omitted prefix use root scope
- Non-hub projects ignore the prefix
- pm_commit(prefix='API') only commits that subproject's store
- pm_commit() at hub level commits the hub's own store
"""

import subprocess

import pytest
import yaml

from projectman.store import Store
from conftest import make_hub_subproject



#: Every hub subproject in the suite is built by the one conftest factory
#: (US-PM-31-9), so ``projects/{name}/.project`` is spelled in exactly one
#: place and a later layout change is a single edit.
_register_subproject = make_hub_subproject


# ─── Store scope configuration ──────────────────────────────────


def test_store_default_scope_uses_root_project_dir(tmp_project):
    """Store(root) defaults project_dir to root/.project/."""
    s = Store(tmp_project)
    assert s.project_dir == tmp_project / ".project"
    assert s.config.hub is False


def test_store_hub_scope_uses_root_project_dir(tmp_hub):
    """Store(root) in hub mode defaults project_dir to root/.project/."""
    s = Store(tmp_hub)
    assert s.project_dir == tmp_hub / ".project"
    assert s.config.hub is True


def test_store_explicit_project_dir_scopes_to_subproject(tmp_hub):
    """Store(root, project_dir=...) uses the given directory as scope."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")
    s = Store(tmp_hub, project_dir=pm_dir)

    assert s.project_dir == pm_dir
    assert s.config.name == "api"
    assert s.config.hub is False


def test_store_scoped_operations_stay_in_subproject(tmp_hub):
    """Stories created via a scoped Store are written to the subproject directory."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")
    sub_store = Store(tmp_hub, project_dir=pm_dir)
    meta, _ = sub_store.create_story("API Auth", "Add login", points=3)

    # Story file lives under the subproject
    assert (pm_dir / "stories" / f"{meta.id}.md").exists()
    # NOT in the hub-level stories dir
    assert not (tmp_hub / ".project" / "stories" / f"{meta.id}.md").exists()


def test_store_hub_and_subproject_have_independent_id_sequences(tmp_hub):
    """Hub and subproject maintain separate story ID counters."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")

    hub_store = Store(tmp_hub)
    sub_store = Store(tmp_hub, project_dir=pm_dir)

    hub_meta, _ = hub_store.create_story("Hub Story", "Desc")
    sub_meta, _ = sub_store.create_story("API Story", "Desc")

    # Each uses its own prefix and counter
    assert hub_meta.id.startswith("US-HUB-")
    assert sub_meta.id.startswith("US-API-")


# ─── Server _store() routing ────────────────────────────────────


def test_resolve_store_with_prefix_in_hub_mode(tmp_hub, monkeypatch):
    """_store_for_prefix('API') returns a Store scoped to the subproject."""
    _register_subproject(tmp_hub, "api", prefix="API")
    monkeypatch.chdir(tmp_hub)

    from projectman.server import _store_for_prefix

    s = _store_for_prefix("API")
    expected = tmp_hub / "projects" / "api" / ".project"
    assert s.project_dir == expected


def test_resolve_store_without_project_param_uses_root(tmp_hub, monkeypatch):
    """_store() without project param returns a Store at root .project/."""
    monkeypatch.chdir(tmp_hub)
    from projectman.server import _store

    s = _store()
    assert s.project_dir == tmp_hub / ".project"


def test_prefix_is_ignored_when_not_a_hub(tmp_project, monkeypatch):
    """A prefix outside a hub does nothing at all — right or wrong (US-PM-34-5)."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_for_prefix

    # There is one store; the prefix is never even looked up.
    s = _store_for_prefix("NONEXISTENT")
    assert s.project_dir == tmp_project / ".project"


def test_resolve_store_unknown_prefix_raises_in_hub(tmp_hub, monkeypatch):
    """An unknown prefix is the coded not_found, listing what does exist."""
    from projectman.errors import NotFoundError
    from projectman.server import _store_for_prefix

    monkeypatch.chdir(tmp_hub)

    with pytest.raises(NotFoundError, match="MISSING") as exc:
        _store_for_prefix("MISSING")
    assert exc.value.code == "not_found"


# ─── pm_commit prefix ───────────────────────────────────────────


def test_pm_commit_hub_scoped_to_subproject(tmp_git_hub, monkeypatch):
    """pm_commit(prefix='API') only commits projects/api/.project/ changes."""
    _register_subproject(tmp_git_hub, "api", prefix="API")

    # Commit the subproject registration
    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register api"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, _store_for_prefix, pm_commit

    # Create a story in the subproject scope
    sub_store = _store_for_prefix("API")
    sub_store.create_story("API Story", "Desc", points=3)

    # Also create a hub-level story
    hub_store = _store()
    hub_store.create_story("Hub Story", "Desc", points=5)

    # Commit only the subproject
    result = pm_commit(prefix="API")
    data = yaml.safe_load(result)

    assert "committed" in data
    assert data["committed"]["files_committed"] > 0
    # All committed files should be under projects/api/.project/
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    files = [f for f in show.stdout.splitlines() if f.strip()]
    for f in files:
        assert "projects/api" in f, f"Expected subproject path, got: {f}"

    # Hub-level story should still be uncommitted
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", ".project/stories/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert status.stdout.strip(), "Hub story should still be unstaged/uncommitted"


def test_pm_commit_hub_level_commits_hub_changes(tmp_git_hub, monkeypatch):
    """pm_commit() at hub level commits the hub's own .project/ changes."""
    _register_subproject(tmp_git_hub, "api", prefix="API")

    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register api"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, _store_for_prefix, pm_commit

    # Create a hub-level story only
    hub_store = _store()
    hub_store.create_story("Hub Story", "Desc", points=5)

    result = pm_commit()
    data = yaml.safe_load(result)

    assert "committed" in data
    assert data["committed"]["files_committed"] > 0


def test_pm_commit_subproject_prefix_does_not_cross_contaminate(tmp_git_hub, monkeypatch):
    """Commits against two different subproject stores don't affect each other."""
    _register_subproject(tmp_git_hub, "api", prefix="API")
    _register_subproject(tmp_git_hub, "web", prefix="WEB")

    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register subs"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, _store_for_prefix, pm_commit

    # Create stories in both subprojects
    api_store = _store_for_prefix("API")
    api_store.create_story("API Story", "Desc", points=3)

    web_store = _store_for_prefix("WEB")
    web_store.create_story("Web Story", "Desc", points=5)

    # Commit only api
    result = pm_commit(prefix="API")
    data = yaml.safe_load(result)

    assert "committed" in data
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    for f in [f for f in show.stdout.splitlines() if f.strip()]:
        assert "projects/api" in f
        assert "projects/web" not in f

    # Web changes should still be uncommitted
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "projects/web/.project/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert status.stdout.strip(), "Web story should still be unstaged"
