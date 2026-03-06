"""Tests for hub mode -- registry and rollup."""

import shutil
import subprocess

import pytest
import yaml
from pathlib import Path

from projectman.hub.registry import (
    list_projects, repair, _init_subproject, _parse_github_repo,
    log_ref_update, REF_LOG_MAX_ENTRIES,
    hub_push_with_rebase, _analyze_remote_changes, _classify_rebase_conflict,
    check_ref_fast_forward, _get_conflicting_submodule_refs,
    _resolve_submodule_ref_conflict,
    validate_branches,
    format_branch_validation,
    sync,
    pm_commit,
    _generate_hub_commit_message,
    pm_push,
    _push_subproject,
    push_preflight,
    _has_staged_changes,
    _remote_reachable,
)
from projectman.hub.rollup import rollup
from projectman.indexer import _discover_badges, write_markdown_indexes
from projectman.store import Store


def test_list_projects_empty(tmp_hub):
    projects = list_projects(tmp_hub)
    assert projects == []


def test_rollup_empty(tmp_hub):
    data = rollup(tmp_hub)
    assert data["total_stories"] == 0
    assert data["total_points"] == 0


def test_rollup_with_subproject(tmp_hub):
    # Manually create a subproject's source dir and PM data in hub
    sub_path = tmp_hub / "projects" / "sub1"
    sub_path.mkdir(parents=True)

    pm_dir = tmp_hub / ".project" / "projects" / "sub1"
    pm_dir.mkdir(parents=True)
    (pm_dir / "stories").mkdir()
    (pm_dir / "tasks").mkdir()

    config = {
        "name": "sub1",
        "prefix": "SUB",
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Register in hub config
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("sub1")
    save_config(hub_config, tmp_hub)

    # Create a story in subproject using hub root + project_dir
    sub_store = Store(tmp_hub, project_dir=pm_dir)
    sub_store.create_story("Sub Story", "Desc", points=3)

    # Rollup
    data = rollup(tmp_hub)
    assert data["total_stories"] == 1
    assert data["total_points"] == 3


# ─── Helper ──────────────────────────────────────────────────────


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
    """Project registered but source dir deleted -- exists=False, initialized=True."""
    _register_subproject(tmp_hub, "gone")
    # Remove the source directory but keep PM data
    shutil.rmtree(tmp_hub / "projects" / "gone")

    projects = list_projects(tmp_hub)
    assert len(projects) == 1
    assert projects[0]["exists"] is False
    assert projects[0]["initialized"] is True


# ─── Migration path in repair() ─────────────────────────────────


def test_repair_migrates_old_style_data(tmp_hub):
    """repair() moves PM data from projects/{name}/.project/ to hub .project/projects/{name}/."""
    from projectman.config import load_config, save_config

    # Register a project in the hub config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("legacy")
    save_config(hub_config, tmp_hub)

    # Create old-style layout: projects/legacy/.project/ with config + a story
    sub_path = tmp_hub / "projects" / "legacy"
    old_pm = sub_path / ".project"
    old_pm.mkdir(parents=True)
    (old_pm / "stories").mkdir()
    (old_pm / "tasks").mkdir()

    old_config = {
        "name": "legacy",
        "prefix": "LEG",
        "description": "",
        "hub": False,
        "next_story_id": 2,
        "projects": [],
    }
    with open(old_pm / "config.yaml", "w") as f:
        yaml.dump(old_config, f)
    (old_pm / "stories" / "US-LEG-1.md").write_text(
        "---\nid: US-LEG-1\ntitle: Old Story\nstatus: backlog\n"
        "priority: should\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\nOld story body\n"
    )

    # New-style PM dir should NOT exist yet
    new_pm = tmp_hub / ".project" / "projects" / "legacy"
    assert not (new_pm / "config.yaml").exists()

    # Run repair
    report = repair(tmp_hub)

    # Migration should have happened
    assert "migrated PM data" in report
    assert (new_pm / "config.yaml").exists()
    assert (new_pm / "stories" / "US-LEG-1.md").exists()

    # Verify migrated config is intact
    with open(new_pm / "config.yaml") as f:
        migrated = yaml.safe_load(f)
    assert migrated["prefix"] == "LEG"
    assert migrated["next_story_id"] == 2


def test_repair_discovers_unregistered_projects(tmp_hub):
    """repair() auto-registers directories in projects/ not in hub config."""
    # Create a project dir that is NOT in the hub config
    (tmp_hub / "projects" / "new-thing").mkdir(parents=True)

    report = repair(tmp_hub)

    assert "new-thing" in report
    assert "Discovered" in report

    # Verify it was registered
    from projectman.config import load_config
    hub_config = load_config(tmp_hub)
    assert "new-thing" in hub_config.projects


def test_repair_initializes_pm_data_for_new_projects(tmp_hub):
    """repair() creates PM data structure at hub .project/projects/{name}/."""
    (tmp_hub / "projects" / "fresh").mkdir(parents=True)

    repair(tmp_hub)

    pm_dir = tmp_hub / ".project" / "projects" / "fresh"
    assert (pm_dir / "config.yaml").exists()
    assert (pm_dir / "stories").is_dir()
    assert (pm_dir / "tasks").is_dir()


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
    log_ref_update("web", "ccc", "ddd", "changeset", tmp_hub, commit="abc123")

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
    log_ref_update("web", "x", "y", "changeset", tmp_hub)

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


# ─── hub_push_with_rebase ────────────────────────────────────────

from unittest.mock import patch, MagicMock


def _make_run_result(returncode=0, stdout="", stderr=""):
    """Build a CompletedProcess-like object."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _git_dispatcher(responses):
    """Return a side_effect callable that dispatches on the git subcommand.

    ``responses`` maps a git subcommand (e.g. "push", "fetch") to either:
      - a CompletedProcess-like object (returned every time), or
      - a list of such objects (popped in order, last one repeats).

    For ``check=True`` calls, a non-zero returncode raises CalledProcessError.
    """
    # track call counts per subcommand
    counters: dict[str, int] = {}

    def side_effect(cmd, **kwargs):
        # Determine the git subcommand
        sub = None
        for i, part in enumerate(cmd):
            if part == "git" or part.endswith("/git"):
                if i + 1 < len(cmd):
                    sub = cmd[i + 1]
                break

        if sub and sub in responses:
            val = responses[sub]
            if isinstance(val, list):
                idx = counters.get(sub, 0)
                counters[sub] = idx + 1
                result = val[min(idx, len(val) - 1)]
            else:
                result = val
        else:
            result = _make_run_result()

        if kwargs.get("check") and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd,
                output=result.stdout, stderr=result.stderr,
            )
        return result

    return side_effect


def test_hub_push_with_rebase_not_a_hub(tmp_project):
    """Returns error for non-hub projects."""
    result = hub_push_with_rebase(root=tmp_project)
    assert result["pushed"] is False
    assert result["error"] == "not a hub project"


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_succeeds_first_try(mock_run, tmp_hub):
    """Push succeeds on first attempt — no rebase needed."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result == {"pushed": True, "retries": 0, "rebased": False, "error": None}


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_non_conflict_error(mock_run, tmp_hub):
    """Push fails for a non-conflict reason (e.g. auth)."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="Permission denied"),
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is False
    assert "Permission denied" in result["error"]
    assert result["rebased"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_conflict_then_success(mock_run, tmp_hub):
    """Push rejected, rebase succeeds, second push succeeds."""
    mock_run.side_effect = _git_dispatcher({
        "push": [
            _make_run_result(1, stderr="rejected non-fast-forward"),
            _make_run_result(0),  # second push succeeds
        ],
        "fetch": _make_run_result(0),
        "diff": _make_run_result(0, stdout="projects/api\n"),
        "rebase": _make_run_result(0),
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result == {"pushed": True, "retries": 1, "rebased": True, "error": None}


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_fetch_fails(mock_run, tmp_hub):
    """Push rejected but fetch fails — returns fetch error."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="rejected non-fast-forward"),
        "fetch": _make_run_result(1, stderr="Could not resolve host"),
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is False
    assert "fetch failed" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_conflict_project_files(mock_run, tmp_hub):
    """Rebase fails with .project/ file conflicts."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="rejected non-fast-forward"),
        "fetch": _make_run_result(0),
        "diff": [
            # First call: _analyze_remote_changes
            _make_run_result(0, stdout=".project/index.yaml\nprojects/api\n"),
            # Second call: _classify_rebase_conflict
            _make_run_result(0, stdout=".project/index.yaml\n"),
        ],
        "rebase": [
            _make_run_result(1, stderr="CONFLICT"),  # rebase fails
            _make_run_result(0),  # --abort succeeds (subcommand still "rebase")
        ],
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is False
    assert "manual resolution required" in result["error"]
    assert ".project/" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_conflict_submodule_ref(mock_run, tmp_hub):
    """Rebase fails with submodule ref conflict."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="rejected non-fast-forward"),
        "fetch": _make_run_result(0),
        "diff": [
            _make_run_result(0, stdout="projects/api\n"),
            _make_run_result(0, stdout="projects/api\n"),
        ],
        "rebase": [
            _make_run_result(1, stderr="CONFLICT"),
            _make_run_result(0),  # --abort
        ],
    })

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is False
    assert "fast-forwardable" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_max_retries_exceeded(mock_run, tmp_hub):
    """Push keeps getting rejected — exceeds max retries."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="rejected non-fast-forward"),
        "fetch": _make_run_result(0),
        "diff": _make_run_result(0, stdout="projects/api\n"),
        "rebase": _make_run_result(0),
    })

    result = hub_push_with_rebase(root=tmp_hub, max_retries=2)
    assert result["pushed"] is False
    assert result["retries"] == 2
    assert "max retries" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_with_rebase_logs_ref_changes(mock_run, tmp_hub):
    """After a successful rebase, ref changes are logged."""
    # Register a subproject so refs can be tracked
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    call_count = {"rev-parse": 0}

    def dispatcher(cmd, **kwargs):
        sub = None
        for i, part in enumerate(cmd):
            if part == "git" or part.endswith("/git"):
                if i + 1 < len(cmd):
                    sub = cmd[i + 1]
                break

        if sub == "push":
            # First push rejected, second succeeds
            if not hasattr(dispatcher, "_push_count"):
                dispatcher._push_count = 0
            dispatcher._push_count += 1
            r = _make_run_result(
                1 if dispatcher._push_count == 1 else 0,
                stderr="rejected non-fast-forward" if dispatcher._push_count == 1 else "",
            )
        elif sub == "fetch":
            r = _make_run_result(0)
        elif sub == "diff":
            r = _make_run_result(0, stdout="projects/api\n")
        elif sub == "rev-parse":
            call_count["rev-parse"] += 1
            # Return different SHAs before and after rebase
            sha = "aaa111" if call_count["rev-parse"] <= 1 else "bbb222"
            r = _make_run_result(0, stdout=sha + "\n")
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r
        elif sub == "rebase":
            r = _make_run_result(0)
        else:
            r = _make_run_result(0)

        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is True
    assert result["rebased"] is True

    # Check that ref-log.yaml was written
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    assert log_path.exists()
    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == 1
    assert entries[0]["project"] == "api"
    assert entries[0]["source"] == "auto_rebase"
    assert entries[0]["old_ref"] == "aaa111"
    assert entries[0]["new_ref"] == "bbb222"


# ─── _analyze_remote_changes ─────────────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_analyze_remote_changes_submodule_only(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(0, stdout="projects/api\nprojects/web\n")
    result = _analyze_remote_changes(tmp_hub)
    assert result["submodule_only"] is True
    assert result["project_files_changed"] is False
    assert len(result["files"]) == 2


@patch("projectman.hub.registry.subprocess.run")
def test_analyze_remote_changes_mixed(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(
        0, stdout="projects/api\n.project/index.yaml\n"
    )
    result = _analyze_remote_changes(tmp_hub)
    assert result["submodule_only"] is False
    assert result["project_files_changed"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_analyze_remote_changes_git_fails(mock_run, tmp_hub):
    mock_run.side_effect = subprocess.CalledProcessError(1, "git diff")
    result = _analyze_remote_changes(tmp_hub)
    assert result["submodule_only"] is False
    assert result["files"] == []


# ─── _classify_rebase_conflict ────────────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_classify_rebase_conflict_project_files(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(0, stdout=".project/config.yaml\n")
    assert _classify_rebase_conflict(tmp_hub) == "project_files"


@patch("projectman.hub.registry.subprocess.run")
def test_classify_rebase_conflict_submodule_ref(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(0, stdout="projects/api\n")
    assert _classify_rebase_conflict(tmp_hub) == "submodule_ref"


@patch("projectman.hub.registry.subprocess.run")
def test_classify_rebase_conflict_unknown(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(0, stdout="README.md\n")
    assert _classify_rebase_conflict(tmp_hub) == "unknown"


@patch("projectman.hub.registry.subprocess.run")
def test_classify_rebase_conflict_no_conflicts(mock_run, tmp_hub):
    mock_run.return_value = _make_run_result(0, stdout="")
    assert _classify_rebase_conflict(tmp_hub) == "unknown"


# ─── check_ref_fast_forward ──────────────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_check_ref_fast_forward_ours_ahead(mock_run, tmp_hub):
    """When their_ref is ancestor of our_ref, resolution is 'ours'."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    # First merge-base call: --is-ancestor their our → exit 0
    mock_run.return_value = _make_run_result(0)

    result = check_ref_fast_forward("api", "aaa1111", "bbb2222", tmp_hub)
    assert result["resolution"] == "ours"
    assert result["newer_ref"] == "aaa1111"
    assert "keeping ours" in result["message"]


