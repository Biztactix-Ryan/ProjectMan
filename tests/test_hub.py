"""Tests for hub mode -- registry and rollup."""

import shutil
import subprocess

import pytest
import yaml
from pathlib import Path

from projectman.hub.registry import (
    list_projects, _init_subproject, _parse_github_repo,
    log_ref_update, REF_LOG_MAX_ENTRIES,
    pm_commit,
    _generate_hub_commit_message,
    pm_push,
)
from projectman.hub.rollup import rollup
from projectman.indexer import _discover_badges, write_markdown_indexes
from projectman.store import Store
from conftest import make_hub_subproject, make_legacy_hub_side_store


def test_list_projects_empty(tmp_hub):
    projects = list_projects(tmp_hub)
    assert projects == []


def test_rollup_empty(tmp_hub):
    data = rollup(tmp_hub)
    assert data["total_stories"] == 0
    assert data["total_points"] == 0


def test_rollup_with_subproject(tmp_hub):
    # The subproject's store lives inside its own checkout (US-PM-31).
    pm_dir = make_hub_subproject(tmp_hub, "sub1")

    # Create a story in subproject using hub root + project_dir
    sub_store = Store(tmp_hub, project_dir=pm_dir)
    sub_store.create_story("Sub Story", "Desc", points=3)

    # Rollup
    data = rollup(tmp_hub)
    assert data["total_stories"] == 1
    assert data["total_points"] == 3


# ─── Helper ──────────────────────────────────────────────────────



#: Every hub subproject in the suite is built by the one conftest factory
#: (US-PM-31-9), so ``projects/{name}/.project`` is spelled in exactly one
#: place and a later layout change is a single edit.
_register_subproject = make_hub_subproject


# ─── list_projects with new layout ──────────────────────────────


def test_list_projects_with_registered_projects(tmp_hub):
    """list_projects returns correct info for projects at new hub layout."""
    _register_subproject(tmp_hub, "api", prefix="API")

    projects = list_projects(tmp_hub)
    assert len(projects) == 1
    assert projects[0]["name"] == "api"
    assert projects[0]["exists"] is True
    assert projects[0]["initialized"] is True


def test_list_projects_missing_source_dir(tmp_hub):
    """Registered but the checkout is gone — and with it the store (US-PM-31).

    The PM data lives inside the checkout now, so losing the checkout loses
    the store: ``initialized`` follows ``exists`` rather than outliving it.
    """
    _register_subproject(tmp_hub, "gone")
    shutil.rmtree(tmp_hub / "projects" / "gone")

    projects = list_projects(tmp_hub)
    assert len(projects) == 1
    assert projects[0]["exists"] is False
    assert projects[0]["initialized"] is False


# ─── _init_subproject ────────────────────────────────────────────


def test_init_subproject_creates_structure(tmp_path):
    """_init_subproject creates config, stories/, tasks/, epics/ at target."""
    target = tmp_path / "pm_data" / "myproj"
    _init_subproject(target, "myproj")

    assert target.is_dir()
    assert (target / "config.yaml").exists()
    assert (target / "stories").is_dir()
    assert (target / "tasks").is_dir()
    assert (target / "epics").is_dir()
    assert (target / "index.yaml").exists()
    # ...and index.yaml is derived, so the subproject ignores it (US-PM-29-6).
    from projectman.indexer import DERIVED_INDEX_FILES

    ignored = (target / ".gitignore").read_text().splitlines()
    assert all(name in ignored for name in DERIVED_INDEX_FILES)

    with open(target / "config.yaml") as f:
        config = yaml.safe_load(f)
    assert config["name"] == "myproj"
    assert config["hub"] is False
    assert config["next_story_id"] == 1


def test_init_subproject_stores_repo(tmp_path):
    """_init_subproject writes repo field to config.yaml when provided."""
    target = tmp_path / "pm_data" / "api"
    _init_subproject(target, "api", repo="acme/api")

    with open(target / "config.yaml") as f:
        config = yaml.safe_load(f)
    assert config["repo"] == "acme/api"


# ─── _parse_github_repo ──────────────────────────────────────────


def test_parse_github_repo_https():
    assert _parse_github_repo("https://github.com/acme/api.git") == "acme/api"


