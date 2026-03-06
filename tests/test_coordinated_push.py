"""Test: Single command pushes across hub + N subprojects (US-PRJ-4-1).

Verifies acceptance criterion for story US-PRJ-4:
    > Single command pushes across hub + N subprojects

Uses real git repos with bare remotes to verify end-to-end push behavior.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import pm_push


# ─── Helpers ──────────────────────────────────────────────────────

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
}


def _git(args, cwd, check=True):
    """Run a git command with test user env."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


def _sha(cwd):
    """Get HEAD SHA of a repo."""
    return _git(["rev-parse", "HEAD"], cwd).stdout.strip()


def _remote_sha(bare_repo, branch="main"):
    """Get the tip SHA of a branch in a bare repo."""
    result = _git(["rev-parse", branch], bare_repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_with_remotes(tmp_path):
    """Real git hub with two subprojects (api, web) and bare remotes.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            hub.git/          bare remote for hub
            api-work/         external api working copy
            web-work/         external web working copy
            hub/              hub working copy
                projects/api/ submodule checkout
                projects/web/ submodule checkout
                .project/     PM metadata
    """
    env = {"tmp": tmp_path}

    # Create subproject bare repos and seed with initial commits
    for name in ("api", "web"):
        bare = tmp_path / f"{name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)
        env[f"{name}_bare"] = bare

        work = tmp_path / f"{name}-work"
        _git(["clone", str(bare), str(work)], tmp_path)
        (work / "README.md").write_text(f"# {name}\n")
        _git(["add", "."], work)
        _git(["commit", "-m", f"initial {name}"], work)
        _git(["push", "-u", "origin", "main"], work)
        env[f"{name}_work"] = work

    # Create hub bare repo
    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    # Clone hub and configure
    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev1@test.com"], hub)
    _git(["config", "user.name", "Dev1"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    # Set up PM structure
    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects", "dashboards"):
        (proj / d).mkdir()
    config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "projects": ["api", "web"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    # Add submodules
    for name in ("api", "web"):
        _git(
            ["submodule", "add", str(env[f"{name}_bare"]), f"projects/{name}"],
            hub,
        )

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub"], hub)
    _git(["push", "-u", "origin", "main"], hub)
    env["hub"] = hub

    return env


# ─── Tests ────────────────────────────────────────────────────────



def test_single_command_pushes_hub_and_all_subprojects(hub_with_remotes):
    """pm_push(scope='all') pushes N subprojects then the hub.

    A single pm_push(scope='all') call must result in:
    1. Each subproject's local commits pushed to its bare remote
    2. The hub commit (with updated submodule refs) pushed to the hub remote
    """
    hub = hub_with_remotes["hub"]

    # Make local commits in both subprojects within the hub
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "feature.txt").write_text(f"{name} feature")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: new feature"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")

    # Stage submodule ref updates and commit in hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update api and web refs"], hub)
    hub_sha = _sha(hub)

    # ── Single command ──
    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is True, f"push failed: {result.get('error', result)}"
    assert result.get("scope") == "all"

    # Hub remote has the hub commit
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_sha

    # Both subproject remotes have the subproject commits
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_sha, (
        "api subproject commits should be pushed to api remote"
    )
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_sha, (
        "web subproject commits should be pushed to web remote"
    )



def test_single_command_pushes_subset_of_subprojects(hub_with_remotes):
    """pm_push(scope='all') works when only some subprojects have new commits."""
    hub = hub_with_remotes["hub"]

    # Only make a commit in api — web has nothing new
    api_sub = hub / "projects" / "api"
    (api_sub / "feature.txt").write_text("api only")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: only change"], api_sub)
    api_sha = _sha(api_sub)

    # Record the pre-push web remote SHA for later comparison
    web_before = _remote_sha(hub_with_remotes["web_bare"])

    # Stage and commit hub
    _git(["add", "projects/api"], hub)
    _git(["commit", "-m", "update api ref"], hub)

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is True, f"push failed: {result.get('error', result)}"

    # api was pushed
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_sha

    # web remote unchanged (no new commits to push)
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_before


def test_push_all_routes_through_coordinated_push(hub_with_remotes):
    """pm_push(scope='all') returns scope='all' and report from coordinated_push."""
    hub = hub_with_remotes["hub"]

    # Make a trivial hub-only commit (no subproject changes)
    readme = hub / "README.md"
    readme.write_text("# Hub\n")
    _git(["add", "."], hub)
    _git(["commit", "-m", "add readme"], hub)

    result = pm_push(scope="all", root=hub)

    assert result.get("scope") == "all"
    assert "report" in result, "coordinated_push should return a report"
    assert "Hub:" in result["report"]


# ─── Tests: Branch alignment validation before push (US-PRJ-4-2) ─────


@pytest.fixture
def hub_with_tracking_branches(hub_with_remotes):
    """Extend hub_with_remotes to configure tracking branches in .gitmodules.

    This sets `submodule.projects/{name}.branch = main` for both api and web,
    which is what validate_branches() reads to determine the expected branch.
    """
    hub = hub_with_remotes["hub"]
    for name in ("api", "web"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
    _git(["add", ".gitmodules"], hub)
    _git(["commit", "-m", "set tracking branches"], hub)
    _git(["push", "origin", "main"], hub)
    return hub_with_remotes


def test_push_all_rejects_misaligned_branch(hub_with_tracking_branches):
    """pm_push(scope='all') aborts when a subproject is on the wrong branch.

    Validates acceptance criterion:
        > Validates branch alignment before any push
    """
    hub = hub_with_tracking_branches["hub"]

    # Put api on a feature branch (misaligned with tracking branch 'main')
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "feature-x"], api_sub)
    (api_sub / "feature.txt").write_text("api feature")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: feature on wrong branch"], api_sub)

    # Record remote SHAs before the push attempt
    api_remote_before = _remote_sha(hub_with_tracking_branches["api_bare"])
    hub_remote_before = _remote_sha(hub_with_tracking_branches["hub_bare"])

    result = pm_push(scope="all", root=hub)

    # Push must be rejected
    assert result["pushed"] is False
    assert "validation failed" in result.get("error", "").lower()

    # Nothing should have been pushed (validation happens before push)
    assert _remote_sha(hub_with_tracking_branches["api_bare"]) == api_remote_before
    assert _remote_sha(hub_with_tracking_branches["hub_bare"]) == hub_remote_before


def test_push_all_rejects_detached_head(hub_with_tracking_branches):
    """pm_push(scope='all') aborts when a subproject has detached HEAD.

    In strict mode (used before push), detached HEAD is a blocking error.
    """
    hub = hub_with_tracking_branches["hub"]

    # Detach HEAD in web submodule
    web_sub = hub / "projects" / "web"
    head_sha = _sha(web_sub)
    _git(["checkout", head_sha], web_sub)

    hub_remote_before = _remote_sha(hub_with_tracking_branches["hub_bare"])

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is False
    assert "validation failed" in result.get("error", "").lower()

    # Hub remote unchanged — no push was attempted
    assert _remote_sha(hub_with_tracking_branches["hub_bare"]) == hub_remote_before


def test_push_project_rejects_misaligned_branch(hub_with_tracking_branches):
    """pm_push(scope='project:api') aborts when api is on the wrong branch."""
    hub = hub_with_tracking_branches["hub"]

    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "develop"], api_sub)

    api_remote_before = _remote_sha(hub_with_tracking_branches["api_bare"])

    result = pm_push(scope="project:api", root=hub)

    assert result["pushed"] is False
    assert "branch validation failed" in result.get("error", "").lower()
    assert "api" in result.get("error", "").lower()

    # Remote unchanged
    assert _remote_sha(hub_with_tracking_branches["api_bare"]) == api_remote_before