@patch("projectman.hub.registry.subprocess.run")
def test_check_ref_fast_forward_theirs_ahead(mock_run, tmp_hub):
    """When our_ref is ancestor of their_ref, resolution is 'theirs'."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    mock_run.side_effect = [
        _make_run_result(1),  # first check: theirs NOT ancestor of ours
        _make_run_result(0),  # second check: ours IS ancestor of theirs
    ]

    result = check_ref_fast_forward("api", "aaa1111", "bbb2222", tmp_hub)
    assert result["resolution"] == "theirs"
    assert result["newer_ref"] == "bbb2222"
    assert "taking theirs" in result["message"]


@patch("projectman.hub.registry.subprocess.run")
def test_check_ref_fast_forward_diverged(mock_run, tmp_hub):
    """When neither ref is ancestor, resolution is 'diverged'."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    mock_run.side_effect = [
        _make_run_result(1),  # first check fails
        _make_run_result(1),  # second check fails
    ]

    result = check_ref_fast_forward("api", "aaa1111", "bbb2222", tmp_hub)
    assert result["resolution"] == "diverged"
    assert result["newer_ref"] == ""
    assert "diverged" in result["message"]
    assert "aaa1111" in result["message"]
    assert "bbb2222" in result["message"]


@patch("projectman.hub.registry.subprocess.run")
def test_check_ref_fast_forward_missing_subproject(mock_run, tmp_hub):
    """Returns diverged when subproject directory doesn't exist."""
    mock_run.side_effect = FileNotFoundError("no such dir")

    result = check_ref_fast_forward("missing", "aaa", "bbb", tmp_hub)
    assert result["resolution"] == "diverged"