def test_parse_github_repo_https_no_git():
    assert _parse_github_repo("https://github.com/acme/api") == "acme/api"


def test_parse_github_repo_https_trailing_slash():
    assert _parse_github_repo("https://github.com/acme/api/") == "acme/api"


def test_parse_github_repo_ssh():
    assert _parse_github_repo("git@github.com:acme/api.git") == "acme/api"


def test_parse_github_repo_ssh_no_git():
    assert _parse_github_repo("git@github.com:acme/api") == "acme/api"


def test_parse_github_repo_non_github():
    assert _parse_github_repo("https://gitlab.com/acme/api.git") == ""


def test_parse_github_repo_random_string():
    assert _parse_github_repo("not-a-url") == ""


# ─── rollup includes repo ────────────────────────────────────────


def test_rollup_includes_repo(tmp_hub):
    """rollup() per-project data includes the repo field from subproject config."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")

    # Write repo into the subproject config
    with open(pm_dir / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["repo"] = "acme/api"
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(cfg, f)

    data = rollup(tmp_hub)
    proj = next(p for p in data["projects"] if p["name"] == "api")
    assert proj["repo"] == "acme/api"


def test_rollup_repo_defaults_empty(tmp_hub):
    """rollup() returns empty repo when subproject config has no repo field."""
    _register_subproject(tmp_hub, "legacy", prefix="LEG")

    data = rollup(tmp_hub)
    proj = next(p for p in data["projects"] if p["name"] == "legacy")
    assert proj["repo"] == ""


# ─── _discover_badges ────────────────────────────────────────────


def test_discover_badges_no_repo(tmp_hub):
    """No badges when repo is empty."""
    assert _discover_badges(tmp_hub, "api", "") == []


def test_discover_badges_no_workflows_dir(tmp_hub):
    """No badges when .github/workflows/ doesn't exist."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    assert _discover_badges(tmp_hub, "api", "acme/api") == []


def test_discover_badges_with_workflows(tmp_hub):
    """Badges are generated from workflow YAML files."""
    wf_dir = tmp_hub / "projects" / "api" / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs: {}\n")
    (wf_dir / "deploy.yaml").write_text("name: Deploy\non: push\njobs: {}\n")

    badges = _discover_badges(tmp_hub, "api", "acme/api")
    assert len(badges) == 2
    assert "[![CI]" in badges[0]
    assert "acme/api" in badges[0]
    assert "ci.yml" in badges[0]
    assert "[![Deploy]" in badges[1]
    assert "deploy.yaml" in badges[1]


def test_discover_badges_falls_back_to_filename(tmp_hub):
    """When YAML has no name field, badge uses the file stem."""
    wf_dir = tmp_hub / "projects" / "api" / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "test.yml").write_text("on: push\njobs: {}\n")

    badges = _discover_badges(tmp_hub, "api", "acme/api")
    assert len(badges) == 1
    assert "[![test]" in badges[0]


def test_discover_badges_ignores_non_yaml(tmp_hub):
    """Non-YAML files in workflows dir are ignored."""
    wf_dir = tmp_hub / "projects" / "api" / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs: {}\n")
    (wf_dir / "README.md").write_text("# Workflows\n")

    badges = _discover_badges(tmp_hub, "api", "acme/api")
    assert len(badges) == 1


# ─── Hub README generation ───────────────────────────────────────


