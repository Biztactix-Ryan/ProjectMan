"""Tests for hub git status dashboard — US-PRJ-8-9.

Eight focused scenarios covering data collection, formatting, and edge cases:

1. All clean: 3 subprojects on deploy branch, clean, up to date → no issues
2. Mixed state: one dirty, one misaligned, one behind → correct issues, sorted by severity
3. Detached HEAD: submodule in detached state → detected and reported
4. Ahead/behind counts: subproject 3 ahead, 2 behind → correct counts
5. Missing project: registered but dir missing → reported, doesn't crash
6. No remote: subproject has no remote → ahead/behind 0, doesn't crash
7. 20+ projects: parallel git calls complete in reasonable time
8. PR data unavailable: gh not installed or not authed → graceful degradation
"""

import json
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest
import yaml

from projectman.hub.registry import (
    format_git_status,
    git_status_all,
)


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


def _clean_dispatcher(cmd, **kwargs):
    """Dispatcher that returns all-clean git state for any project."""
    if "config" in cmd and ".gitmodules" in cmd:
        return _make_run_result(0, stdout="main\n")
    if "rev-parse" in cmd and "--abbrev-ref" in cmd:
        return _make_run_result(0, stdout="main\n")
    if "status" in cmd and "--porcelain" in cmd:
        return _make_run_result(0, stdout="")
    if "rev-list" in cmd and "--left-right" in cmd:
        return _make_run_result(0, stdout="0\t0\n")
    if "log" in cmd and "--format" in str(cmd):
        return _make_run_result(0, stdout="abc123|2026-02-28 12:00:00|Dev|feat: init\n")
    if "gh" in cmd and "pr" in cmd:
        return _make_run_result(0, stdout="[]")
    return _make_run_result(0)


# ─── 1. All clean: 3 subprojects on deploy branch, clean, up to date ──


@patch("projectman.hub.registry.subprocess.run")
def test_all_clean_three_projects(mock_run, tmp_hub):
    """3 subprojects all on deploy branch, clean, up to date → no issues."""
    _register_subproject(tmp_hub, "api", prefix="API")
    _register_subproject(tmp_hub, "web", prefix="WEB")
    _register_subproject(tmp_hub, "worker", prefix="WRK")

    mock_run.side_effect = _clean_dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == 3
    assert result["issues"] == 0
    assert result["ok"] is True
    assert "All 3 projects clean" in result["summary"]

    for proj in result["projects"]:
        assert proj["exists"] is True
        assert proj["dirty"] is False
        assert proj["dirty_count"] == 0
        assert proj["branch"] == "main"
        assert proj["branch_ok"] is True
        assert proj["aligned"] is True
        assert proj["detached"] is False
        assert proj["ahead"] == 0
        assert proj["behind"] == 0
        assert proj["issues"] == []


# ─── 2. Mixed state: dirty, misaligned, behind → sorted by severity ──