def test_push_project_rejects_detached_head(hub_with_tracking_branches):
    """pm_push(scope='project:web') aborts when web has detached HEAD."""
    hub = hub_with_tracking_branches["hub"]

    web_sub = hub / "projects" / "web"
    head_sha = _sha(web_sub)
    _git(["checkout", head_sha], web_sub)

    web_remote_before = _remote_sha(hub_with_tracking_branches["web_bare"])

    result = pm_push(scope="project:web", root=hub)

    assert result["pushed"] is False
    assert "branch validation failed" in result.get("error", "").lower()
    assert "detached" in result.get("error", "").lower()

    # Remote unchanged
    assert _remote_sha(hub_with_tracking_branches["web_bare"]) == web_remote_before


def test_push_all_allows_aligned_branches(hub_with_tracking_branches):
    """pm_push(scope='all') proceeds when all submodules are on correct branches.

    This is the positive case — validation passes, so the push proceeds.
    """
    hub = hub_with_tracking_branches["hub"]

    # Both api and web are on main (the tracked branch) — make a hub-only commit
    readme = hub / "README.md"
    readme.write_text("# Hub aligned\n")
    _git(["add", "."], hub)
    _git(["commit", "-m", "hub: readme update"], hub)

    result = pm_push(scope="all", root=hub)

    # Push should succeed (branches are aligned)
    assert result["pushed"] is True
    assert result.get("scope") == "all"


def test_push_project_allows_aligned_branch(hub_with_tracking_branches):
    """pm_push(scope='project:api') proceeds when api is on the correct branch."""
    hub = hub_with_tracking_branches["hub"]

    # api is on main — make a commit and push
    api_sub = hub / "projects" / "api"
    (api_sub / "aligned.txt").write_text("on main branch")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: aligned commit"], api_sub)

    result = pm_push(scope="project:api", root=hub)

    assert result["pushed"] is True
    assert result.get("scope") == "project:api"


# ─── Tests: Subprojects pushed before hub ref update (US-PRJ-4-3) ────



def test_subprojects_pushed_before_hub(hub_with_remotes):
    """Subproject remotes receive commits before the hub remote is updated.

    Verifies acceptance criterion:
        > Subprojects pushed before hub ref update

    After pm_push(scope='all'), each subproject's bare remote must already
    contain the new commits by the time the hub remote receives its push.
    We verify this indirectly: if subprojects were NOT pushed first, the
    hub remote would reference submodule SHAs that don't exist on the
    subproject remotes.
    """
    hub = hub_with_remotes["hub"]

    # Make local commits in both subprojects
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "ordering.txt").write_text(f"{name} ordering test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: ordering test"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")

    # Stage submodule ref updates and commit in hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update submodule refs"], hub)

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is True, f"push failed: {result.get('error', result)}"

    # Subproject remotes must have received their commits
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_sha, (
        "api remote should have the subproject commit (pushed before hub)"
    )
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_sha, (
        "web remote should have the subproject commit (pushed before hub)"
    )

    # Hub remote must reference the submodule SHAs that are now on the
    # subproject remotes — this only works if subprojects were pushed first
    hub_remote_sha = _remote_sha(hub_with_remotes["hub_bare"])
    assert hub_remote_sha, "hub remote should have the hub commit"



def test_hub_not_pushed_when_subproject_push_fails(hub_with_remotes):
    """Hub remote must NOT be updated when a subproject push fails.

    Verifies acceptance criterion:
        > Subprojects pushed before hub ref update

    If subprojects are pushed first and one fails, the hub push must be
    skipped entirely — proving the ordering guarantee.
    """
    hub = hub_with_remotes["hub"]

    # Make commits in both subprojects
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "feature.txt").write_text(f"{name} feature")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: new feature"], sub)

    # Sabotage the api bare remote so its push will fail
    api_bare = hub_with_remotes["api_bare"]
    api_bare.rename(api_bare.parent / "api-moved.git")

    # Stage and commit hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs"], hub)

    hub_remote_before = _remote_sha(hub_with_remotes["hub_bare"])

    result = pm_push(scope="all", root=hub)

    # The push must fail (api subproject push blocked)
    assert result["pushed"] is False, (
        "coordinated push should fail when a subproject push fails"
    )

    # Hub remote must be unchanged — subprojects come first, and since
    # api failed, the hub push should never have been attempted
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_remote_before, (
        "hub remote should NOT be updated when a subproject push fails"
    )