# ─── _get_conflicting_submodule_refs ──────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_get_conflicting_submodule_refs_parses_output(mock_run, tmp_hub):
    """Parses git ls-files --unmerged output into (our_ref, their_ref) pairs."""
    output = (
        "160000 remote_aaa 2\tprojects/api\n"
        "160000 local_bbb 3\tprojects/api\n"
        "160000 remote_ccc 2\tprojects/web\n"
        "160000 local_ddd 3\tprojects/web\n"
    )
    mock_run.return_value = _make_run_result(0, stdout=output)

    conflicts = _get_conflicting_submodule_refs(tmp_hub)
    assert len(conflicts) == 2
    # Stage 3 (git "theirs" in rebase) = our local ref
    # Stage 2 (git "ours" in rebase) = remote/their ref
    assert conflicts["api"] == ("local_bbb", "remote_aaa")
    assert conflicts["web"] == ("local_ddd", "remote_ccc")


@patch("projectman.hub.registry.subprocess.run")
def test_get_conflicting_submodule_refs_empty_on_error(mock_run, tmp_hub):
    """Returns empty dict when git command fails."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "git ls-files")

    conflicts = _get_conflicting_submodule_refs(tmp_hub)
    assert conflicts == {}


@patch("projectman.hub.registry.subprocess.run")
def test_get_conflicting_submodule_refs_incomplete_stages(mock_run, tmp_hub):
    """Skips entries that only have one stage (missing the other)."""
    output = "160000 aaa 2\tprojects/api\n"  # only stage 2, no stage 3
    mock_run.return_value = _make_run_result(0, stdout=output)

    conflicts = _get_conflicting_submodule_refs(tmp_hub)
    assert conflicts == {}


# ─── _resolve_submodule_ref_conflict ──────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_resolve_submodule_ref_conflict_success(mock_run, tmp_hub):
    """Returns True when checkout and add both succeed."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    mock_run.return_value = _make_run_result(0)

    assert _resolve_submodule_ref_conflict("api", "abc123", tmp_hub) is True
    assert mock_run.call_count == 2  # checkout + add


@patch("projectman.hub.registry.subprocess.run")
def test_resolve_submodule_ref_conflict_checkout_fails(mock_run, tmp_hub):
    """Returns False when checkout fails."""
    (tmp_hub / "projects" / "api").mkdir(parents=True)
    mock_run.side_effect = subprocess.CalledProcessError(1, "git checkout")

    assert _resolve_submodule_ref_conflict("api", "abc123", tmp_hub) is False


# ─── hub_push_with_rebase + fast-forward integration ─────────────


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_rebase_auto_resolves_ff_conflict(mock_run, tmp_hub):
    """Submodule ref conflict is auto-resolved via fast-forward check."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    rev_parse_count = {"n": 0}

    def dispatcher(cmd, **kwargs):
        sub = None
        for i, part in enumerate(cmd):
            if part == "git" or part.endswith("/git"):
                if i + 1 < len(cmd):
                    sub = cmd[i + 1]
                break

        if sub == "push":
            if not hasattr(dispatcher, "_push_n"):
                dispatcher._push_n = 0
            dispatcher._push_n += 1
            if dispatcher._push_n == 1:
                r = _make_run_result(1, stderr="rejected non-fast-forward")
            else:
                r = _make_run_result(0)
        elif sub == "fetch":
            r = _make_run_result(0)
        elif sub == "diff":
            r = _make_run_result(0, stdout="projects/api\n")
        elif sub == "rev-parse":
            rev_parse_count["n"] += 1
            sha = "old_aaa" if rev_parse_count["n"] <= 1 else "new_bbb"
            r = _make_run_result(0, stdout=sha + "\n")
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r
        elif sub == "rebase":
            if not hasattr(dispatcher, "_rebase_n"):
                dispatcher._rebase_n = 0
            dispatcher._rebase_n += 1
            if dispatcher._rebase_n == 1:
                r = _make_run_result(1, stderr="CONFLICT")  # initial rebase fails
            else:
                r = _make_run_result(0)  # --continue succeeds
        elif sub == "ls-files":
            r = _make_run_result(
                0,
                stdout="160000 remote_ref 2\tprojects/api\n"
                       "160000 local_ref 3\tprojects/api\n",
            )
        elif sub == "merge-base":
            # local_ref is ahead of remote_ref → ours is newer
            r = _make_run_result(0)
        elif sub == "checkout":
            r = _make_run_result(0)
        elif sub == "add":
            r = _make_run_result(0)
        else:
            r = _make_run_result(0)

        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is True
    assert result["rebased"] is True

    # Verify ref change was logged
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    assert log_path.exists()
    entries = yaml.safe_load(log_path.read_text())
    assert any(e["source"] == "auto_rebase" for e in entries)


@patch("projectman.hub.registry.subprocess.run")
def test_hub_push_rebase_diverged_conflict_reports_error(mock_run, tmp_hub):
    """Diverged submodule refs are reported with a clear error message."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        sub = None
        for i, part in enumerate(cmd):
            if part == "git" or part.endswith("/git"):
                if i + 1 < len(cmd):
                    sub = cmd[i + 1]
                break

        if sub == "push":
            r = _make_run_result(1, stderr="rejected non-fast-forward")
        elif sub == "fetch":
            r = _make_run_result(0)
        elif sub == "diff":
            r = _make_run_result(0, stdout="projects/api\n")
        elif sub == "rev-parse":
            r = _make_run_result(0, stdout="some_sha\n")
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r
        elif sub == "rebase":
            if not hasattr(dispatcher, "_rebase_n"):
                dispatcher._rebase_n = 0
            dispatcher._rebase_n += 1
            if dispatcher._rebase_n == 1:
                r = _make_run_result(1, stderr="CONFLICT")
            else:
                r = _make_run_result(0)  # --abort
        elif sub == "ls-files":
            r = _make_run_result(
                0,
                stdout="160000 aaa111 2\tprojects/api\n"
                       "160000 bbb222 3\tprojects/api\n",
            )
        elif sub == "merge-base":
            # Both checks fail → diverged
            r = _make_run_result(1)
        else:
            r = _make_run_result(0)

        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = hub_push_with_rebase(root=tmp_hub)
    assert result["pushed"] is False
    assert "diverged" in result["error"]
    assert "api" in result["error"]