def test_hub_readme_has_per_project_sections(tmp_hub):
    """Hub README includes per-project stats tables."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")

    # Add a story with points
    sub_store = Store(tmp_hub, project_dir=pm_dir)
    sub_store.create_story("API Story", "Desc", points=5)

    # Generate hub indexes
    hub_store = Store(tmp_hub)
    write_markdown_indexes(hub_store)

    readme = (tmp_hub / "README.md").read_text()

    assert "### api" in readme
    assert "| Epics | Stories | Tasks | Points | Progress |" in readme
    assert "| Projects |" in readme
    assert "## Indexes" in readme


def test_hub_readme_includes_badges(tmp_hub):
    """Hub README includes GitHub Actions badges when workflows exist."""
    pm_dir = _register_subproject(tmp_hub, "web", prefix="WEB")

    # Set repo in subproject config
    with open(pm_dir / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["repo"] = "acme/web"
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(cfg, f)

    # Create a workflow file in the subproject source dir
    wf_dir = tmp_hub / "projects" / "web" / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "build.yml").write_text("name: build\non: push\njobs: {}\n")

    hub_store = Store(tmp_hub)
    write_markdown_indexes(hub_store)

    readme = (tmp_hub / "README.md").read_text()

    assert "[![build]" in readme
    assert "acme/web" in readme


def test_hub_readme_no_badges_without_repo(tmp_hub):
    """Hub README has no badges when subproject has no repo configured."""
    _register_subproject(tmp_hub, "cli", prefix="CLI")

    hub_store = Store(tmp_hub)
    write_markdown_indexes(hub_store)

    readme = (tmp_hub / "README.md").read_text()

    assert "### cli" in readme
    assert "[![" not in readme


def test_hub_readme_completion_percentage(tmp_hub):
    """Hub README shows aggregate completion percentage."""
    import frontmatter as fm

    pm_dir = _register_subproject(tmp_hub, "svc", prefix="SVC")

    sub_store = Store(tmp_hub, project_dir=pm_dir)
    meta_done, _ = sub_store.create_story("Done Story", "Desc", points=3)
    sub_store.create_story("Open Story", "Desc", points=5)

    # Manually set the first story to done
    story_path = pm_dir / "stories" / f"{meta_done.id}.md"
    post = fm.load(str(story_path))
    post.metadata["status"] = "done"
    story_path.write_text(fm.dumps(post))

    hub_store = Store(tmp_hub)
    write_markdown_indexes(hub_store)

    readme = (tmp_hub / "README.md").read_text()

    # 3 out of 8 points = 38%
    assert "| Completion | 38% |" in readme


# ─── log_ref_update ──────────────────────────────────────────────


def test_log_ref_update_creates_file(tmp_hub):
    """log_ref_update creates ref-log.yaml with a single entry."""
    log_ref_update("api", "aaa", "bbb", "sync", tmp_hub)

    log_path = tmp_hub / ".project" / "ref-log.yaml"
    assert log_path.exists()

    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == 1
    assert entries[0]["project"] == "api"
    assert entries[0]["old_ref"] == "aaa"
    assert entries[0]["new_ref"] == "bbb"
    assert entries[0]["source"] == "sync"
    assert "timestamp" in entries[0]


def test_log_ref_update_appends(tmp_hub):
    """Successive calls append to the log."""
    log_ref_update("api", "aaa", "bbb", "sync", tmp_hub)
    log_ref_update("web", "ccc", "ddd", "manual", tmp_hub, commit="abc123")

    entries = yaml.safe_load(
        (tmp_hub / ".project" / "ref-log.yaml").read_text()
    )
    assert len(entries) == 2
    assert entries[1]["project"] == "web"
    assert entries[1]["commit"] == "abc123"


def test_log_ref_update_optional_fields(tmp_hub):
    """author and commit are included only when provided."""
    log_ref_update("api", "a", "b", "manual", tmp_hub, author="dev-a", commit="sha1")

    entries = yaml.safe_load(
        (tmp_hub / ".project" / "ref-log.yaml").read_text()
    )
    assert entries[0]["author"] == "dev-a"
    assert entries[0]["commit"] == "sha1"


def test_log_ref_update_omits_empty_optional_fields(tmp_hub):
    """author and commit are omitted when not provided."""
    log_ref_update("api", "a", "b", "sync", tmp_hub)

    entries = yaml.safe_load(
        (tmp_hub / ".project" / "ref-log.yaml").read_text()
    )
    assert "author" not in entries[0]
    assert "commit" not in entries[0]


def test_log_ref_update_rotation(tmp_hub):
    """Entries beyond MAX are rotated to ref-log.archive.yaml."""
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    archive_path = tmp_hub / ".project" / "ref-log.archive.yaml"

    # Pre-fill with MAX entries
    seed = [
        {"timestamp": f"t{i}", "project": "api", "old_ref": "o", "new_ref": "n", "source": "seed"}
        for i in range(REF_LOG_MAX_ENTRIES)
    ]
    log_path.write_text(yaml.dump(seed, default_flow_style=False))

    # One more should trigger rotation
    log_ref_update("web", "x", "y", "manual", tmp_hub)

    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == REF_LOG_MAX_ENTRIES
    # The newest entry should be the last one
    assert entries[-1]["project"] == "web"

    # Archive should contain the overflow
    assert archive_path.exists()
    archived = yaml.safe_load(archive_path.read_text())
    assert len(archived) == 1
    assert archived[0]["timestamp"] == "t0"


def test_log_ref_update_archive_appends(tmp_hub):
    """Rotation appends to an existing archive file."""
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    archive_path = tmp_hub / ".project" / "ref-log.archive.yaml"

    # Pre-existing archive
    archive_path.write_text(yaml.dump([{"old": "entry"}], default_flow_style=False))

    # Fill log to trigger rotation
    seed = [
        {"timestamp": f"t{i}", "project": "api", "old_ref": "o", "new_ref": "n", "source": "seed"}
        for i in range(REF_LOG_MAX_ENTRIES)
    ]
    log_path.write_text(yaml.dump(seed, default_flow_style=False))

    log_ref_update("api", "x", "y", "sync", tmp_hub)

    archived = yaml.safe_load(archive_path.read_text())
    assert len(archived) == 2  # 1 pre-existing + 1 rotated
    assert archived[0]["old"] == "entry"


# ─── pm_commit ───────────────────────────────────────────────────
#
# US-PM-35-7: pm_commit acts on the *one* store it is handed — the hub's own
# or a subproject's — and never on a set of them.  The prefix that picks the
# store is resolved by the caller (``server.pm_commit``, ``projectman
# commit``); these test what the registry does once it has one.


def _hub_store(root):
    return root / ".project"


def test_pm_commit_commits_the_store_it_is_given(tmp_git_hub):
    """The hub's own store commits its own changed files."""
    stories_dir = tmp_git_hub / ".project" / "stories"
    (stories_dir / "US-HUB-1.md").write_text("---\ntitle: Test\nstatus: backlog\n---\nBody\n")

    result = pm_commit(_hub_store(tmp_git_hub))

    assert "commit_hash" in result
    assert result["message"].startswith("pm: ")
    assert len(result["files_committed"]) > 0
    assert any("US-HUB-1" in f for f in result["files_committed"])