# ─── Tests: Clear report of what succeeded/failed (US-PRJ-4-4) ───


def test_report_contains_success_indicator_on_push(hub_with_remotes):
    """Successful push report includes ✓ and the commit SHA prefix.

    Verifies acceptance criterion:
        > Clear report of what succeeded/failed
    """
    hub = hub_with_remotes["hub"]

    readme = hub / "README.md"
    readme.write_text("# Hub report test\n")
    _git(["add", "."], hub)
    _git(["commit", "-m", "hub: report test"], hub)
    hub_sha = _sha(hub)[:7]

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is True
    report = result["report"]
    assert "Hub:" in report, "report should have a Hub section header"
    assert "\u2713" in report, "successful push report should contain ✓"
    assert hub_sha in report, (
        f"report should contain the commit SHA prefix ({hub_sha})"
    )


def test_report_contains_failure_indicator_on_push_error(hub_with_remotes):
    """Failed push report includes ✗ and an error description.

    Verifies acceptance criterion:
        > Clear report of what succeeded/failed
    """
    hub = hub_with_remotes["hub"]

    readme = hub / "README.md"
    readme.write_text("# Hub failure report\n")
    _git(["add", "."], hub)
    _git(["commit", "-m", "hub: will fail"], hub)

    # Sabotage hub remote by renaming the bare repo so push fails
    hub_bare = hub_with_remotes["hub_bare"]
    hub_bare.rename(hub_bare.parent / "hub-moved.git")

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is False
    report = result["report"]
    assert "Hub:" in report, "report should have a Hub section header"
    assert "\u2717" in report, "failed push report should contain ✗"


def test_report_distinguishes_success_from_failure(hub_with_remotes):
    """Report uses different indicators for success (✓) vs failure (✗).

    Verifies acceptance criterion:
        > Clear report of what succeeded/failed

    A user reading the report must be able to tell at a glance what
    worked and what didn't.
    """
    hub = hub_with_remotes["hub"]

    # First: a successful push
    (hub / "success.txt").write_text("ok")
    _git(["add", "."], hub)
    _git(["commit", "-m", "success commit"], hub)

    success_result = pm_push(scope="all", root=hub)
    assert success_result["pushed"] is True
    success_report = success_result["report"]

    # Now: a failed push (rename the bare repo so it's unreachable)
    (hub / "fail.txt").write_text("will fail")
    _git(["add", "."], hub)
    _git(["commit", "-m", "fail commit"], hub)
    hub_bare = hub_with_remotes["hub_bare"]
    hub_bare.rename(hub_bare.parent / "hub-moved.git")

    fail_result = pm_push(scope="all", root=hub)
    assert fail_result["pushed"] is False
    fail_report = fail_result["report"]

    # Success report should have ✓ but NOT ✗
    assert "\u2713" in success_report
    assert "\u2717" not in success_report

    # Failure report should have ✗ but NOT ✓
    assert "\u2717" in fail_report
    assert "\u2713" not in fail_report


def test_report_includes_origin_reference(hub_with_remotes):
    """Report references the remote target (origin) so the user knows where
    pushes were directed.

    Verifies acceptance criterion:
        > Clear report of what succeeded/failed
    """
    hub = hub_with_remotes["hub"]

    (hub / "origin-ref.txt").write_text("test")
    _git(["add", "."], hub)
    _git(["commit", "-m", "origin ref test"], hub)

    result = pm_push(scope="all", root=hub)
    report = result["report"]

    assert "origin" in report, "report should reference the remote (origin)"


def test_validation_failure_report_is_clear(hub_with_remotes):
    """When pre-push validation fails, the error message clearly states
    what went wrong so the user knows what to fix.

    Verifies acceptance criterion:
        > Clear report of what succeeded/failed
    """
    hub = hub_with_remotes["hub"]

    # Configure tracking branches so validation has something to check
    for name in ("api", "web"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
    _git(["add", ".gitmodules"], hub)
    _git(["commit", "-m", "set tracking branches"], hub)
    _git(["push", "origin", "main"], hub)

    # Put api on wrong branch
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "wrong-branch"], api_sub)

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is False
    error = result.get("error", "")
    # Error should mention "validation" so user knows it was a pre-check
    assert "validation" in error.lower(), (
        f"error should mention validation: {error}"
    )


# ─── Tests: Subproject push not rolled back on hub failure (US-PRJ-4-3) ──