# ─── coordinated_push ────────────────────────────────────────────


from projectman.hub.registry import coordinated_push


def test_coordinated_push_not_a_hub(tmp_project):
    """Returns error for non-hub projects."""
    result = coordinated_push(root=tmp_project)
    assert result["pushed"] is False
    assert result["hub_result"] is None
    assert "not a hub project" in result["report"]


def test_coordinated_push_dry_run(tmp_hub):
    """Dry run returns a report without pushing."""
    result = coordinated_push(dry_run=True, root=tmp_hub)
    assert result["pushed"] is False
    assert result["hub_result"] is None
    assert "Dry Run" in result["report"]


@patch("projectman.hub.registry.subprocess.run")
def test_coordinated_push_clean_push(mock_run, tmp_hub):
    """Clean push reports success with SHA."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="abc1234def5678\n"),
    })

    result = coordinated_push(root=tmp_hub)
    assert result["pushed"] is True
    assert result["hub_result"]["rebased"] is False
    assert "\u2713" in result["report"]
    assert "abc1234" in result["report"]
    assert "rebased" not in result["report"]


@patch("projectman.hub.registry.subprocess.run")
def test_coordinated_push_rebased_push(mock_run, tmp_hub):
    """Push with rebase reports the retry count."""
    mock_run.side_effect = _git_dispatcher({
        "push": [
            _make_run_result(1, stderr="rejected non-fast-forward"),
            _make_run_result(0),
        ],
        "fetch": _make_run_result(0),
        "diff": _make_run_result(0, stdout="projects/api\n"),
        "rebase": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="abc1234def5678\n"),
    })

    result = coordinated_push(root=tmp_hub)
    assert result["pushed"] is True
    assert result["hub_result"]["rebased"] is True
    assert "rebased" in result["report"]
    assert "1 retry" in result["report"]
    assert "\u2713" in result["report"]


@patch("projectman.hub.registry.subprocess.run")
def test_coordinated_push_max_retries(mock_run, tmp_hub):
    """Max retries exceeded shows clear failure message."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="rejected non-fast-forward"),
        "fetch": _make_run_result(0),
        "diff": _make_run_result(0, stdout="projects/api\n"),
        "rebase": _make_run_result(0),
    })

    result = coordinated_push(root=tmp_hub, max_retries=2)
    assert result["pushed"] is False
    assert "max retries" in result["hub_result"]["error"]
    assert "\u2717" in result["report"]
    assert "manual resolution needed" in result["report"]


@patch("projectman.hub.registry.subprocess.run")
def test_coordinated_push_diverged_conflict(mock_run, tmp_hub):
    """Diverged ref conflict suggests resolution in the subproject."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        sub = None
        for i, part in enumerate(cmd):
            if part == "git" or part.endswith("/git"):
                if i + 1 < len(cmd):
                    sub = cmd[i + 1]
                break

        if sub == "push":
            return _make_run_result(1, stderr="rejected non-fast-forward")
        elif sub == "rebase" and "--abort" not in cmd:
            return _make_run_result(1, stderr="CONFLICT")
        elif sub == "diff" and "--diff-filter=U" in cmd:
            return _make_run_result(0, stdout="projects/api\n")
        elif sub == "ls-files":
            return _make_run_result(
                0,
                stdout="160000 aaa 2\tprojects/api\n"
                       "160000 bbb 3\tprojects/api\n",
            )
        elif sub == "merge-base":
            return _make_run_result(1)  # diverged
        elif sub == "rev-parse":
            r = _make_run_result(0, stdout="some_sha\n")
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r
        else:
            r = _make_run_result(0)
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r

    mock_run.side_effect = dispatcher

    result = coordinated_push(root=tmp_hub)
    assert result["pushed"] is False
    assert "diverged" in result["report"]
    assert "Suggestion" in result["report"]


@patch("projectman.hub.registry.subprocess.run")
def test_coordinated_push_report_format(mock_run, tmp_hub):
    """Report starts with 'Hub:' header."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="deadbeef1234\n"),
    })

    result = coordinated_push(root=tmp_hub)
    assert result["report"].startswith("Hub:")


# ─── validate_branches ────────────────────────────────────────────


