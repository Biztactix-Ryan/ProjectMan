"""Integration tests for hub conflict resolution with real git repos.

Tests auto-rebase and fast-forward scenarios by creating bare repos as
remotes and simulating concurrent pushes.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import (
    hub_push_with_rebase,
    log_ref_update,
    REF_LOG_MAX_ENTRIES,
)


# ─── Helpers ──────────────────────────────────────────────────────

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    # Allow local file:// transport for submodule operations in tests
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


def _make_commit(work_dir, message="update"):
    """Commit in a subproject working copy and push. Returns HEAD SHA."""
    readme = work_dir / "README.md"
    readme.write_text((readme.read_text() if readme.exists() else "") + f"\n{message}")
    _git(["add", "."], work_dir)
    _git(["commit", "-m", message], work_dir)
    _git(["push", "origin", "HEAD"], work_dir)
    return _sha(work_dir)


def _update_sub(hub_dir, project, sha):
    """Fetch latest in a hub's submodule, checkout SHA, stage in hub."""
    sub = hub_dir / "projects" / project
    _git(["fetch", "origin"], sub)
    _git(["checkout", sha], sub)
    _git(["add", f"projects/{project}"], hub_dir)


def _committed_sub_ref(hub_dir, project):
    """Get the submodule ref recorded in the hub's HEAD commit (not the working dir)."""
    tree = _git(["ls-tree", "HEAD", f"projects/{project}"], hub_dir).stdout.strip()
    # Format: "160000 commit <sha>\tprojects/<project>"
    return tree.split()[2] if tree else ""


def _clone_hub(env, name="hub2"):
    """Clone the hub as a second developer."""
    hub2 = env["tmp"] / name
    _git(["clone", str(env["hub_bare"]), str(hub2)], env["tmp"])
    _git(["config", "user.email", "dev2@test.com"], hub2)
    _git(["config", "user.name", "Dev2"], hub2)
    _git(["config", "protocol.file.allow", "always"], hub2)
    _git(["submodule", "update", "--init"], hub2)
    return hub2


# ─── Fixture ──────────────────────────────────────────────────────


@pytest.fixture
def hub_env(tmp_path):
    """Real git hub with two subprojects (api, web) and bare remotes."""
    env = {"tmp": tmp_path}

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
        "projects": ["api", "web"],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))

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


# ─── 1. Clean push ───────────────────────────────────────────────