def test_successful_subproject_push_not_rolled_back_on_hub_failure(hub_with_remotes):
    """Subproject pushes that succeeded are NOT rolled back if the hub push fails.

    Verifies the one-way ordering: subprojects push first, then hub.
    If the hub push fails, we expect subproject remotes to still have
    their new commits (no rollback), and the result should clearly
    report the hub failure.
    """
    hub = hub_with_remotes["hub"]

    # Make a commit in api subproject
    api_sub = hub / "projects" / "api"
    (api_sub / "feature.txt").write_text("api feature")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: feature"], api_sub)
    api_sha = _sha(api_sub)

    # Stage and commit hub
    _git(["add", "projects/api"], hub)
    _git(["commit", "-m", "update api ref"], hub)

    # Sabotage the hub bare remote so hub push fails
    hub_bare = hub_with_remotes["hub_bare"]
    hub_bare.rename(hub_bare.parent / "hub-moved.git")

    result = pm_push(scope="all", root=hub)

    # Hub push failed
    assert result["pushed"] is False

    # But api subproject should still have been pushed successfully
    # (subprojects go first, and api push should have succeeded
    # before the hub push was attempted and failed)
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_sha, (
        "api remote should have the commit even though hub push failed"
    )


# ─── Tests: No silent partial pushes (US-PRJ-4-5) ────────────────



def test_partial_subproject_failure_returns_pushed_false(hub_with_remotes):
    """When one subproject push fails, overall result must be pushed=False.

    Verifies acceptance criterion:
        > No silent partial pushes

    Even if some subprojects push successfully, a failure in any single
    subproject must cause the overall result to report failure.
    """
    hub = hub_with_remotes["hub"]

    # Make commits in both subprojects
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "partial.txt").write_text(f"{name} partial test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: partial test"], sub)

    # Sabotage only api — web should succeed
    api_bare = hub_with_remotes["api_bare"]
    api_bare.rename(api_bare.parent / "api-moved.git")

    # Stage and commit hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update both refs"], hub)

    result = pm_push(scope="all", root=hub)

    # Must NOT silently succeed with only web pushed
    assert result["pushed"] is False, (
        "pushed must be False when any subproject push fails — "
        "partial success must not be reported as success"
    )



def test_partial_failure_report_names_the_failed_project(hub_with_remotes):
    """When a subproject push fails, the report must name which project failed.

    Verifies acceptance criterion:
        > No silent partial pushes

    A partial push must not be silent — the report must explicitly
    mention the project that failed so the user knows what went wrong.
    """
    hub = hub_with_remotes["hub"]

    # Make commits in both subprojects
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "report.txt").write_text(f"{name} report test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: report test"], sub)

    # Sabotage only api
    api_bare = hub_with_remotes["api_bare"]
    api_bare.rename(api_bare.parent / "api-moved.git")

    # Stage and commit hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs for report test"], hub)

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is False
    report = result.get("report", "")
    # The report must mention "api" so the user knows which project failed
    assert "api" in report.lower(), (
        f"report must name the failed project ('api'): {report}"
    )
    # The report must contain a failure indicator
    assert "\u2717" in report, (
        f"report must contain ✗ for the failed project: {report}"
    )


def test_hub_failure_not_silent_after_push(hub_with_remotes):
    """When the hub push fails, the result must explicitly report the failure.

    Verifies acceptance criterion:
        > No silent partial pushes

    The hub push failure must be surfaced with pushed=False and a clear
    report — never silently swallowed.
    """
    hub = hub_with_remotes["hub"]

    # Make a commit and sabotage the hub remote
    (hub / "silent.txt").write_text("testing silent failure")
    _git(["add", "."], hub)
    _git(["commit", "-m", "hub: will fail silently?"], hub)

    hub_bare = hub_with_remotes["hub_bare"]
    hub_bare.rename(hub_bare.parent / "hub-gone.git")

    result = pm_push(scope="all", root=hub)

    # Must not silently succeed
    assert result["pushed"] is False, (
        "hub push failure must set pushed=False, never silent"
    )
    # Report must exist and contain failure info
    report = result.get("report", "")
    assert report, "a failed push must produce a non-empty report"
    assert "Hub:" in report, "report must include a Hub section"
    assert "\u2717" in report, (
        f"report must contain ✗ for the hub failure: {report}"
    )