def test_validate_branches_not_a_hub(tmp_project):
    """Returns error for non-hub projects."""
    result = validate_branches(root=tmp_project)
    assert result["ok"] is False
    assert "Not a hub" in result["summary"]


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_all_match(mock_run, tmp_hub):
    """All submodules on correct tracking branch → ok=True."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is True
    assert len(result["aligned"]) == 1
    assert result["aligned"][0]["name"] == "api"
    assert result["aligned"][0]["branch"] == "main"
    assert result["aligned"][0]["dirty"] is False
    assert result["misaligned"] == []
    assert result["detached"] == []
    assert result["missing"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_mismatch(mock_run, tmp_hub):
    """Submodule on wrong branch → ok=False with expected vs actual."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is False
    assert len(result["misaligned"]) == 1
    assert result["misaligned"][0]["expected"] == "main"
    assert result["misaligned"][0]["actual"] == "feature-x"
    assert result["aligned"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_no_tracking_branch_skipped(mock_run, tmp_hub):
    """Projects without a tracking branch in .gitmodules are skipped."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            # No tracking branch configured
            return _make_run_result(1, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is True
    assert result["aligned"] == []
    assert result["misaligned"] == []
    assert result["detached"] == []
    assert result["missing"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_multiple_projects_mixed(mock_run, tmp_hub):
    """Multiple projects: one matching, one mismatched → ok=False."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)
    (tmp_hub / "projects" / "web").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            # Both track main
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            # Determine which project by cwd
            cwd = kwargs.get("cwd", "")
            if "api" in cwd:
                return _make_run_result(0, stdout="main\n")
            if "web" in cwd:
                return _make_run_result(0, stdout="develop\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is False
    assert len(result["aligned"]) == 1
    assert result["aligned"][0]["name"] == "api"
    assert len(result["misaligned"]) == 1
    assert result["misaligned"][0]["name"] == "web"
    assert result["misaligned"][0]["expected"] == "main"
    assert result["misaligned"][0]["actual"] == "develop"


def test_validate_branches_missing_project_dir(tmp_hub):
    """Projects with missing directories go to the missing list."""
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("ghost")
    save_config(hub_config, tmp_hub)

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is False
    assert len(result["missing"]) == 1
    assert result["missing"][0]["name"] == "ghost"


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_detached_head(mock_run, tmp_hub):
    """Submodule in detached HEAD state → goes to detached list (informational in default mode)."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    # In default (non-strict) mode, detached HEAD is informational → ok=True
    assert result["ok"] is True
    assert len(result["detached"]) == 1
    assert result["detached"][0]["name"] == "api"
    assert result["detached"][0]["expected"] == "main"
    assert result["aligned"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_dirty_working_tree(mock_run, tmp_hub):
    """Dirty working tree is flagged on aligned projects."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M file.py\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is True
    assert len(result["aligned"]) == 1
    assert result["aligned"][0]["dirty"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_summary_string(mock_run, tmp_hub):
    """Summary string reflects the validation outcome."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert "summary" in result
    assert "correct branch" in result["summary"]


# ─── format_branch_validation (error message clarity) ────────────


def test_format_branch_validation_mismatch_shows_expected_and_actual():
    """Mismatch message clearly shows expected vs actual branch."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [
            {"name": "api", "expected": "main", "actual": "feature-x", "dirty": False},
        ],
        "detached": [],
        "missing": [],
        "summary": "1 misaligned",
    }
    msg = format_branch_validation(result)
    assert "Branch mismatch" in msg
    assert "api" in msg
    assert "expected 'main'" in msg
    assert "actual 'feature-x'" in msg


def test_format_branch_validation_multiple_mismatches():
    """Multiple mismatched projects each listed with expected vs actual."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [
            {"name": "api", "expected": "main", "actual": "feature-x", "dirty": False},
            {"name": "web", "expected": "main", "actual": "develop", "dirty": False},
        ],
        "detached": [],
        "missing": [],
        "summary": "2 misaligned",
    }
    msg = format_branch_validation(result)
    assert "api" in msg
    assert "expected 'main', actual 'feature-x'" in msg
    assert "web" in msg
    assert "expected 'main', actual 'develop'" in msg


def test_format_branch_validation_all_ok():
    """All branches matching → positive confirmation message."""
    result = {
        "ok": True,
        "aligned": [
            {"name": "api", "branch": "main", "dirty": False},
        ],
        "misaligned": [],
        "detached": [],
        "missing": [],
        "summary": "All 1 submodule(s) on correct branch.",
    }
    msg = format_branch_validation(result)
    assert "correct branch" in msg
    assert "mismatch" not in msg.lower()


def test_format_branch_validation_with_missing():
    """Missing directories included in formatted output."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [],
        "detached": [],
        "missing": [{"name": "ghost"}],
        "summary": "1 missing",
    }
    msg = format_branch_validation(result)
    assert "ghost" in msg
    assert "not found" in msg


def test_format_branch_validation_no_tracking_branches():
    """No submodules to check → informative message."""
    result = {
        "ok": True,
        "aligned": [],
        "misaligned": [],
        "detached": [],
        "missing": [],
        "summary": "No submodules with tracking branches to validate.",
    }
    msg = format_branch_validation(result)
    assert "No submodules" in msg


def test_format_branch_validation_detached_head():
    """Detached HEAD projects shown in formatted output."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [],
        "detached": [{"name": "worker", "expected": "main", "dirty": False}],
        "missing": [],
        "summary": "1 detached",
    }
    msg = format_branch_validation(result)
    assert "Detached HEAD" in msg
    assert "worker" in msg
    assert "expected 'main'" in msg


def test_format_branch_validation_dirty_flag():
    """Dirty flag shown in formatted output for misaligned projects."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [
            {"name": "api", "expected": "main", "actual": "feature-x", "dirty": True},
        ],
        "detached": [],
        "missing": [],
        "summary": "1 misaligned",
    }
    msg = format_branch_validation(result)
    assert "(dirty)" in msg


# ─── standalone command: CLI + MCP tool ───────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_cli_standalone(mock_run, tmp_hub):
    """validate-branches CLI command runs standalone and reports results."""
    from click.testing import CliRunner
    from projectman.cli import cli

    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-branches"], env={"PROJECTMAN_ROOT": str(tmp_hub)})
    assert result.exit_code == 0
    assert "correct branch" in result.output


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_cli_standalone_shows_mismatch(mock_run, tmp_hub):
    """validate-branches CLI command shows mismatch details when run standalone."""
    from click.testing import CliRunner
    from projectman.cli import cli

    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-branches"], env={"PROJECTMAN_ROOT": str(tmp_hub)})
    assert result.exit_code == 1
    assert "Branch mismatch" in result.output
    assert "api" in result.output
    assert "expected 'main'" in result.output
    assert "actual 'feature-x'" in result.output


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_mcp_tool_standalone(mock_run, tmp_hub, monkeypatch):
    """pm_validate_branches MCP tool can be called standalone."""
    from projectman.server import pm_validate_branches

    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_hub)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result_str = pm_validate_branches()
    data = yaml.safe_load(result_str)
    assert data["ok"] is True
    assert len(data["aligned"]) == 1
    assert data["aligned"][0]["name"] == "api"


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_mcp_tool_standalone_returns_mismatch(mock_run, tmp_hub, monkeypatch):
    """pm_validate_branches MCP tool returns structured mismatch data."""
    from projectman.server import pm_validate_branches

    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_hub)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result_str = pm_validate_branches()
    data = yaml.safe_load(result_str)
    assert data["ok"] is False
    assert data["misaligned"][0]["expected"] == "main"
    assert data["misaligned"][0]["actual"] == "feature-x"