def test_pm_commit_on_the_hub_store_excludes_subproject_files(tmp_git_hub):
    """A subproject store is a different store; the hub's commit cannot see it."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nHub body\n"
    )
    sub_dir = make_hub_subproject(tmp_git_hub, "api", prefix="API")
    (sub_dir / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )

    result = pm_commit(_hub_store(tmp_git_hub))

    assert "commit_hash" in result
    assert any("US-HUB-1" in f for f in result["files_committed"])
    assert not any("US-API-1" in f for f in result["files_committed"])
    assert not any("projects/api" in f for f in result["files_committed"])


def test_pm_commit_on_a_subproject_store_commits_only_that_store(tmp_git_hub):
    """The mirror image: naming the subproject store leaves the hub's alone."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nHub body\n"
    )
    sub_dir = make_hub_subproject(tmp_git_hub, "api", prefix="API")
    (sub_dir / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )

    result = pm_commit(sub_dir)

    assert "commit_hash" in result
    assert any("US-API-1" in f for f in result["files_committed"])
    assert not any("US-HUB-1" in f for f in result["files_committed"])


def test_pm_commit_nothing_to_commit(tmp_git_hub):
    """pm_commit returns nothing_to_commit when no .project/ files changed."""
    result = pm_commit(_hub_store(tmp_git_hub))
    assert result == {"nothing_to_commit": True}


def test_pm_commit_nothing_to_commit_for_a_clean_subproject(tmp_git_hub):
    """A store with nothing of its own is the expected negative, not the hub's changes."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nBody\n"
    )
    sub_dir = tmp_git_hub / "projects" / "api" / ".project"
    sub_dir.mkdir(parents=True)

    assert pm_commit(sub_dir) == {"nothing_to_commit": True}


def test_pm_commit_custom_message(tmp_git_hub):
    """pm_commit uses a provided message instead of auto-generating."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Test\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(_hub_store(tmp_git_hub), message="custom: my msg")

    assert result["message"] == "custom: my msg"