def test_validation_failure_prevents_any_push(hub_with_remotes):
    """Pre-push validation failure must block all pushes, not just some.

    Verifies acceptance criterion:
        > No silent partial pushes

    When branch validation fails, no push at all should be attempted —
    the user must fix alignment first. This prevents a scenario where
    some projects are pushed but others can't be.
    """
    hub = hub_with_remotes["hub"]

    # Configure tracking branches
    for name in ("api", "web"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
    _git(["add", ".gitmodules"], hub)
    _git(["commit", "-m", "set tracking branches"], hub)
    _git(["push", "origin", "main"], hub)

    # Misalign api — create a commit on a wrong branch
    api_sub = hub / "projects" / "api"
    _git(["checkout", "-b", "rogue-branch"], api_sub)
    (api_sub / "rogue.txt").write_text("rogue commit")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: rogue commit on wrong branch"], api_sub)

    # Record remote SHAs
    api_remote_before = _remote_sha(hub_with_remotes["api_bare"])
    web_remote_before = _remote_sha(hub_with_remotes["web_bare"])
    hub_remote_before = _remote_sha(hub_with_remotes["hub_bare"])

    result = pm_push(scope="all", root=hub)

    # Validation must block everything
    assert result["pushed"] is False
    assert "validation failed" in result.get("error", "").lower()

    # Nothing should have been pushed — no silent partial
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_remote_before, (
        "api remote should be unchanged after validation failure"
    )
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_remote_before, (
        "web remote should be unchanged after validation failure"
    )
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_remote_before, (
        "hub remote should be unchanged after validation failure"
    )



def test_all_subprojects_fail_returns_pushed_false_with_report(hub_with_remotes):
    """When all subproject pushes fail, pushed=False and each failure is reported.

    Verifies acceptance criterion:
        > No silent partial pushes

    Even total failure must produce a clear report — silence is never acceptable.
    """
    hub = hub_with_remotes["hub"]

    # Make commits in both subprojects
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "allbad.txt").write_text(f"{name} all fail test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: all fail test"], sub)

    # Sabotage both bare remotes
    for name in ("api", "web"):
        bare = hub_with_remotes[f"{name}_bare"]
        bare.rename(bare.parent / f"{name}-moved.git")

    # Stage and commit hub
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs — both will fail"], hub)

    result = pm_push(scope="all", root=hub)

    assert result["pushed"] is False, (
        "total failure must report pushed=False"
    )
    report = result.get("report", "")
    assert report, "total failure must produce a non-empty report"
    # Both failures should be visible in the report
    assert "api" in report.lower(), (
        f"report must mention failed project 'api': {report}"
    )
    assert "web" in report.lower(), (
        f"report must mention failed project 'web': {report}"
    )


# ─── push_hub with pushed_projects (US-PRJ-4-8) ───────────────────


from projectman.hub.registry import push_hub


def test_push_hub_stages_and_commits_submodule_refs(hub_with_remotes):
    """push_hub(pushed_projects) stages submodule refs and commits before pushing.

    After subprojects are pushed, push_hub should:
    1. git add projects/{name} for each pushed project
    2. Commit with formatted message
    3. Push to remote
    """
    hub = hub_with_remotes["hub"]

    # Make a commit in api subproject and push it
    api_sub = hub / "projects" / "api"
    (api_sub / "new-feature.txt").write_text("api feature")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: add feature"], api_sub)
    api_sha = _sha(api_sub)
    _git(["push", "origin", "main"], api_sub)

    # push_hub should stage the updated ref, commit, and push
    result = push_hub(
        pushed_projects=[{"name": "api", "sha": api_sha}],
        root=hub,
    )

    assert result["committed"] is True
    assert result["pushed"] is True
    assert result["commit_sha"] is not None
    assert result.get("error") is None

    # Verify the hub remote has the new commit
    hub_remote_sha = _remote_sha(hub_with_remotes["hub_bare"])
    assert hub_remote_sha == result["commit_sha"]