# ─── validate_branches strict mode ───────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_strict_detached_is_blocking(mock_run, tmp_hub):
    """In strict mode, detached HEAD causes ok=False."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub, strict=True)
    assert result["ok"] is False
    assert result["strict"] is True
    assert len(result["detached"]) == 1
    assert "blocking" in result["summary"]


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_default_detached_is_informational(mock_run, tmp_hub):
    """In default mode, detached HEAD does not cause ok=False."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub)
    assert result["ok"] is True
    assert result["strict"] is False
    assert len(result["detached"]) == 1
    assert "info" in result["summary"]


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_strict_misaligned_still_blocking(mock_run, tmp_hub):
    """In strict mode, misaligned branches are still blocking."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub, strict=True)
    assert result["ok"] is False
    assert result["strict"] is True
    assert len(result["misaligned"]) == 1


@patch("projectman.hub.registry.subprocess.run")
def test_validate_branches_strict_all_aligned_ok(mock_run, tmp_hub):
    """In strict mode, all aligned → ok=True."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = validate_branches(root=tmp_hub, strict=True)
    assert result["ok"] is True
    assert result["strict"] is True


def test_validate_branches_result_includes_strict_flag(tmp_project):
    """Result dict always includes the strict flag."""
    result = validate_branches(root=tmp_project)
    assert "strict" in result
    assert result["strict"] is False


# ─── format_branch_validation strict/info labels ─────────────────


def test_format_branch_validation_detached_strict_label():
    """Detached HEAD section says 'blocking' in strict mode."""
    result = {
        "ok": False,
        "aligned": [],
        "misaligned": [],
        "detached": [{"name": "worker", "expected": "main", "dirty": False}],
        "missing": [],
        "strict": True,
        "summary": "1 detached (blocking)",
    }
    msg = format_branch_validation(result)
    assert "blocking" in msg
    assert "informational" not in msg


def test_format_branch_validation_detached_default_label():
    """Detached HEAD section says 'informational' in default mode."""
    result = {
        "ok": True,
        "aligned": [],
        "misaligned": [],
        "detached": [{"name": "worker", "expected": "main", "dirty": False}],
        "missing": [],
        "strict": False,
        "summary": "1 detached (info)",
    }
    msg = format_branch_validation(result)
    assert "informational" in msg
    assert "blocking" not in msg


# ─── sync() with branch validation ───────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_sync_warns_on_misaligned_branches(mock_run, tmp_hub):
    """sync() includes branch mismatch warnings before sync results."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "pull" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = sync(root=tmp_hub)
    assert "branch validation" in result
    assert "warning" in result
    assert "api" in result
    assert "feature-x" in result
    assert "expected 'main'" in result
    # sync still completes
    assert "sync complete" in result


@patch("projectman.hub.registry.subprocess.run")
def test_sync_info_on_detached_head(mock_run, tmp_hub):
    """sync() includes informational note for detached HEAD submodules."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "pull" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = sync(root=tmp_hub)
    assert "branch validation" in result
    assert "info" in result
    assert "detached HEAD" in result
    assert "sync complete" in result


@patch("projectman.hub.registry.subprocess.run")
def test_sync_no_warnings_when_aligned(mock_run, tmp_hub):
    """sync() has no branch validation section when all branches match."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "pull" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = sync(root=tmp_hub)
    assert "branch validation" not in result
    assert "sync complete" in result


# ─── pm_commit tests ─────────────────────────────────────────────


def test_pm_commit_all_scope(tmp_git_hub):
    """pm_commit with scope='all' commits all .project/ changes."""
    # Create a new story file to produce a change
    stories_dir = tmp_git_hub / ".project" / "stories"
    (stories_dir / "US-HUB-1.md").write_text("---\ntitle: Test\nstatus: backlog\n---\nBody\n")

    result = pm_commit(scope="all", root=tmp_git_hub)

    assert "commit_hash" in result
    assert result["message"].startswith("pm: ")
    assert len(result["files_committed"]) > 0
    assert any("US-HUB-1" in f for f in result["files_committed"])


def test_pm_commit_hub_scope_excludes_subprojects(tmp_git_hub):
    """pm_commit with scope='hub' only commits hub-level files, not subproject files."""
    # Create hub-level story
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nHub body\n"
    )
    # Create subproject story
    sub_dir = tmp_git_hub / ".project" / "projects" / "api"
    (sub_dir / "stories").mkdir(parents=True)
    (sub_dir / "tasks").mkdir()
    (sub_dir / "config.yaml").write_text("name: api\nprefix: API\n")
    (sub_dir / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )

    result = pm_commit(scope="hub", root=tmp_git_hub)

    assert "commit_hash" in result
    # Hub story should be committed
    assert any("US-HUB-1" in f for f in result["files_committed"])
    # Subproject story should NOT be committed
    assert not any("US-API-1" in f for f in result["files_committed"])
    assert not any("projects/api" in f for f in result["files_committed"])


def test_pm_commit_project_scope(tmp_git_hub):
    """pm_commit with scope='project:api' only commits that subproject's files."""
    # Create hub-level story
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nHub body\n"
    )
    # Create subproject story
    sub_dir = tmp_git_hub / ".project" / "projects" / "api"
    (sub_dir / "stories").mkdir(parents=True)
    (sub_dir / "tasks").mkdir()
    (sub_dir / "config.yaml").write_text("name: api\nprefix: API\n")
    (sub_dir / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )

    result = pm_commit(scope="project:api", root=tmp_git_hub)

    assert "commit_hash" in result
    # Subproject story should be committed
    assert any("US-API-1" in f for f in result["files_committed"])
    # Hub story should NOT be committed
    assert not any("US-HUB-1" in f for f in result["files_committed"])


def test_pm_commit_nothing_to_commit(tmp_git_hub):
    """pm_commit returns nothing_to_commit when no .project/ files changed."""
    result = pm_commit(scope="all", root=tmp_git_hub)
    assert result == {"nothing_to_commit": True}


def test_pm_commit_nothing_to_commit_scoped(tmp_git_hub):
    """pm_commit returns nothing_to_commit when scope matches no changed files."""
    # Create hub-level change only
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nBody\n"
    )
    # Create the subproject dir so scope validation passes
    sub_dir = tmp_git_hub / ".project" / "projects" / "api"
    sub_dir.mkdir(parents=True)

    result = pm_commit(scope="project:api", root=tmp_git_hub)
    assert result == {"nothing_to_commit": True}