def test_clean_push(hub_env):
    """No conflict — pushes first try, 0 retries."""
    hub = hub_env["hub"]
    sha = _make_commit(hub_env["api_work"], "feature-1")
    _update_sub(hub, "api", sha)
    _git(["commit", "-m", "update api"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is True
    assert result["retries"] == 0
    assert result["rebased"] is False
    assert result["error"] is None


# ─── 2. Simple rebase ────────────────────────────────────────────


def test_simple_rebase(hub_env):
    """Remote has new commit on different submodule — rebase succeeds."""
    hub = hub_env["hub"]
    sha_api = _make_commit(hub_env["api_work"], "api-feat")
    sha_web = _make_commit(hub_env["web_work"], "web-feat")

    # Dev2 pushes web update first
    hub2 = _clone_hub(hub_env)
    _update_sub(hub2, "web", sha_web)
    _git(["commit", "-m", "dev2: web"], hub2)
    _git(["push", "origin", "main"], hub2)

    # Dev1 updates api — remote is now ahead
    _update_sub(hub, "api", sha_api)
    _git(["commit", "-m", "dev1: api"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is True
    assert result["retries"] >= 1
    assert result["rebased"] is True
    assert result["error"] is None


# ─── 3. Same-project fast-forward: ours newer ────────────────────


def test_same_project_ff_ours_newer(hub_env):
    """Both update api ref — ours is ahead, auto-resolved, ours kept."""
    hub = hub_env["hub"]
    api_work = hub_env["api_work"]

    sha_c1 = _make_commit(api_work, "c1")
    sha_c2 = _make_commit(api_work, "c2")  # c2 ahead of c1

    # Dev2 pushes api at c1 (the older commit)
    hub2 = _clone_hub(hub_env)
    _update_sub(hub2, "api", sha_c1)
    _git(["commit", "-m", "dev2: api@c1"], hub2)
    _git(["push", "origin", "main"], hub2)

    # Dev1 has api at c2 (the newer commit)
    _update_sub(hub, "api", sha_c2)
    _git(["commit", "-m", "dev1: api@c2"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is True
    assert result["rebased"] is True
    assert _committed_sub_ref(hub, "api") == sha_c2


# ─── 4. Same-project fast-forward: theirs newer ──────────────────


def test_same_project_ff_theirs_newer(hub_env):
    """Both update api ref — theirs is ahead, auto-resolved, theirs kept."""
    hub = hub_env["hub"]
    api_work = hub_env["api_work"]

    sha_c1 = _make_commit(api_work, "c1")
    sha_c2 = _make_commit(api_work, "c2")

    # Dev2 pushes api at c2 (the newer commit)
    hub2 = _clone_hub(hub_env)
    _update_sub(hub2, "api", sha_c2)
    _git(["commit", "-m", "dev2: api@c2"], hub2)
    _git(["push", "origin", "main"], hub2)

    # Dev1 has api at c1 (the older commit)
    _update_sub(hub, "api", sha_c1)
    _git(["commit", "-m", "dev1: api@c1"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is True
    assert result["rebased"] is True
    # Check the committed ref (not the submodule working dir, which rebase
    # doesn't update for theirs-newer resolution)
    assert _committed_sub_ref(hub, "api") == sha_c2


# ─── 5. Diverged refs ────────────────────────────────────────────


def test_diverged_refs(hub_env):
    """Both update api ref, branches diverged — flagged for manual resolution."""
    hub = hub_env["hub"]
    api_work = hub_env["api_work"]

    # Create two diverged branches in the api subproject
    _git(["checkout", "-b", "branch-a"], api_work)
    (api_work / "a.txt").write_text("a")
    _git(["add", "."], api_work)
    _git(["commit", "-m", "branch-a"], api_work)
    sha_a = _sha(api_work)
    _git(["push", "origin", "branch-a"], api_work)

    _git(["checkout", "main"], api_work)
    _git(["checkout", "-b", "branch-b"], api_work)
    (api_work / "b.txt").write_text("b")
    _git(["add", "."], api_work)
    _git(["commit", "-m", "branch-b"], api_work)
    sha_b = _sha(api_work)
    _git(["push", "origin", "branch-b"], api_work)

    # Dev2 pushes api at branch-a
    hub2 = _clone_hub(hub_env)
    _update_sub(hub2, "api", sha_a)
    _git(["commit", "-m", "dev2: api@branch-a"], hub2)
    _git(["push", "origin", "main"], hub2)

    # Dev1 has api at branch-b
    _update_sub(hub, "api", sha_b)
    _git(["commit", "-m", "dev1: api@branch-b"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is False
    assert "diverged" in result["error"].lower()


# ─── 6. Max retries exceeded ─────────────────────────────────────


def test_max_retries_exceeded(hub_env):
    """Continuous remote rejections — fails after max retries."""
    hub = hub_env["hub"]
    sha = _make_commit(hub_env["api_work"], "feature")
    _update_sub(hub, "api", sha)
    _git(["commit", "-m", "update api"], hub)

    # Install an update hook that always rejects pushes
    hook_dir = hub_env["hub_bare"] / "hooks"
    hook_dir.mkdir(exist_ok=True)
    hook_path = hook_dir / "update"
    hook_path.write_text("#!/bin/bash\nexit 1\n")
    hook_path.chmod(0o755)

    try:
        result = hub_push_with_rebase(root=hub, max_retries=3)

        assert result["pushed"] is False
        assert result["retries"] == 3
        assert "max retries" in result["error"]
    finally:
        hook_path.unlink()


# ─── 7. .project/ file conflict ──────────────────────────────────


def test_project_file_conflict(hub_env):
    """Both modify same .project/ file — abort with manual resolution message."""
    hub = hub_env["hub"]

    # Dev2 modifies .project/config.yaml and pushes
    hub2 = _clone_hub(hub_env)
    cfg2 = hub2 / ".project" / "config.yaml"
    data = yaml.safe_load(cfg2.read_text())
    data["description"] = "dev2 edit"
    cfg2.write_text(yaml.dump(data))
    _git(["add", "."], hub2)
    _git(["commit", "-m", "dev2: config"], hub2)
    _git(["push", "origin", "main"], hub2)

    # Dev1 modifies the same file differently
    cfg1 = hub / ".project" / "config.yaml"
    data = yaml.safe_load(cfg1.read_text())
    data["description"] = "dev1 edit"
    cfg1.write_text(yaml.dump(data))
    _git(["add", "."], hub)
    _git(["commit", "-m", "dev1: config"], hub)

    result = hub_push_with_rebase(root=hub)

    assert result["pushed"] is False
    assert ".project/" in result["error"]
    assert "manual resolution" in result["error"]


# ─── 8. Ref log after push ───────────────────────────────────────


def test_ref_log_after_push(hub_env):
    """After successful push, ref-log.yaml contains entry with old/new ref, timestamp, source."""
    hub = hub_env["hub"]
    api_work = hub_env["api_work"]

    old_ref = _sha(hub / "projects" / "api")
    sha_new = _make_commit(api_work, "feature")
    _update_sub(hub, "api", sha_new)
    _git(["commit", "-m", "update api"], hub)

    result = hub_push_with_rebase(root=hub)
    assert result["pushed"] is True

    # Log the ref change (as coordinated_push / sync would after a real push)
    hub_sha = _sha(hub)
    log_ref_update("api", old_ref, sha_new, "coordinated_push", hub, commit=hub_sha)

    log_path = hub / ".project" / "ref-log.yaml"
    assert log_path.exists()

    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == 1

    entry = entries[0]
    assert entry["project"] == "api"
    assert entry["old_ref"] == old_ref
    assert entry["new_ref"] == sha_new
    assert entry["source"] == "coordinated_push"
    assert entry["commit"] == hub_sha
    assert "timestamp" in entry
    assert entry["old_ref"] != entry["new_ref"]


# ─── 9. Ref log rotation ─────────────────────────────────────────


def test_ref_log_rotation(tmp_hub):
    """501 entries — oldest rotated to archive."""
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    archive_path = tmp_hub / ".project" / "ref-log.archive.yaml"

    # Pre-fill with exactly MAX entries
    seed = [
        {
            "timestamp": f"t{i}",
            "project": "api",
            "old_ref": "o",
            "new_ref": "n",
            "source": "seed",
        }
        for i in range(REF_LOG_MAX_ENTRIES)
    ]
    log_path.write_text(yaml.dump(seed, default_flow_style=False))

    # One more triggers rotation
    log_ref_update("web", "x", "y", "push", tmp_hub)

    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == REF_LOG_MAX_ENTRIES
    assert entries[-1]["project"] == "web"
    assert entries[-1]["source"] == "push"

    assert archive_path.exists()
    archived = yaml.safe_load(archive_path.read_text())
    assert len(archived) == 1
    assert archived[0]["timestamp"] == "t0"
