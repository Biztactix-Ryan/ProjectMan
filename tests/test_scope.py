"""Tests that hub vs subproject scope is configurable.

Verifies acceptance criterion for US-PRJ-3:
  > Hub vs subproject scope is configurable

Covers:
- Store(root) defaults to hub-level .project/
- Store(root, project_dir=...) scopes to subproject
- _store(project='x') resolves hub subproject correctly
- _store() without project uses root scope
- Non-hub projects reject the project parameter
- pm_commit(scope='project:x') only commits subproject changes
- pm_commit(scope='hub') at hub level commits hub changes
"""

import subprocess

import pytest
import yaml

from projectman.store import Store


def _register_subproject(hub_root, name, prefix="SUB"):
    """Set up a subproject with source dir, PM data dir, and hub config entry."""
    sub_path = hub_root / "projects" / name
    sub_path.mkdir(parents=True, exist_ok=True)

    pm_dir = hub_root / ".project" / "projects" / name
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "stories").mkdir(exist_ok=True)
    (pm_dir / "tasks").mkdir(exist_ok=True)
    (pm_dir / "epics").mkdir(exist_ok=True)

    config = {
        "name": name,
        "prefix": prefix,
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    from projectman.config import load_config, save_config
    hub_config = load_config(hub_root)
    if name not in hub_config.projects:
        hub_config.projects.append(name)
        save_config(hub_config, hub_root)

    return pm_dir


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


def test_resolve_store_with_project_param_in_hub_mode(tmp_hub, monkeypatch):
    """_store(project='api') returns a Store scoped to the subproject."""
    _register_subproject(tmp_hub, "api", prefix="API")
    monkeypatch.chdir(tmp_hub)

    from projectman.server import _store

    s = _store(project="api")
    expected = tmp_hub / ".project" / "projects" / "api"
    assert s.project_dir == expected


def test_resolve_store_without_project_param_uses_root(tmp_hub, monkeypatch):
    """_store() without project param returns a Store at root .project/."""
    monkeypatch.chdir(tmp_hub)
    from projectman.server import _store

    s = _store()
    assert s.project_dir == tmp_hub / ".project"


def test_resolve_store_project_param_rejected_when_not_hub(tmp_project, monkeypatch):
    """_store(project='x') returns root Store in non-hub mode (project param ignored)."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store

    # In non-hub mode the `project` param is only checked when config.hub is True.
    # When hub=False, _store falls through to the default Store(root).
    s = _store(project="nonexistent")
    assert s.project_dir == tmp_project / ".project"


def test_resolve_store_unknown_project_raises_in_hub(tmp_hub, monkeypatch):
    """_store(project='missing') raises FileNotFoundError in hub mode."""
    monkeypatch.chdir(tmp_hub)
    from projectman.server import _store

    with pytest.raises(FileNotFoundError, match="not found in hub"):
        _store(project="missing")


# ─── pm_commit scope ────────────────────────────────────────────


def test_pm_commit_hub_scoped_to_subproject(tmp_git_hub, monkeypatch):
    """pm_commit(scope='project:api') only commits subproject .project/projects/api/ changes."""
    _register_subproject(tmp_git_hub, "api", prefix="API")

    # Commit the subproject registration
    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register api"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, pm_commit

    # Create a story in the subproject scope
    sub_store = _store(project="api")
    sub_store.create_story("API Story", "Desc", points=3)

    # Also create a hub-level story
    hub_store = _store()
    hub_store.create_story("Hub Story", "Desc", points=5)

    # Commit only the subproject
    result = pm_commit(scope="project:api")
    data = yaml.safe_load(result)

    assert "committed" in data
    files = data["committed"]["files_committed"]
    # All committed files should be under .project/projects/api/
    for f in files:
        assert "projects/api" in f, f"Expected subproject path, got: {f}"

    # Hub-level story should still be uncommitted
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", ".project/stories/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert status.stdout.strip(), "Hub story should still be unstaged/uncommitted"


def test_pm_commit_hub_level_commits_hub_changes(tmp_git_hub, monkeypatch):
    """pm_commit(scope='hub') at hub level commits hub .project/ changes."""
    _register_subproject(tmp_git_hub, "api", prefix="API")

    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register api"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, pm_commit

    # Create a hub-level story only
    hub_store = _store()
    hub_store.create_story("Hub Story", "Desc", points=5)

    result = pm_commit(scope="hub")
    data = yaml.safe_load(result)

    assert "committed" in data
    assert len(data["committed"]["files_committed"]) > 0


def test_pm_commit_subproject_scope_does_not_cross_contaminate(tmp_git_hub, monkeypatch):
    """Commits in two different subproject scopes don't affect each other."""
    _register_subproject(tmp_git_hub, "api", prefix="API")
    _register_subproject(tmp_git_hub, "web", prefix="WEB")

    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register subs"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    monkeypatch.chdir(tmp_git_hub)
    from projectman.server import _store, pm_commit

    # Create stories in both subprojects
    api_store = _store(project="api")
    api_store.create_story("API Story", "Desc", points=3)

    web_store = _store(project="web")
    web_store.create_story("Web Story", "Desc", points=5)

    # Commit only api
    result = pm_commit(scope="project:api")
    data = yaml.safe_load(result)

    assert "committed" in data
    for f in data["committed"]["files_committed"]:
        assert "projects/api" in f
        assert "projects/web" not in f

    # Web changes should still be uncommitted
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", ".project/projects/web/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert status.stdout.strip(), "Web story should still be unstaged"