def test_pm_commit_custom_message(tmp_git_hub):
    """pm_commit uses a provided message instead of auto-generating."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Test\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(scope="all", message="custom: my msg", root=tmp_git_hub)

    assert result["message"] == "custom: my msg"


def test_pm_commit_auto_message_lists_ids(tmp_git_hub):
    """Auto-generated message lists individual IDs when few files changed."""
    (tmp_git_hub / ".project" / "stories" / "US-HUB-5.md").write_text(
        "---\ntitle: Five\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(scope="all", root=tmp_git_hub)

    assert "US-HUB-5" in result["message"]


def test_pm_commit_invalid_scope(tmp_git_hub):
    """pm_commit raises ValueError for an unrecognised scope."""
    with pytest.raises(ValueError, match="Invalid scope"):
        pm_commit(scope="bogus", root=tmp_git_hub)


def test_pm_commit_missing_project_scope(tmp_git_hub):
    """pm_commit raises ValueError when scoped to a non-existent project."""
    with pytest.raises(ValueError, match="not found"):
        pm_commit(scope="project:nonexistent", root=tmp_git_hub)


def test_pm_commit_no_project_dir(tmp_path):
    """pm_commit raises FileNotFoundError when .project/ doesn't exist."""
    # tmp_path has no .project/
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True, check=True)

    with pytest.raises(FileNotFoundError, match=".project/"):
        pm_commit(scope="all", root=tmp_path)


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
    """pm_commit never touches files outside .project/ — src/ changes stay unstaged."""
    # Create a non-.project file change
    src_dir = tmp_git_hub / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello')\n")

    # Create a .project change too
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Test\nstatus: backlog\n---\nBody\n"
    )

    result = pm_commit(scope="all", root=tmp_git_hub)

    assert "commit_hash" in result
    # Only .project/ files should be committed
    for f in result["files_committed"]:
        assert f.startswith(".project/"), f"Non-.project file committed: {f}"
    assert not any("src/" in f for f in result["files_committed"])

    # src/main.py should still show as untracked
    import subprocess
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "src/"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert "src/main.py" in status.stdout


def test_pm_commit_all_scope_hub_and_two_subprojects(tmp_git_hub):
    """pm_commit(scope='all') commits hub + 2 subprojects in one commit."""
    # Register two subprojects
    _register_subproject(tmp_git_hub, "api", prefix="API")
    _register_subproject(tmp_git_hub, "web", prefix="WEB")

    # Commit registration so these are baseline
    import subprocess
    subprocess.run(["git", "add", "."], cwd=str(tmp_git_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "register subs"], cwd=str(tmp_git_hub), capture_output=True, check=True)

    # Create changes in hub + both subprojects
    (tmp_git_hub / ".project" / "stories" / "US-HUB-1.md").write_text(
        "---\ntitle: Hub story\nstatus: backlog\n---\nHub body\n"
    )
    (tmp_git_hub / ".project" / "projects" / "api" / "stories" / "US-API-1.md").write_text(
        "---\ntitle: API story\nstatus: backlog\n---\nAPI body\n"
    )
    (tmp_git_hub / ".project" / "projects" / "web" / "stories" / "US-WEB-1.md").write_text(
        "---\ntitle: Web story\nstatus: backlog\n---\nWeb body\n"
    )

    result = pm_commit(scope="all", root=tmp_git_hub)

    assert "commit_hash" in result
    files = result["files_committed"]
    # All three scopes should be in the same commit
    assert any("US-HUB-1" in f for f in files), "Hub story not committed"
    assert any("projects/api" in f for f in files), "API subproject not committed"
    assert any("projects/web" in f for f in files), "Web subproject not committed"

    # Verify it was a single commit (check git log)
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=str(tmp_git_hub), capture_output=True, text=True,
    )
    assert result["commit_hash"][:7] in log.stdout


# ─── _push_subproject ─────────────────────────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_push_subproject_success(mock_run, tmp_hub):
    """Pushes subproject on its current branch."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = _push_subproject("api", tmp_hub)
    assert result["pushed"] is True
    assert result["branch"] == "feature-x"


@patch("projectman.hub.registry.subprocess.run")
def test_push_subproject_detached_head(mock_run, tmp_hub):
    """Refuses to push when subproject is in detached HEAD state."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = _push_subproject("api", tmp_hub)
    assert result["pushed"] is False
    assert "detached HEAD" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_subproject_push_failure(mock_run, tmp_hub):
    """Reports error when git push fails."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            r = _make_run_result(0, stdout="main\n")
            if kwargs.get("check") and r.returncode != 0:
                raise subprocess.CalledProcessError(
                    r.returncode, cmd, output=r.stdout, stderr=r.stderr,
                )
            return r
        if "push" in cmd:
            return _make_run_result(1, stderr="Permission denied")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = _push_subproject("api", tmp_hub)
    assert result["pushed"] is False
    assert "Permission denied" in result["error"]


# ─── pm_push ──────────────────────────────────────────────────────


def test_pm_push_not_a_hub(tmp_project):
    """Returns error for non-hub projects."""
    result = pm_push(root=tmp_project)
    assert result["pushed"] is False
    assert "not a hub project" in result["error"]


def test_pm_push_invalid_scope(tmp_hub):
    """Returns error for unrecognised scope."""
    result = pm_push(scope="bogus", root=tmp_hub)
    assert result["pushed"] is False
    assert "invalid scope" in result["error"]


def test_pm_push_project_scope_unregistered(tmp_hub):
    """Returns error when project is not registered in hub."""
    result = pm_push(scope="project:ghost", root=tmp_hub)
    assert result["pushed"] is False
    assert "not registered" in result["error"]


def test_pm_push_project_scope_missing_dir(tmp_hub):
    """Returns error when project directory doesn't exist."""
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("ghost")
    save_config(hub_config, tmp_hub)

    result = pm_push(scope="project:ghost", root=tmp_hub)
    assert result["pushed"] is False
    assert "not found" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_hub_scope_delegates_to_push_hub(mock_run, tmp_hub):
    """Hub scope delegates to push_hub and returns status."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="abc1234\n"),
    })

    result = pm_push(scope="hub", root=tmp_hub)
    assert result["pushed"] is True
    assert result["scope"] == "hub"
    assert result["status"] == "pushed"


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_hub_scope_failure(mock_run, tmp_hub):
    """Hub scope reports push failure."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(1, stderr="Permission denied"),
    })

    result = pm_push(scope="hub", root=tmp_hub)
    assert result["pushed"] is False
    assert result["scope"] == "hub"
    assert "error" in result


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_all_scope_delegates_to_coordinated_push(mock_run, tmp_hub):
    """All scope delegates to coordinated_push."""
    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="abc1234\n"),
    })

    result = pm_push(scope="all", root=tmp_hub)
    assert result["pushed"] is True
    assert result["scope"] == "all"
    assert "report" in result  # coordinated_push includes a report


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_project_scope_success(mock_run, tmp_hub):
    """Project scope pushes the specific subproject."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        # validate_branches calls
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        # push calls
        if "push" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = pm_push(scope="project:api", root=tmp_hub)
    assert result["pushed"] is True
    assert result["scope"] == "project:api"
    assert result["branch"] == "main"


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_project_scope_branch_validation_fails_misaligned(mock_run, tmp_hub):
    """Project scope aborts when branch validation detects mismatch."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = pm_push(scope="project:api", root=tmp_hub)
    assert result["pushed"] is False
    assert "branch validation failed" in result["error"]
    assert "feature-x" in result["error"]
    assert "main" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_project_scope_branch_validation_fails_detached(mock_run, tmp_hub):
    """Project scope aborts when branch validation detects detached HEAD."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = pm_push(scope="project:api", root=tmp_hub)
    assert result["pushed"] is False
    assert "branch validation failed" in result["error"]
    assert "detached HEAD" in result["error"]


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_all_scope_branch_validation_fails(mock_run, tmp_hub):
    """All scope aborts when branch validation fails."""
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = pm_push(scope="all", root=tmp_hub)
    assert result["pushed"] is False
    assert "branch validation failed" in result["error"]
    assert "validation" in result  # includes full validation dict


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_hub_scope_skips_branch_validation(mock_run, tmp_hub):
    """Hub scope does not run branch validation (hub is always on main)."""
    # Register a misaligned subproject — should NOT block hub push
    _register_subproject(tmp_hub, "api", prefix="API")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)

    mock_run.side_effect = _git_dispatcher({
        "push": _make_run_result(0),
        "rev-parse": _make_run_result(0, stdout="abc1234\n"),
    })

    result = pm_push(scope="hub", root=tmp_hub)
    # Hub push succeeds even though subproject is misaligned
    assert result["pushed"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_pm_push_project_scope_other_project_misaligned_ok(mock_run, tmp_hub):
    """Project scope only checks the targeted project, not others."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    (tmp_hub / "projects" / "api").mkdir(parents=True, exist_ok=True)
    (tmp_hub / "projects" / "web").mkdir(parents=True, exist_ok=True)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            cwd = kwargs.get("cwd", "")
            if "api" in cwd:
                return _make_run_result(0, stdout="main\n")
            if "web" in cwd:
                return _make_run_result(0, stdout="feature-x\n")  # misaligned
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "push" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    # Push api — should succeed even though web is misaligned
    result = pm_push(scope="project:api", root=tmp_hub)
    assert result["pushed"] is True
    assert result["branch"] == "main"