def test_pm_commit_auto_message_lists_ids(tmp_git_hub):
    """Auto-generated message lists individual IDs when few files changed."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-5.md").write_text(
        "---\ntitle: Five\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(_hub_store(tmp_git_hub))

    assert "US-HUB-5" in result["message"]


def test_pm_commit_no_store_dir(tmp_path):
    """pm_commit raises the coded not_found when the store isn't there."""
    from projectman.errors import NotFoundError

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True, check=True)

    with pytest.raises(NotFoundError, match=".project") as exc:
        pm_commit(tmp_path / ".project")
    assert exc.value.code == "not_found"


def test_generate_hub_commit_message_few_ids():
    """Message lists IDs when 4 or fewer files changed."""
    files = [
        ".project/stories/US-PRJ-5.md",
        ".project/tasks/US-PRJ-5-1.md",
    ]
    msg = _generate_hub_commit_message(files)
    assert msg == "pm: update US-PRJ-5, US-PRJ-5-1"


def test_generate_hub_commit_message_many_ids():
    """Message uses count summaries when more than 4 IDs."""
    files = [
        ".project/stories/US-PRJ-1.md",
        ".project/stories/US-PRJ-2.md",
        ".project/stories/US-PRJ-3.md",
        ".project/tasks/US-PRJ-1-1.md",
        ".project/tasks/US-PRJ-2-1.md",
    ]
    msg = _generate_hub_commit_message(files)
    assert "3 stories" in msg
    assert "2 tasks" in msg


def test_generate_hub_commit_message_config_only():
    """Message mentions config when only config files changed."""
    files = [".project/config.yaml"]
    msg = _generate_hub_commit_message(files)
    assert msg == "pm: update config"


def test_pm_commit_ignores_non_project_files(tmp_git_hub):
    """pm_commit never touches files outside the store — src/ changes stay unstaged."""
    src_dir = tmp_git_hub / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello')\n")

    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Test\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(_hub_store(tmp_git_hub))

    assert "commit_hash" in result
    for f in result["files_committed"]:
        assert f.startswith(".project/"), f"Non-.project file committed: {f}"
    assert not any("src/" in f for f in result["files_committed"])

    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "src/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert "src/main.py" in status.stdout


def test_pm_commit_leaves_the_other_subproject_uncommitted(tmp_git_hub):
    """Two subprojects, one named: the other's story is still uncommitted."""
    api = make_hub_subproject(tmp_git_hub, "api", prefix="API")
    web = make_hub_subproject(tmp_git_hub, "web", prefix="WEB")

    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register subs"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    (api / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )
    (web / "stories" / "US-WEB-1.md").write_text(
        "---\ntitle: Web story\nstatus: backlog\n---\nWeb body\n"
    )

    result = pm_commit(api)

    assert any("projects/api" in f for f in result["files_committed"])
    assert not any("projects/web" in f for f in result["files_committed"])

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "projects/web/.project/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert status.stdout.strip(), "Web story should still be uncommitted"


# ─── pm_push ──────────────────────────────────────────────────────
#
# The push against real repos with real bare remotes lives in
# tests/test_hub_commit_push_prefix.py and tests/test_worktree_git_ops.py;
# what belongs here is the refusal that needs no remote at all.


def test_pm_push_refuses_a_store_that_is_not_there(tmp_git_hub):
    """An unmounted store has no branch to push — coded not_found."""
    from projectman.errors import NotFoundError

    with pytest.raises(NotFoundError, match="nothing to push") as exc:
        pm_push(tmp_git_hub / "projects" / "ghost" / ".project")
    assert exc.value.code == "not_found"


def test_pm_push_refuses_a_store_with_no_remote(tmp_git_hub):
    """tmp_git_hub has no origin, so there is nothing to push to — coded store."""
    from projectman.errors import StoreError

    with pytest.raises(StoreError, match="not configured") as exc:
        pm_push(_hub_store(tmp_git_hub))
    assert exc.value.code == "store"