@patch("projectman.hub.registry.subprocess.run")
def test_mixed_state_correct_issues_and_severity(mock_run, tmp_hub):
    """One dirty, one misaligned, one behind → each flagged correctly."""
    _register_subproject(tmp_hub, "dirty-svc", prefix="DRT")
    _register_subproject(tmp_hub, "wrong-branch", prefix="WBR")
    _register_subproject(tmp_hub, "behind-svc", prefix="BHD")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))

        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "wrong-branch" in cwd:
                return _make_run_result(0, stdout="feature-x\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            if "dirty-svc" in cwd:
                return _make_run_result(0, stdout=" M app.py\n?? tmp.log\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "behind-svc" in cwd:
                return _make_run_result(0, stdout="4\t0\n")
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    # All 3 have issues
    assert result["issues"] == 3
    assert result["ok"] is False
    assert "3/3" in result["summary"]

    dirty = next(p for p in result["projects"] if p["name"] == "dirty-svc")
    wrong = next(p for p in result["projects"] if p["name"] == "wrong-branch")
    behind = next(p for p in result["projects"] if p["name"] == "behind-svc")

    assert dirty["dirty"] is True
    assert dirty["dirty_count"] == 2
    assert any("Dirty" in i for i in dirty["issues"])

    assert wrong["branch_ok"] is False
    assert wrong["branch"] == "feature-x"
    assert wrong["tracking_branch"] == "main"
    assert any("mismatch" in i.lower() or "Branch" in i for i in wrong["issues"])

    assert behind["behind"] == 4
    assert any("behind" in i.lower() for i in behind["issues"])


@patch("projectman.hub.registry.subprocess.run")
def test_mixed_state_format_sorted_by_severity(mock_run, tmp_hub):
    """format_git_status sorts projects by severity: misaligned before dirty before behind."""
    _register_subproject(tmp_hub, "dirty-svc", prefix="DRT")
    _register_subproject(tmp_hub, "wrong-branch", prefix="WBR")
    _register_subproject(tmp_hub, "behind-svc", prefix="BHD")
    _register_subproject(tmp_hub, "clean-svc", prefix="CLN")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))

        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            if "wrong-branch" in cwd:
                return _make_run_result(0, stdout="feature-x\n")
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            if "dirty-svc" in cwd:
                return _make_run_result(0, stdout=" M app.py\n")
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "behind-svc" in cwd:
                return _make_run_result(0, stdout="2\t0\n")
            return _make_run_result(0, stdout="0\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    data = git_status_all(root=tmp_hub)
    output = format_git_status(data)

    # Verify the formatted output has projects sorted by severity:
    # wrong-branch (severity 2) before dirty-svc (severity 3) before
    # behind-svc (severity 4) before clean-svc (severity 10)
    wrong_pos = output.find("wrong-branch")
    dirty_pos = output.find("dirty-svc")
    behind_pos = output.find("behind-svc")
    clean_pos = output.find("clean-svc")

    assert wrong_pos < dirty_pos, "misaligned should appear before dirty"
    assert dirty_pos < behind_pos, "dirty should appear before behind"
    assert behind_pos < clean_pos, "behind should appear before clean"


# ─── 3. Detached HEAD → detected and reported ──


@patch("projectman.hub.registry.subprocess.run")
def test_detached_head_detected_and_reported(mock_run, tmp_hub):
    """Submodule in detached HEAD state is detected and reported as an issue."""
    _register_subproject(tmp_hub, "detached-svc", prefix="DET")

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
            return _make_run_result(0, stdout="abc|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["detached"] is True
    assert proj["aligned"] is False
    assert proj["branch"] == "HEAD"
    assert any("Detached" in issue for issue in proj["issues"])
    assert result["ok"] is False
    assert result["issues"] == 1


@patch("projectman.hub.registry.subprocess.run")
def test_detached_head_format_output(mock_run, tmp_hub):
    """Detached HEAD is shown with parentheses in formatted output."""
    _register_subproject(tmp_hub, "detached-svc", prefix="DET")

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
            return _make_run_result(0, stdout="abc|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    data = git_status_all(root=tmp_hub)
    output = format_git_status(data)

    # Detached HEAD shows branch as (HEAD) in parentheses
    assert "(HEAD)" in output


# ─── 4. Ahead/behind counts: 3 ahead, 2 behind → correct counts ──


@patch("projectman.hub.registry.subprocess.run")
def test_ahead_behind_counts(mock_run, tmp_hub):
    """Subproject with 3 ahead and 2 behind reports correct counts."""
    _register_subproject(tmp_hub, "diverged", prefix="DIV")

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
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    assert proj["ahead"] == 3
    assert proj["behind"] == 2
    # Behind means an issue
    assert result["ok"] is False
    assert result["issues"] == 1
    assert any("behind" in i.lower() for i in proj["issues"])


@patch("projectman.hub.registry.subprocess.run")
def test_ahead_behind_format_output(mock_run, tmp_hub):
    """Ahead/behind counts appear in formatted table output."""
    _register_subproject(tmp_hub, "diverged", prefix="DIV")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="2\t3\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    data = git_status_all(root=tmp_hub)
    output = format_git_status(data)

    # Ahead/behind rendered as ahead/behind in table
    assert "3/2" in output


# ─── 5. Missing project: registered but dir missing → doesn't crash ──


def test_missing_project_reported_no_crash(tmp_hub):
    """Registered project with missing directory is reported, doesn't crash."""
    import shutil

    _register_subproject(tmp_hub, "present")
    _register_subproject(tmp_hub, "gone")
    shutil.rmtree(tmp_hub / "projects" / "gone")

    with patch("projectman.hub.registry.subprocess.run") as mock_run:
        mock_run.side_effect = _clean_dispatcher

        result = git_status_all(root=tmp_hub)

    assert result["total"] == 2
    assert result["ok"] is False

    present = next(p for p in result["projects"] if p["name"] == "present")
    gone = next(p for p in result["projects"] if p["name"] == "gone")

    assert present["exists"] is True
    assert present["issues"] == []

    assert gone["exists"] is False
    assert gone["branch_ok"] is False
    assert gone["branch"] == ""
    assert gone["dirty"] is False
    assert gone["ahead"] == 0
    assert gone["behind"] == 0
    assert gone["open_prs"] == 0
    assert gone["prs"] == []
    assert any("missing" in i.lower() or "Missing" in i for i in gone["issues"])


def test_missing_project_format_output(tmp_hub):
    """Missing project shows in formatted output with verbose details."""
    import shutil

    _register_subproject(tmp_hub, "gone")
    shutil.rmtree(tmp_hub / "projects" / "gone")

    result = git_status_all(root=tmp_hub)
    output = format_git_status(result, verbose=True)

    assert "gone" in output
    assert "MISSING" in output


# ─── 6. No remote: no remote configured → ahead/behind 0, no crash ──


@patch("projectman.hub.registry.subprocess.run")
def test_no_remote_ahead_behind_zero(mock_run, tmp_hub):
    """Subproject with no remote returns ahead=0, behind=0 without crashing."""
    _register_subproject(tmp_hub, "local-only", prefix="LOC")

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            # No remote → git returns error
            return _make_run_result(128, stderr="fatal: ambiguous argument 'origin/main...main'\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # No crash — ahead/behind default to 0
    assert proj["ahead"] == 0
    assert proj["behind"] == 0
    assert proj["exists"] is True
    assert proj["branch"] == "main"
    # Core status still works fine
    assert proj["dirty"] is False
    assert proj["branch_ok"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_no_remote_mixed_with_normal_projects(mock_run, tmp_hub):
    """A no-remote project alongside a normal one doesn't affect the other."""
    _register_subproject(tmp_hub, "local-only", prefix="LOC")
    _register_subproject(tmp_hub, "has-remote", prefix="RMT")

    def dispatcher(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))

        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            if "local-only" in cwd:
                # No remote
                return _make_run_result(128, stderr="fatal: no remote\n")
            # Normal project: 1 ahead
            return _make_run_result(0, stdout="0\t1\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)

    local = next(p for p in result["projects"] if p["name"] == "local-only")
    remote = next(p for p in result["projects"] if p["name"] == "has-remote")

    assert local["ahead"] == 0
    assert local["behind"] == 0
    assert remote["ahead"] == 1
    assert remote["behind"] == 0


@patch("projectman.hub.registry.subprocess.run")
def test_no_remote_git_raises_os_error(mock_run, tmp_hub):
    """OSError during rev-list (e.g. git not found) doesn't crash."""
    _register_subproject(tmp_hub, "broken", prefix="BRK")

    call_count = {"n": 0}

    def dispatcher(cmd, **kwargs):
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout="")
        if "rev-list" in cmd and "--left-right" in cmd:
            raise OSError("git not available")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # Graceful degradation
    assert proj["ahead"] == 0
    assert proj["behind"] == 0
    assert proj["exists"] is True


# ─── 7. 20+ projects: parallel git calls in reasonable time ──


@patch("projectman.hub.registry.subprocess.run")
def test_twenty_plus_projects_parallel_performance(mock_run, tmp_hub):
    """20+ submodules complete in reasonable time (parallel execution)."""
    count = 25
    names = [f"svc-{i:02d}" for i in range(count)]
    for name in names:
        _register_subproject(tmp_hub, name)

    def slow_dispatcher(cmd, **kwargs):
        """Simulate a 50ms delay per git call to verify parallelism."""
        time.sleep(0.05)
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
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="[]")
        return _make_run_result(0)

    mock_run.side_effect = slow_dispatcher

    start = time.monotonic()
    result = git_status_all(root=tmp_hub)
    elapsed = time.monotonic() - start

    assert result["total"] == count
    assert result["ok"] is True
    assert len(result["projects"]) == count

    # Sequential 50ms × ~7 calls × 25 projects = ~8.75s
    # Parallel with 16 workers should be much faster
    # Allow generous 5s for slow CI environments
    assert elapsed < 5.0, f"Took {elapsed:.1f}s — should be faster with parallelism"


@patch("projectman.hub.registry.subprocess.run")
def test_twenty_plus_projects_all_fields_present(mock_run, tmp_hub):
    """All required fields present on every project at 20+ scale."""
    count = 22
    for i in range(count):
        _register_subproject(tmp_hub, f"app-{i:02d}")

    mock_run.side_effect = _clean_dispatcher

    result = git_status_all(root=tmp_hub)

    assert result["total"] == count

    all_fields = {
        "name", "branch", "tracking_branch", "deploy_branch", "aligned",
        "dirty", "dirty_count", "ahead", "behind", "detached",
        "last_commit", "branch_ok", "exists", "issues", "open_prs", "prs",
    }
    for proj in result["projects"]:
        assert all_fields.issubset(proj.keys()), (
            f"Project {proj['name']} missing: {all_fields - proj.keys()}"
        )
        assert isinstance(proj["last_commit"], dict)
        assert isinstance(proj["issues"], list)
        assert isinstance(proj["prs"], list)


# ─── 8. PR data unavailable: gh not installed or not authed ──


@patch("projectman.hub.registry.subprocess.run")
def test_pr_unavailable_gh_not_installed(mock_run, tmp_hub):
    """gh CLI not installed → PR fields default to empty, core status works."""
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
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # PR fields gracefully empty
    assert proj["open_prs"] == 0
    assert proj["prs"] == []
    # Core status still works
    assert proj["branch"] == "main"
    assert proj["dirty"] is False
    assert proj["exists"] is True
    assert proj["aligned"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_pr_unavailable_gh_not_authenticated(mock_run, tmp_hub):
    """gh CLI not authenticated → PR fields empty, core status works."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(1, stderr="gh: auth login required")
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

    assert proj["open_prs"] == 0
    assert proj["prs"] == []
    # Core status unaffected
    assert proj["branch"] == "main"
    assert proj["exists"] is True


@patch("projectman.hub.registry.subprocess.run")
def test_pr_unavailable_malformed_json(mock_run, tmp_hub):
    """Malformed JSON from gh → PR fields empty, no crash."""
    _register_subproject(tmp_hub, "api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd and "pr" in cmd:
            return _make_run_result(0, stdout="this is not json")
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

    assert proj["open_prs"] == 0
    assert proj["prs"] == []
    assert proj["branch"] == "main"


@patch("projectman.hub.registry.subprocess.run")
def test_pr_unavailable_core_status_with_issues_still_detected(mock_run, tmp_hub):
    """Even when gh fails, dirty/branch issues are still detected correctly."""
    _register_subproject(tmp_hub, "messy-api", prefix="API")

    def dispatcher(cmd, **kwargs):
        if "gh" in cmd:
            raise FileNotFoundError("gh not found")
        if "config" in cmd and ".gitmodules" in cmd:
            return _make_run_result(0, stdout="main\n")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return _make_run_result(0, stdout="feature-y\n")
        if "status" in cmd and "--porcelain" in cmd:
            return _make_run_result(0, stdout=" M dirty.py\n")
        if "rev-list" in cmd and "--left-right" in cmd:
            return _make_run_result(0, stdout="1\t0\n")
        if "log" in cmd and "--format" in str(cmd):
            return _make_run_result(0, stdout="sha|2026-01-01|Dev|msg\n")
        return _make_run_result(0)

    mock_run.side_effect = dispatcher

    result = git_status_all(root=tmp_hub)
    proj = result["projects"][0]

    # PR data gracefully empty
    assert proj["open_prs"] == 0
    assert proj["prs"] == []
    # But all other issues are detected
    assert proj["dirty"] is True
    assert proj["branch_ok"] is False
    assert proj["behind"] == 1
    assert result["ok"] is False
    assert result["issues"] == 1
    assert len(proj["issues"]) >= 2