# ─── push_preflight ──────────────────────────────────────────────


def test_push_preflight_not_a_hub(tmp_project):
    result = push_preflight(root=tmp_project)
    assert result["can_proceed"] is False
    assert len(result["blocked"]) == 1
    assert "not a hub" in result["blocked"][0]["reason"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_all_ready(mock_run, tmp_hub):
    """All projects pass: aligned, remote reachable, no blockers."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")

    def dispatcher(cmd, **kwargs):
        # validate_branches helpers
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        # _is_dirty → clean
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        # _remote_reachable → yes
        if "ls-remote" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is True
    assert sorted(result["ready"]) == ["api", "web"]
    assert result["blocked"] == []
    assert result["warnings"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_branch_mismatch_blocks(mock_run, tmp_hub):
    """A misaligned project is blocked with a clear reason."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is False
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["name"] == "api"
    assert "branch mismatch" in result["blocked"][0]["reason"]
    assert "feature-x" in result["blocked"][0]["reason"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_detached_head_blocks(mock_run, tmp_hub):
    """Detached HEAD blocks in push preflight (strict mode)."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is False
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["name"] == "api"
    assert "detached HEAD" in result["blocked"][0]["reason"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_remote_unreachable_blocks(mock_run, tmp_hub):
    """Project with unreachable remote is blocked."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        # Remote unreachable
        if "ls-remote" in cmd:
            return _make_run_result(128, stderr="fatal: Could not read from remote")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is False
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["name"] == "api"
    assert "remote" in result["blocked"][0]["reason"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_dirty_no_staged_warns(mock_run, tmp_hub):
    """Dirty project with no staged changes produces a warning, not a blocker."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        # _is_dirty → yes (has untracked files)
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="?? newfile.txt\n")
        # _has_staged_changes → no (diff --cached --quiet exits 0)
        if "diff" in cmd and "--cached" in cmd:
            return _make_run_result(0)
        # Remote reachable
        if "ls-remote" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is True
    assert "api" in result["ready"]
    assert len(result["warnings"]) == 1
    assert "no staged changes" in result["warnings"][0]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_missing_project_blocks(mock_run, tmp_hub):
    """Missing project directory is a blocker."""
    _register_subproject(tmp_hub, "api", prefix="API")
    # Remove the source directory
    shutil.rmtree(tmp_hub / "projects" / "api")

    mock_run.side_effect = _git_dispatcher({})

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is False
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["name"] == "api"
    assert "not found" in result["blocked"][0]["reason"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_scoped_to_specific_projects(mock_run, tmp_hub):
    """When projects list is given, only those are checked."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            cwd = kwargs.get("cwd", "")
            if "api" in cwd:
                return _make_run_result(0, stdout="main\n")
            if "web" in cwd:
                return _make_run_result(0, stdout="feature-x\n")  # misaligned
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "ls-remote" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    # Only check api — web misalignment doesn't affect result
    result = push_preflight(projects=["api"], root=tmp_hub)
    assert result["can_proceed"] is True
    assert result["ready"] == ["api"]


@patch("projectman.hub.registry.subprocess.run")
def test_push_preflight_collects_all_issues(mock_run, tmp_hub):
    """Preflight collects all non-fatal issues at once (not one at a time)."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    _register_subproject(tmp_hub, "worker", prefix="WRK")
    # Remove worker source dir to make it missing
    shutil.rmtree(tmp_hub / "projects" / "worker")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            cwd = kwargs.get("cwd", "")
            if "api" in cwd:
                return _make_run_result(0, stdout="feature-x\n")  # misaligned
            if "web" in cwd:
                return _make_run_result(0, stdout="main\n")  # ok
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "ls-remote" in cmd:
            return _make_run_result(0)
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = push_preflight(root=tmp_hub)
    assert result["can_proceed"] is False
    # Should have 2 blockers: api (misaligned) + worker (missing)
    blocked_names = {b["name"] for b in result["blocked"]}
    assert "api" in blocked_names
    assert "worker" in blocked_names
    # web should be ready
    assert "web" in result["ready"]