def test_push_hub_commit_message_format(hub_with_remotes):
    """push_hub generates commit message: hub: update {names} to {shas}."""
    hub = hub_with_remotes["hub"]

    # Make commits in both subprojects and push them
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "msg-test.txt").write_text(f"{name} msg test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: msg test"], sub)
        _git(["push", "origin", "main"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")

    pushed = [
        {"name": "api", "sha": api_sha},
        {"name": "web", "sha": web_sha},
    ]

    result = push_hub(pushed_projects=pushed, root=hub)

    assert result["committed"] is True

    # Check the commit message
    log = _git(["log", "-1", "--format=%s", result["commit_sha"]], hub)
    msg = log.stdout.strip()
    assert msg.startswith("hub: update ")
    assert "api" in msg
    assert "web" in msg
    assert api_sha[:7] in msg
    assert web_sha[:7] in msg


def test_push_hub_without_pushed_projects_preserves_old_behavior(hub_with_remotes):
    """push_hub() without pushed_projects just pushes existing commits."""
    hub = hub_with_remotes["hub"]

    # Make a local hub commit (not submodule-related)
    (hub / "README.md").write_text("updated readme")
    _git(["add", "README.md"], hub)
    _git(["commit", "-m", "update readme"], hub)
    hub_sha = _sha(hub)

    result = push_hub(root=hub)

    assert result["pushed"] is True
    assert result["committed"] is False  # No submodule staging done
    assert result["status"] == "pushed"
    assert result["attempts"] == 1
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_sha


def test_push_hub_nothing_to_commit_still_pushes(hub_with_remotes):
    """When pushed_projects refs haven't changed, push_hub still pushes."""
    hub = hub_with_remotes["hub"]

    # Don't change any subproject — refs are same as remote
    # But make a different hub commit so there's something to push
    (hub / "CHANGELOG.md").write_text("changelog")
    _git(["add", "CHANGELOG.md"], hub)
    _git(["commit", "-m", "add changelog"], hub)

    api_sha = _sha(hub / "projects" / "api")
    result = push_hub(
        pushed_projects=[{"name": "api", "sha": api_sha}],
        root=hub,
    )

    # commit may or may not succeed (refs unchanged), but push should work
    assert result["pushed"] is True


def test_push_hub_returns_error_fields(hub_with_remotes):
    """push_hub returns all required fields in the result dict."""
    hub = hub_with_remotes["hub"]

    api_sub = hub / "projects" / "api"
    (api_sub / "fields-test.txt").write_text("fields test")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: fields test"], api_sub)
    _git(["push", "origin", "main"], api_sub)

    result = push_hub(
        pushed_projects=[{"name": "api", "sha": _sha(api_sub)}],
        root=hub,
    )

    # Verify all required keys are present
    assert "committed" in result
    assert "pushed" in result
    assert "commit_sha" in result
    # error is absent on success, present on failure
    assert result.get("error") is None
    # Backward-compat keys
    assert "status" in result
    assert "attempts" in result


def test_push_hub_single_project_commit_message(hub_with_remotes):
    """push_hub with one project produces a clean commit message."""
    hub = hub_with_remotes["hub"]

    web_sub = hub / "projects" / "web"
    (web_sub / "single.txt").write_text("single project")
    _git(["add", "."], web_sub)
    _git(["commit", "-m", "web: single"], web_sub)
    _git(["push", "origin", "main"], web_sub)
    web_sha = _sha(web_sub)

    result = push_hub(
        pushed_projects=[{"name": "web", "sha": web_sha}],
        root=hub,
    )

    assert result["committed"] is True
    log = _git(["log", "-1", "--format=%s", result["commit_sha"]], hub)
    msg = log.stdout.strip()
    assert msg == f"hub: update web to {web_sha[:7]}"


def test_push_hub_push_failure_reports_error(hub_with_remotes):
    """When hub push fails, push_hub reports the error clearly."""
    hub = hub_with_remotes["hub"]

    api_sub = hub / "projects" / "api"
    (api_sub / "fail-test.txt").write_text("fail test")
    _git(["add", "."], api_sub)
    _git(["commit", "-m", "api: fail test"], api_sub)
    _git(["push", "origin", "main"], api_sub)
    api_sha = _sha(api_sub)

    # Sabotage the hub bare remote so push fails
    hub_bare = hub_with_remotes["hub_bare"]
    hub_bare.rename(hub_bare.parent / "hub-moved.git")

    result = push_hub(
        pushed_projects=[{"name": "api", "sha": api_sha}],
        root=hub,
    )

    # Commit should succeed even though push fails
    assert result["committed"] is True
    assert result["pushed"] is False
    assert result["error"] is not None
    assert result["status"] == "failed"


# ─── Tests: Full coordinated push workflow (US-PRJ-4-10) ─────────

from projectman.hub.registry import coordinated_push


@pytest.fixture
def hub_with_three_remotes(tmp_path):
    """Real git hub with three subprojects (api, web, worker) and bare remotes.

    Layout::

        tmp_path/
            api.git/          bare remote for api
            web.git/          bare remote for web
            worker.git/       bare remote for worker
            hub.git/          bare remote for hub
            hub/              hub working copy
                projects/api/ submodule checkout
                projects/web/ submodule checkout
                projects/worker/ submodule checkout
                .project/     PM metadata
    """
    env = {"tmp": tmp_path}

    for name in ("api", "web", "worker"):
        bare = tmp_path / f"{name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)
        env[f"{name}_bare"] = bare

        work = tmp_path / f"{name}-work"
        _git(["clone", str(bare), str(work)], tmp_path)
        (work / "README.md").write_text(f"# {name}\n")
        _git(["add", "."], work)
        _git(["commit", "-m", f"initial {name}"], work)
        _git(["push", "-u", "origin", "main"], work)
        env[f"{name}_work"] = work

    hub_bare = tmp_path / "hub.git"
    hub_bare.mkdir()
    _git(["init", "--bare", "-b", "main"], hub_bare)
    env["hub_bare"] = hub_bare

    hub = tmp_path / "hub"
    _git(["clone", str(hub_bare), str(hub)], tmp_path)
    _git(["config", "user.email", "dev1@test.com"], hub)
    _git(["config", "user.name", "Dev1"], hub)
    _git(["config", "protocol.file.allow", "always"], hub)

    proj = hub / ".project"
    proj.mkdir()
    for d in ("stories", "tasks", "projects", "dashboards"):
        (proj / d).mkdir()
    config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "test",
        "hub": True,
        "next_story_id": 1,
        "projects": ["api", "web", "worker"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

    for name in ("api", "web", "worker"):
        _git(
            ["submodule", "add", str(env[f"{name}_bare"]), f"projects/{name}"],
            hub,
        )

    _git(["add", "."], hub)
    _git(["commit", "-m", "initial hub"], hub)
    _git(["push", "-u", "origin", "main"], hub)
    env["hub"] = hub

    return env


def test_happy_path_three_dirty_subprojects(hub_with_three_remotes):
    """Scenario 1: 3 dirty subprojects -> preflight passes -> all push -> hub updated.

    All three subproject remotes and the hub remote must receive their
    respective commits after a single coordinated_push() call.
    """
    hub = hub_with_three_remotes["hub"]

    for name in ("api", "web", "worker"):
        sub = hub / "projects" / name
        (sub / "feature.txt").write_text(f"{name} feature")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: new feature"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")
    worker_sha = _sha(hub / "projects" / "worker")

    _git(["add", "projects/api", "projects/web", "projects/worker"], hub)
    _git(["commit", "-m", "update all refs"], hub)

    result = coordinated_push(root=hub)

    assert result["pushed"] is True, f"push failed: {result.get('error', result)}"

    # All three subproject remotes updated
    assert _remote_sha(hub_with_three_remotes["api_bare"]) == api_sha
    assert _remote_sha(hub_with_three_remotes["web_bare"]) == web_sha
    assert _remote_sha(hub_with_three_remotes["worker_bare"]) == worker_sha

    # Hub remote updated
    assert _remote_sha(hub_with_three_remotes["hub_bare"]) == _sha(hub)


def test_preflight_blocks_entire_push_with_three_projects(hub_with_three_remotes):
    """Scenario 2: one subproject on wrong branch -> entire push aborted.

    When preflight detects a branch misalignment, nothing should be pushed
    to any remote — not even the projects that are correctly aligned.
    """
    hub = hub_with_three_remotes["hub"]

    # Configure tracking branches so validation has something to check
    for name in ("api", "web", "worker"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
    _git(["add", ".gitmodules"], hub)
    _git(["commit", "-m", "set tracking branches"], hub)
    _git(["push", "origin", "main"], hub)

    # Make commits in api and worker (both on main — correct)
    for name in ("api", "worker"):
        sub = hub / "projects" / name
        (sub / "feature.txt").write_text(f"{name} feature")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: feature"], sub)

    # Put web on wrong branch
    web_sub = hub / "projects" / "web"
    _git(["checkout", "-b", "wrong-branch"], web_sub)
    (web_sub / "feature.txt").write_text("web on wrong branch")
    _git(["add", "."], web_sub)
    _git(["commit", "-m", "web: wrong branch"], web_sub)

    api_remote_before = _remote_sha(hub_with_three_remotes["api_bare"])
    worker_remote_before = _remote_sha(hub_with_three_remotes["worker_bare"])
    hub_remote_before = _remote_sha(hub_with_three_remotes["hub_bare"])

    result = coordinated_push(root=hub)

    assert result["pushed"] is False

    # Nothing should have been pushed — preflight blocks everything
    assert _remote_sha(hub_with_three_remotes["api_bare"]) == api_remote_before
    assert _remote_sha(hub_with_three_remotes["worker_bare"]) == worker_remote_before
    assert _remote_sha(hub_with_three_remotes["hub_bare"]) == hub_remote_before


def test_midway_failure_records_pushed_and_skipped(hub_with_three_remotes):
    """Scenario 3: project 2 of 3 fails mid-way.

    Project 1 (api) should be recorded as pushed, project 2 (web) as failed,
    project 3 (worker) as skipped, and hub NOT updated.

    Uses a competing commit on web's remote to cause a non-fast-forward
    rejection (remote is still reachable, so preflight passes).
    """
    hub = hub_with_three_remotes["hub"]

    for name in ("api", "web", "worker"):
        sub = hub / "projects" / name
        (sub / "midway.txt").write_text(f"{name} midway test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: midway test"], sub)

    api_sha = _sha(hub / "projects" / "api")

    # Push a competing commit to web's remote from the external clone
    # so the hub's web submodule push is rejected (non-fast-forward)
    web_work = hub_with_three_remotes["web_work"]
    (web_work / "competing.txt").write_text("competing commit")
    _git(["add", "."], web_work)
    _git(["commit", "-m", "competing commit on web"], web_work)
    _git(["push", "origin", "main"], web_work)

    _git(["add", "projects/api", "projects/web", "projects/worker"], hub)
    _git(["commit", "-m", "update all refs"], hub)

    hub_remote_before = _remote_sha(hub_with_three_remotes["hub_bare"])
    worker_remote_before = _remote_sha(hub_with_three_remotes["worker_bare"])

    result = coordinated_push(root=hub)

    # Overall must fail
    assert result["pushed"] is False

    # api (project 1) should have been pushed before the failure
    assert _remote_sha(hub_with_three_remotes["api_bare"]) == api_sha, (
        "api (pushed before failure) should be on remote"
    )

    # worker (project 3) should be skipped — remote unchanged
    assert _remote_sha(hub_with_three_remotes["worker_bare"]) == worker_remote_before, (
        "worker (after failure) should be skipped"
    )

    # Hub should NOT be updated
    assert _remote_sha(hub_with_three_remotes["hub_bare"]) == hub_remote_before, (
        "hub should NOT be updated when a subproject push fails"
    )

    # Verify the sub_result tracks pushed/failed/skipped correctly
    sub_result = result.get("sub_result", {})
    pushed_names = [p["name"] for p in sub_result.get("pushed", [])]
    assert "api" in pushed_names, "api should be recorded as pushed"
    assert sub_result.get("failed", {}).get("name") == "web", (
        "web should be recorded as the failed project"
    )
    assert "worker" in sub_result.get("skipped", []), (
        "worker should be in the skipped list"
    )


def test_hub_push_conflict_preserves_subproject_pushes(hub_with_remotes):
    """Scenario 4: hub push fails due to concurrent commit, subproject pushes preserved.

    Simulates a concurrent commit on the hub remote so the hub push is
    rejected (non-fast-forward). With max_retries=1 the hub gives up
    immediately, but subproject commits must remain on their remotes.
    """
    hub = hub_with_remotes["hub"]

    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "conflict.txt").write_text(f"{name} conflict test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: conflict test"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")

    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs"], hub)

    # Simulate concurrent commit on hub remote from another developer
    hub_clone2 = hub_with_remotes["tmp"] / "hub-clone2"
    _git(
        ["clone", str(hub_with_remotes["hub_bare"]), str(hub_clone2)],
        hub_with_remotes["tmp"],
    )
    _git(["config", "user.email", "dev2@test.com"], hub_clone2)
    _git(["config", "user.name", "Dev2"], hub_clone2)
    _git(["config", "protocol.file.allow", "always"], hub_clone2)
    (hub_clone2 / "concurrent.txt").write_text("concurrent change")
    _git(["add", "."], hub_clone2)
    _git(["commit", "-m", "concurrent commit by dev2"], hub_clone2)
    _git(["push", "origin", "main"], hub_clone2)

    # max_retries=1 gives hub_push_with_rebase 0 retries — fails immediately
    result = coordinated_push(root=hub, max_retries=1)

    assert result["pushed"] is False

    # Subproject remotes should have their commits regardless
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_sha, (
        "api remote should have its commit even if hub push fails"
    )
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_sha, (
        "web remote should have its commit even if hub push fails"
    )

    # Error should be reported in the report
    report = result.get("report", "")
    assert "Hub:" in report
    assert "\u2717" in report, "hub failure should be indicated with ✗"


def test_dry_run_prints_plan_without_pushing(hub_with_remotes):
    """Scenario 5: dry_run=True detects dirty projects, prints plan, pushes nothing.

    The report should describe what WOULD happen, and all remotes must
    remain unchanged.
    """
    hub = hub_with_remotes["hub"]

    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "dryrun.txt").write_text(f"{name} dry run")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: dry run test"], sub)

    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs for dry run"], hub)

    api_remote_before = _remote_sha(hub_with_remotes["api_bare"])
    web_remote_before = _remote_sha(hub_with_remotes["web_bare"])
    hub_remote_before = _remote_sha(hub_with_remotes["hub_bare"])

    result = coordinated_push(dry_run=True, root=hub)

    # pushed must be False (nothing actually pushed)
    assert result["pushed"] is False

    # Report should describe the dry run plan
    report = result.get("report", "")
    assert "Dry Run" in report, f"report should mention 'Dry Run': {report}"
    assert "would push" in report, f"report should say 'would push': {report}"

    # Nothing actually pushed
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_remote_before
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_remote_before
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_remote_before


def test_no_dirty_projects_nothing_to_push(hub_with_remotes):
    """Scenario 6: everything clean -> no errors, hub handles gracefully.

    When no subprojects have unpushed commits, the push should complete
    without error and no remote state should change.
    """
    hub = hub_with_remotes["hub"]

    api_remote_before = _remote_sha(hub_with_remotes["api_bare"])
    web_remote_before = _remote_sha(hub_with_remotes["web_bare"])
    hub_remote_before = _remote_sha(hub_with_remotes["hub_bare"])

    result = coordinated_push(root=hub)

    # No errors — should complete cleanly
    assert result.get("report") is not None, "should produce a report"

    # Remotes unchanged
    assert _remote_sha(hub_with_remotes["api_bare"]) == api_remote_before
    assert _remote_sha(hub_with_remotes["web_bare"]) == web_remote_before
    assert _remote_sha(hub_with_remotes["hub_bare"]) == hub_remote_before


def test_selective_push_only_pushes_specified_projects(hub_with_three_remotes):
    """Scenario 7: coordinated_push(projects=['api','web']) ignores dirty worker.

    Only the explicitly specified projects should be pushed; worker should
    remain unchanged even though it has unpushed commits.
    """
    hub = hub_with_three_remotes["hub"]

    for name in ("api", "web", "worker"):
        sub = hub / "projects" / name
        (sub / "selective.txt").write_text(f"{name} selective test")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: selective test"], sub)

    api_sha = _sha(hub / "projects" / "api")
    web_sha = _sha(hub / "projects" / "web")
    worker_remote_before = _remote_sha(hub_with_three_remotes["worker_bare"])

    _git(["add", "projects/api", "projects/web", "projects/worker"], hub)
    _git(["commit", "-m", "update all refs"], hub)

    # Only push api and web — worker should be ignored
    result = coordinated_push(projects=["api", "web"], root=hub)

    assert result["pushed"] is True, f"push failed: {result.get('error', result)}"

    # api and web should be pushed
    assert _remote_sha(hub_with_three_remotes["api_bare"]) == api_sha
    assert _remote_sha(hub_with_three_remotes["web_bare"]) == web_sha

    # worker should NOT be pushed
    assert _remote_sha(hub_with_three_remotes["worker_bare"]) == worker_remote_before, (
        "worker should not be pushed when not in the projects list"
    )


def test_convention_violation_bad_branch_caught_by_preflight(hub_with_three_remotes):
    """Scenario 8: bad branch name on one project -> preflight catches it.

    When a subproject is on a branch that doesn't match its tracking
    configuration, the preflight should catch it and produce a clear error.
    """
    hub = hub_with_three_remotes["hub"]

    # Configure tracking branches
    for name in ("api", "web", "worker"):
        _git(
            ["config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", "main"],
            hub,
        )
    _git(["add", ".gitmodules"], hub)
    _git(["commit", "-m", "set tracking branches"], hub)
    _git(["push", "origin", "main"], hub)

    # Put worker on a non-conventional branch name
    worker_sub = hub / "projects" / "worker"
    _git(["checkout", "-b", "bad/branch-name!"], worker_sub)
    (worker_sub / "bad.txt").write_text("bad branch")
    _git(["add", "."], worker_sub)
    _git(["commit", "-m", "worker: bad branch"], worker_sub)

    worker_remote_before = _remote_sha(hub_with_three_remotes["worker_bare"])
    hub_remote_before = _remote_sha(hub_with_three_remotes["hub_bare"])

    result = coordinated_push(root=hub)

    # Preflight should catch the misalignment
    assert result["pushed"] is False
    report = result.get("report", "")
    assert "worker" in report.lower(), (
        f"report should mention the offending project 'worker': {report}"
    )

    # Nothing pushed
    assert _remote_sha(hub_with_three_remotes["worker_bare"]) == worker_remote_before
    assert _remote_sha(hub_with_three_remotes["hub_bare"]) == hub_remote_before
