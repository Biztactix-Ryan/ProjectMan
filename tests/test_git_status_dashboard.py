"""Tests for hub git status dashboard — US-PRJ-8-1 / US-PRJ-8-2 / US-PRJ-8-3 / US-PRJ-8-4.

Verifies acceptance criteria:
- US-PRJ-8-1: Single command shows git state of all N submodules.
- US-PRJ-8-2: Shows branch/dirty/ahead-behind/PR status per repo.
- US-PRJ-8-3: Highlights mismatches and issues.
- US-PRJ-8-4: Scales to 20+ submodules without clutter.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import yaml

from projectman.hub.registry import git_status_all


# ─── Helpers ──────────────────────────────────────────────────────


def _make_run_result(returncode=0, stdout="", stderr=""):
    """Build a CompletedProcess-like object."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _register_subproject(hub_root, name, prefix="SUB"):
    """Set up a subproject with source dir, PM data dir, and hub config entry."""
    sub_path = hub_root / "projects" / name
    sub_path.mkdir(parents=True, exist_ok=True)

    pm_dir = hub_root / ".project" / "projects" / name
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "stories").mkdir(exist_ok=True)
    (pm_dir / "tasks").mkdir(exist_ok=True)

    config = {
        "name": name,
        "prefix": prefix,
        "description": "",
        "hub": False,
        "next_story_id": 1,
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


# ─── git_status_all: single command for all submodules ────────────


def test_git_status_all_not_a_hub(tmp_project):
    """Returns error for non-hub projects."""
    result = git_status_all(root=tmp_project)
    assert result["ok"] is False
    assert "Not a hub" in result["summary"]
    assert result["projects"] == []


def test_git_status_all_empty_hub(tmp_hub):
    """Empty hub with no projects returns ok with zero total."""
    result = git_status_all(root=tmp_hub)
    assert result["ok"] is True
    assert result["total"] == 0
    assert result["projects"] == []
    assert "No projects" in result["summary"]


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_single_project(mock_run, tmp_hub):
    """Single submodule returns its git state."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["total"] == 1
    assert result["ok"] is True
    assert len(result["projects"]) == 1

    proj = result["projects"][0]
    assert proj["name"] == "api"
    assert proj["branch"] == "main"
    assert proj["tracking_branch"] == "main"
    assert proj["dirty"] is False
    assert proj["ahead"] == 0
    assert proj["behind"] == 0
    assert proj["branch_ok"] is True
    assert proj["exists"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_multiple_projects(mock_run, tmp_hub):
    """Single call returns state for ALL N submodules."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    _register_subproject(tmp_hub, "worker", prefix="WRK")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["total"] == 3
    assert result["ok"] is True
    assert len(result["projects"]) == 3

    names = [p["name"] for p in result["projects"]]
    assert names == ["api", "web", "worker"]

    # Every project has full git state fields
    for proj in result["projects"]:
        assert "branch" in proj
        assert "tracking_branch" in proj
        assert "dirty" in proj
        assert "ahead" in proj
        assert "behind" in proj
        assert "branch_ok" in proj
        assert "exists" in proj


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_detects_dirty(mock_run, tmp_hub):
    """Dirty working tree is flagged in the output."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M src/main.py\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["ok"] is False
    assert result["issues"] == 1
    assert result["projects"][0]["dirty"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_detects_branch_mismatch(mock_run, tmp_hub):
    """Branch misalignment is flagged."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["ok"] is False
    assert result["projects"][0]["branch_ok"] is False
    assert result["projects"][0]["branch"] == "feature-x"
    assert result["projects"][0]["tracking_branch"] == "main"


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_detects_ahead_behind(mock_run, tmp_hub):
    """Ahead/behind counts are reported correctly."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            # left=behind(2), right=ahead(3)
            return _make_run_result(0, stdout="2\t3\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["ahead"] == 3
    assert proj["behind"] == 2
    # behind > 0 means issue
    assert result["ok"] is False
    assert result["issues"] == 1


def test_git_status_all_missing_project_dir(tmp_hub):
    """Missing project directory is reported with exists=False."""
    _register_subproject(tmp_hub, "gone")
    # Remove the source directory but keep PM data
    import shutil
    shutil.rmtree(tmp_hub / "projects" / "gone")

    result = git_status_all(root=tmp_hub)
    assert result["total"] == 1
    assert result["ok"] is False
    assert result["issues"] == 1
    assert result["projects"][0]["exists"] is False
    assert result["projects"][0]["name"] == "gone"


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_mixed_states(mock_run, tmp_hub):
    """Multiple projects with different states are all reported in one call."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    _register_subproject(tmp_hub, "worker", prefix="WRK")

    call_count = {"n": 0}

    def dispatcher(cmd, **kwargs):
        cwd = kwargs.get("cwd", "")

        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")

        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            # api on main, web on feature, worker on main
            if "web" in cwd:
                return _make_run_result(0, stdout="feature-y\n")
            return _make_run_result(0, stdout="main\n")

        if "status" in cmd and "--porcelain" in cmd:
            # api clean, web dirty, worker clean
            if "web" in cwd:
                return _make_run_result(0, stdout=" M file.py\n")
            return _make_run_result(0, stdout="")

        if "rev-list" in cmd and "--left-right" in cmd:
            # api: ahead 1, worker: behind 1
            if "api" in cwd:
                return _make_run_result(0, stdout="0\t1\n")
            if "worker" in cwd:
                return _make_run_result(0, stdout="1\t0\n")
            return _make_run_result(0, stdout="0\t0\n")

        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == 3
    # web: dirty + misaligned, worker: behind
    assert result["issues"] == 2
    assert result["ok"] is False
    assert "2/3" in result["summary"]

    api = result["projects"][0]
    assert api["name"] == "api"
    assert api["dirty"] is False
    assert api["branch_ok"] is True
    assert api["ahead"] == 1

    web = result["projects"][1]
    assert web["name"] == "web"
    assert web["dirty"] is True
    assert web["branch_ok"] is False

    worker = result["projects"][2]
    assert worker["name"] == "worker"
    assert worker["behind"] == 1


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_returns_all_fields_per_project(mock_run, tmp_hub):
    """Every project entry has the complete set of required fields."""
    for name in ["svc-a", "svc-b", "svc-c", "svc-d", "svc-e"]:
        _register_subproject(tmp_hub, name)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    required_fields = {"name", "branch", "tracking_branch", "dirty",
                       "ahead", "behind", "branch_ok", "exists"}

    assert result["total"] == 5
    for proj in result["projects"]:
        assert required_fields.issubset(proj.keys()), (
            f"Project {proj['name']} missing fields: "
            f"{required_fields - proj.keys()}"
        )


@patch("projectman.hub.registry.subprocess.run")
def test_git_status_all_summary_all_clean(mock_run, tmp_hub):
    """Summary says 'All N projects clean' when no issues."""
    _register_subproject(tmp_hub, "api")
    _register_subproject(tmp_hub, "web")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        r = _make_run_result(0)
        if kwargs.get("check") and r.returncode != 0:
            raise subprocess.CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr,
            )
        return r

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["ok"] is True
    assert "All 2 projects clean" in result["summary"]


# ─── US-PRJ-8-2: branch/dirty/ahead-behind/PR status per repo ───


@patch("projectman.hub.registry.subprocess.run")
def test_per_repo_branch_status(mock_run, tmp_hub):
    """Each repo reports its own branch and tracking branch independently."""
    _register_subproject(tmp_hub, "alpha", prefix="ALP")
    _register_subproject(tmp_hub, "beta", prefix="BET")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "alpha" in cwd:
                return _make_run_result(0, stdout="main\n")
            return _make_run_result(0, stdout="develop\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    alpha = result["projects"][0]
    beta = result["projects"][1]

    assert alpha["branch"] == "main"
    assert alpha["branch_ok"] is True
    assert beta["branch"] == "develop"
    assert beta["tracking_branch"] == "main"
    assert beta["branch_ok"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_per_repo_dirty_status(mock_run, tmp_hub):
    """Dirty flag is tracked independently per repo."""
    _register_subproject(tmp_hub, "clean-svc", prefix="CLN")
    _register_subproject(tmp_hub, "dirty-svc", prefix="DRT")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            if "dirty-svc" in cwd:
                return _make_run_result(0, stdout=" M app.py\n?? tmp.log\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    clean = result["projects"][0]
    dirty = result["projects"][1]

    assert clean["dirty"] is False
    assert dirty["dirty"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_per_repo_ahead_behind_independent(mock_run, tmp_hub):
    """Each repo reports its own ahead/behind counts independently."""
    _register_subproject(tmp_hub, "ahead-only", prefix="AHD")
    _register_subproject(tmp_hub, "behind-only", prefix="BHD")
    _register_subproject(tmp_hub, "both", prefix="BTH")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "ahead-only" in cwd:
                return _make_run_result(0, stdout="0\t5\n")
            if "behind-only" in cwd:
                return _make_run_result(0, stdout="3\t0\n")
            if "both" in cwd:
                return _make_run_result(0, stdout="2\t4\n")
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    ahead_only = result["projects"][0]
    behind_only = result["projects"][1]
    both = result["projects"][2]

    assert ahead_only["ahead"] == 5
    assert ahead_only["behind"] == 0
    assert behind_only["ahead"] == 0
    assert behind_only["behind"] == 3
    assert both["ahead"] == 4
    assert both["behind"] == 2


@patch("projectman.hub.registry.subprocess.run")
def test_per_repo_all_status_fields_distinct(mock_run, tmp_hub):
    """Full integration: each repo has distinct branch/dirty/ahead/behind values."""
    _register_subproject(tmp_hub, "svc-ok", prefix="SOK")
    _register_subproject(tmp_hub, "svc-messy", prefix="SMS")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "svc-ok" in cwd:
                return _make_run_result(0, stdout="main\n")
            return _make_run_result(0, stdout="hotfix-123\n")
        if "status" in cmd and "--porcelain" in cmd:
            if "svc-messy" in cwd:
                return _make_run_result(0, stdout=" M broken.py\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "svc-ok" in cwd:
                return _make_run_result(0, stdout="0\t0\n")
            return _make_run_result(0, stdout="1\t2\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    ok = result["projects"][0]
    assert ok["name"] == "svc-ok"
    assert ok["branch"] == "main"
    assert ok["dirty"] is False
    assert ok["ahead"] == 0
    assert ok["behind"] == 0
    assert ok["branch_ok"] is True

    messy = result["projects"][1]
    assert messy["name"] == "svc-messy"
    assert messy["branch"] == "hotfix-123"
    assert messy["dirty"] is True
    assert messy["ahead"] == 2
    assert messy["behind"] == 1
    assert messy["branch_ok"] is False

    # svc-ok should not count as an issue, svc-messy should
    assert result["issues"] == 1


# ─── US-PRJ-8-3: Highlights mismatches and issues ───────────────


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_branch_mismatch_flagged_as_issue(mock_run, tmp_hub):
    """Branch mismatch sets branch_ok=False and increments issues count."""
    _register_subproject(tmp_hub, "drifted", prefix="DFT")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="release/v2\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # Mismatch is highlighted
    assert proj["branch_ok"] is False
    assert proj["branch"] == "release/v2"
    assert proj["tracking_branch"] == "main"
    # Counts toward issues
    assert result["issues"] == 1
    assert result["ok"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_dirty_flagged_as_issue(mock_run, tmp_hub):
    """Dirty working tree is highlighted and counted as an issue."""
    _register_subproject(tmp_hub, "messy", prefix="MSY")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M foo.py\n?? bar.log\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["dirty"] is True
    assert proj["branch_ok"] is True  # branch is fine
    assert result["issues"] == 1
    assert result["ok"] is False


def test_highlight_missing_dir_flagged_as_issue(tmp_hub):
    """Missing project directory is highlighted with exists=False and counted."""
    _register_subproject(tmp_hub, "phantom", prefix="PH")
    import shutil
    shutil.rmtree(tmp_hub / "projects" / "phantom")

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["exists"] is False
    assert proj["branch_ok"] is False
    assert result["issues"] == 1
    assert result["ok"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_behind_remote_flagged_as_issue(mock_run, tmp_hub):
    """Being behind remote is highlighted as an issue even if branch matches."""
    _register_subproject(tmp_hub, "stale", prefix="STL")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="5\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["behind"] == 5
    assert proj["branch_ok"] is True
    assert proj["dirty"] is False
    # Behind alone is enough to be an issue
    assert result["issues"] == 1
    assert result["ok"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_ahead_only_is_not_an_issue(mock_run, tmp_hub):
    """Being ahead of remote is NOT flagged as an issue (local work is fine)."""
    _register_subproject(tmp_hub, "active", prefix="ACT")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t3\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["ahead"] == 3
    assert proj["behind"] == 0
    # Ahead-only is not an issue
    assert result["issues"] == 0
    assert result["ok"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_multiple_issues_counted_per_project(mock_run, tmp_hub):
    """A project with multiple problems (dirty + misaligned + behind) counts as 1 issue."""
    _register_subproject(tmp_hub, "train-wreck", prefix="TW")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="experiment\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M a.py\n M b.py\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="3\t1\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # All three issue types present
    assert proj["dirty"] is True
    assert proj["branch_ok"] is False
    assert proj["behind"] == 3
    # But it counts as 1 project with issues, not 3
    assert result["issues"] == 1
    assert result["ok"] is False


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_summary_shows_issue_count(mock_run, tmp_hub):
    """Summary string includes the ratio of problematic vs total projects."""
    _register_subproject(tmp_hub, "ok-proj", prefix="OK")
    _register_subproject(tmp_hub, "bad-proj", prefix="BAD")
    _register_subproject(tmp_hub, "ok-proj2", prefix="OK2")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "bad-proj" in cwd:
                return _make_run_result(0, stdout="wrong-branch\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["issues"] == 1
    assert result["ok"] is False
    assert "1/3" in result["summary"]
    assert "attention" in result["summary"].lower()


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_clean_projects_not_flagged(mock_run, tmp_hub):
    """Clean projects have no issue flags and don't increment issues count."""
    _register_subproject(tmp_hub, "pristine", prefix="PRS")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["dirty"] is False
    assert proj["branch_ok"] is True
    assert proj["ahead"] == 0
    assert proj["behind"] == 0
    assert proj["exists"] is True
    assert result["issues"] == 0
    assert result["ok"] is True
    assert "clean" in result["summary"].lower()


@patch("projectman.hub.registry.subprocess.run")
def test_highlight_mixed_issues_across_projects(mock_run, tmp_hub):
    """Different issue types across projects are each highlighted correctly."""
    _register_subproject(tmp_hub, "clean", prefix="CLN")
    _register_subproject(tmp_hub, "dirty-only", prefix="DO")
    _register_subproject(tmp_hub, "wrong-branch", prefix="WB")
    _register_subproject(tmp_hub, "behind-only", prefix="BO")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "wrong-branch" in cwd:
                return _make_run_result(0, stdout="feat-x\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            if "dirty-only" in cwd:
                return _make_run_result(0, stdout=" M file.py\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "behind-only" in cwd:
                return _make_run_result(0, stdout="2\t0\n")
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    clean = next(p for p in result["projects"] if p["name"] == "clean")
    dirty = next(p for p in result["projects"] if p["name"] == "dirty-only")
    wrong = next(p for p in result["projects"] if p["name"] == "wrong-branch")
    behind = next(p for p in result["projects"] if p["name"] == "behind-only")

    # Clean has no issues
    assert clean["dirty"] is False and clean["branch_ok"] is True and clean["behind"] == 0

    # Each issue type is highlighted independently
    assert dirty["dirty"] is True and dirty["branch_ok"] is True and dirty["behind"] == 0
    assert wrong["dirty"] is False and wrong["branch_ok"] is False and wrong["behind"] == 0
    assert behind["dirty"] is False and behind["branch_ok"] is True and behind["behind"] == 2

    # 3 out of 4 have issues
    assert result["issues"] == 3
    assert result["ok"] is False
    assert "3/4" in result["summary"]


# ─── US-PRJ-8-4: Scales to 20+ submodules without clutter ────


@patch("projectman.hub.registry.subprocess.run")
def test_scales_to_25_submodules_all_clean(mock_run, tmp_hub):
    """25 clean submodules are all reported with correct fields in one call."""
    names = [f"svc-{i:02d}" for i in range(25)]
    for name in names:
        _register_subproject(tmp_hub, name)

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == 25
    assert result["ok"] is True
    assert result["issues"] == 0
    assert len(result["projects"]) == 25
    assert "All 25 projects clean" in result["summary"]

    # Every project has the full set of required fields
    required = {"name", "branch", "tracking_branch", "dirty",
                "ahead", "behind", "branch_ok", "exists"}
    for proj in result["projects"]:
        assert required.issubset(proj.keys())

    # Ordering preserved
    assert [p["name"] for p in result["projects"]] == names


@patch("projectman.hub.registry.subprocess.run")
def test_scales_to_30_submodules_mixed_states(mock_run, tmp_hub):
    """30 submodules with mixed states: issues counted correctly, all reported."""
    names = [f"proj-{i:02d}" for i in range(30)]
    for name in names:
        _register_subproject(tmp_hub, name)

    # Even-indexed projects are dirty, every 5th has branch mismatch
    dirty_set = {f"proj-{i:02d}" for i in range(0, 30, 2)}
    misaligned_set = {f"proj-{i:02d}" for i in range(0, 30, 5)}

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            for name in misaligned_set:
                if name in cwd:
                    return _make_run_result(0, stdout="feature\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            for name in dirty_set:
                if name in cwd:
                    return _make_run_result(0, stdout=" M file.py\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == 30
    assert len(result["projects"]) == 30

    # Count expected issues: union of dirty and misaligned
    expected_issues = dirty_set | misaligned_set
    assert result["issues"] == len(expected_issues)
    assert result["ok"] is False
    assert f"{len(expected_issues)}/30" in result["summary"]

    # Verify per-project state is correct
    for proj in result["projects"]:
        if proj["name"] in dirty_set:
            assert proj["dirty"] is True
        else:
            assert proj["dirty"] is False
        if proj["name"] in misaligned_set:
            assert proj["branch_ok"] is False
        else:
            assert proj["branch_ok"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_scales_summary_stays_concise_at_25(mock_run, tmp_hub):
    """Summary for 25 projects is a single-line ratio, not a per-project dump."""
    for i in range(25):
        _register_subproject(tmp_hub, f"svc-{i:02d}")

    # 5 projects dirty
    dirty_indices = set(range(0, 25, 5))

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            for i in dirty_indices:
                if f"svc-{i:02d}" in cwd:
                    return _make_run_result(0, stdout=" M x.py\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    # Summary is concise — single line with ratio
    assert result["summary"].count("\n") == 0
    assert "5/25" in result["summary"]
    # Summary does NOT list individual project names
    for i in range(25):
        assert f"svc-{i:02d}" not in result["summary"]


@patch("projectman.hub.registry.subprocess.run")
def test_scales_each_project_has_independent_state_at_20_plus(mock_run, tmp_hub):
    """At 20+ submodules, each project maintains its own independent state."""
    count = 22
    names = [f"micro-{i:02d}" for i in range(count)]
    for name in names:
        _register_subproject(tmp_hub, name)

    # Each project gets unique ahead/behind values based on index
    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            for i, name in enumerate(names):
                if name in cwd:
                    return _make_run_result(0, stdout=f"0\t{i}\n")
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == count
    # Verify each project got its own unique ahead value
    for i, proj in enumerate(result["projects"]):
        assert proj["name"] == names[i]
        assert proj["ahead"] == i


def test_scales_with_missing_dirs_among_20_plus(tmp_hub):
    """Handles missing directories gracefully within 20+ submodules."""
    import shutil

    names = [f"app-{i:02d}" for i in range(24)]
    for name in names:
        _register_subproject(tmp_hub, name)

    # Remove every 4th project directory
    removed = set()
    for i in range(0, 24, 4):
        shutil.rmtree(tmp_hub / "projects" / names[i])
        removed.add(names[i])

    with patch("projectman.hub.registry.subprocess.run") as mock_run:
        def dispatcher(cmd, **kwargs):
            if "config" in cmd and ".gitmodules" in cmd:
                return _make_run_result(0, stdout="main\n")
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return _make_run_result(0, stdout="main\n")
            if "status" in cmd and "--porcelain" in cmd:
                return _make_run_result(0, stdout="")
            if "rev-list" in cmd and "--left-right" in cmd:
                return _make_run_result(0, stdout="0\t0\n")
            return _make_run_result(0)

        mock_run.side_effect = dispatcher

        result = git_status_all(root=tmp_hub)

    assert result["total"] == 24
    assert len(result["projects"]) == 24
    # 6 removed dirs (indices 0, 4, 8, 12, 16, 20) are issues
    assert result["issues"] == len(removed)
    assert result["ok"] is False

    for proj in result["projects"]:
        if proj["name"] in removed:
            assert proj["exists"] is False
        else:
            assert proj["exists"] is True


# ─── US-PRJ-8-5: Core data collection enhancements ───────────


@patch("projectman.hub.registry.subprocess.run")
def test_deploy_branch_from_config(mock_run, tmp_hub):
    """deploy_branch is read from per-project PM config."""
    pm_dir = _register_subproject(tmp_hub, "api", prefix="API")
    # Write deploy_branch into the subproject config
    config_path = pm_dir / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["deploy_branch"] = "production"
    config_path.write_text(yaml.dump(data))

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="production\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="abc123|2026-02-28 12:00:00 +0000|Dev|feat: init\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["deploy_branch"] == "production"
    assert proj["aligned"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_aligned_false_when_not_on_deploy_branch(mock_run, tmp_hub):
    """aligned is False when current branch differs from deploy branch."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="abc|2026-01-01 00:00:00|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["aligned"] is False
    assert proj["deploy_branch"] == "main"  # fallback


@patch("projectman.hub.registry.subprocess.run")
def test_dirty_count_tracks_file_count(mock_run, tmp_hub):
    """dirty_count reflects the number of changed/untracked files."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M a.py\n M b.py\n?? c.log\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["dirty"] is True
    assert proj["dirty_count"] == 3


@patch("projectman.hub.registry.subprocess.run")
def test_dirty_count_zero_when_clean(mock_run, tmp_hub):
    """dirty_count is 0 for a clean working tree."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["dirty"] is False
    assert proj["dirty_count"] == 0


@patch("projectman.hub.registry.subprocess.run")
def test_detached_head_detected(mock_run, tmp_hub):
    """Detached HEAD is reported via detached=True."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="HEAD\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["detached"] is True
    assert proj["aligned"] is False
    assert any("Detached" in i for i in proj["issues"])


@patch("projectman.hub.registry.subprocess.run")
def test_last_commit_fields(mock_run, tmp_hub):
    """last_commit dict contains sha, date, author, message."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(
                0, stdout="abcdef1234|2026-02-28 14:30:00 +0000|Alice|feat: add auth\n"
            )
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    lc = result["projects"][0]["last_commit"]
    assert lc["sha"] == "abcdef1234"
    assert "2026-02-28" in lc["date"]
    assert lc["author"] == "Alice"
    assert lc["message"] == "feat: add auth"


@patch("projectman.hub.registry.subprocess.run")
def test_issues_list_per_project(mock_run, tmp_hub):
    """Per-project issues list contains human-readable problem strings."""
    _register_subproject(tmp_hub, "messy", prefix="MSY")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-x\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M a.py\n?? b.log\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="3\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert isinstance(proj["issues"], list)
    assert len(proj["issues"]) >= 2  # dirty + branch mismatch + behind
    assert any("Dirty" in i for i in proj["issues"])
    assert any("behind" in i.lower() for i in proj["issues"])


@patch("projectman.hub.registry.subprocess.run")
def test_clean_project_has_empty_issues_list(mock_run, tmp_hub):
    """A clean, aligned project has an empty issues list."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["issues"] == []
    assert proj["dirty_count"] == 0
    assert proj["detached"] is False
    assert proj["aligned"] is True


def test_missing_project_has_issues_list(tmp_hub):
    """Missing directory project has issues list with 'missing' message."""
    import shutil
    _register_subproject(tmp_hub, "gone")
    shutil.rmtree(tmp_hub / "projects" / "gone")

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["exists"] is False
    assert isinstance(proj["issues"], list)
    assert len(proj["issues"]) >= 1
    assert any("missing" in i.lower() or "Missing" in i for i in proj["issues"])


@patch("projectman.hub.registry.subprocess.run")
def test_all_new_fields_present_at_scale(mock_run, tmp_hub):
    """All new fields (deploy_branch, aligned, dirty_count, detached, last_commit, issues)
    are present for every project at 20+ scale."""
    for i in range(22):
        _register_subproject(tmp_hub, f"svc-{i:02d}")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["total"] == 22

    new_fields = {"deploy_branch", "aligned", "dirty_count", "detached",
                  "last_commit", "issues"}
    for proj in result["projects"]:
        assert new_fields.issubset(proj.keys()), (
            f"Project {proj['name']} missing: {new_fields - proj.keys()}"
        )
        assert isinstance(proj["last_commit"], dict)
        assert {"sha", "date", "author", "message"} == set(proj["last_commit"].keys())
        assert isinstance(proj["issues"], list)


# ─── PR status collection (US-PRJ-8-6) ───────────────────────────


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_present_when_gh_returns_prs(mock_run, tmp_hub):
    """open_prs count and prs list populated from gh pr list output."""
    import json

    _register_subproject(tmp_hub, "api", prefix="API")

    pr_json = json.dumps([
        {"number": 42, "title": "Add feature", "headRefName": "feat-x",
         "isDraft": False, "updatedAt": "2026-02-28T10:00:00Z"},
        {"number": 43, "title": "Fix bug", "headRefName": "fix-y",
         "isDraft": True, "updatedAt": "2026-02-27T08:00:00Z"},
    ])

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout=pr_json)
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["open_prs"] == 2
    assert len(proj["prs"]) == 2
    assert proj["prs"][0]["number"] == 42
    assert proj["prs"][0]["title"] == "Add feature"
    assert proj["prs"][0]["branch"] == "feat-x"
    assert proj["prs"][0]["draft"] is False
    assert proj["prs"][0]["updated"] == "2026-02-28T10:00:00Z"
    assert proj["prs"][1]["number"] == 43
    assert proj["prs"][1]["draft"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_empty_when_no_open_prs(mock_run, tmp_hub):
    """No open PRs returns open_prs=0 and empty prs list."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["open_prs"] == 0
    assert proj["prs"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_graceful_when_gh_not_installed(mock_run, tmp_hub):
    """When gh CLI is missing, PR fields default to empty without errors."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd:
            raise FileNotFoundError("gh not found")
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["open_prs"] == 0
    assert proj["prs"] == []
    # Core status still works
    assert proj["branch"] == "main"
    assert proj["exists"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_graceful_when_gh_not_authenticated(mock_run, tmp_hub):
    """When gh CLI is not authenticated, PR fields default to empty."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(1, stderr="gh auth login required")
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["open_prs"] == 0
    assert proj["prs"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_graceful_on_invalid_json(mock_run, tmp_hub):
    """Malformed JSON from gh returns empty PR data."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="not json at all")
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["open_prs"] == 0
    assert proj["prs"] == []


def test_pr_fields_present_for_missing_project(tmp_hub):
    """Missing project directory still includes PR fields (zeroed out)."""
    from projectman.config import load_config, save_config

    cfg = load_config(tmp_hub)
    cfg.projects.append("ghost")
    save_config(cfg, tmp_hub)

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]
    assert proj["name"] == "ghost"
    assert proj["exists"] is False
    assert proj["open_prs"] == 0
    assert proj["prs"] == []


@patch("projectman.hub.registry.subprocess.run")
def test_pr_fields_present_at_scale(mock_run, tmp_hub):
    """PR fields present on every project at 20+ scale."""
    for i in range(22):
        _register_subproject(tmp_hub, f"svc-{i:02d}")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="0\t0\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    assert result["total"] == 22

    for proj in result["projects"]:
        assert "open_prs" in proj, f"{proj['name']} missing open_prs"
        assert "prs" in proj, f"{proj['name']} missing prs"
        assert isinstance(proj["open_prs"], int)
        assert isinstance(proj["prs"], list)
