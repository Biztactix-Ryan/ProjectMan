"""Integration tests for validate_branches using real git repos."""

import subprocess

import pytest
import yaml

from projectman.hub.registry import validate_branches, format_branch_validation


# ─── Helpers ──────────────────────────────────────────────────────


def _git(args, cwd):
    """Run a git command in the given directory."""
    subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_hub_repo(hub_root):
    """Initialise the hub root as a real git repo."""
    _git(["init"], hub_root)
    _git(["config", "user.email", "test@test.com"], hub_root)
    _git(["config", "user.name", "Test"], hub_root)
    # Initial commit so we have a HEAD
    (hub_root / "README.md").write_text("hub\n")
    _git(["add", "README.md"], hub_root)
    _git(["commit", "-m", "init"], hub_root)


def _add_submodule_repo(hub_root, name, branch="main"):
    """Create a real git repo at projects/{name} and register it in .gitmodules."""
    sub_path = hub_root / "projects" / name
    sub_path.mkdir(parents=True, exist_ok=True)
    _git(["init"], sub_path)
    _git(["config", "user.email", "test@test.com"], sub_path)
    _git(["config", "user.name", "Test"], sub_path)
    _git(["checkout", "-b", branch], sub_path)
    (sub_path / "README.md").write_text(f"{name}\n")
    _git(["add", "README.md"], sub_path)
    _git(["commit", "-m", "init"], sub_path)

    # Write tracking branch into .gitmodules at hub root
    gitmodules = hub_root / ".gitmodules"
    _git(
        ["config", "-f", ".gitmodules",
         f"submodule.projects/{name}.branch", branch],
        hub_root,
    )

    # Register in hub config
    from projectman.config import load_config, save_config
    hub_config = load_config(hub_root)
    if name not in hub_config.projects:
        hub_config.projects.append(name)
        save_config(hub_config, hub_root)

    # Create PM data dir so list_projects is happy
    pm_dir = hub_root / ".project" / "projects" / name
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "stories").mkdir(exist_ok=True)
    (pm_dir / "tasks").mkdir(exist_ok=True)
    config = {
        "name": name,
        "prefix": name.upper()[:3],
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    return sub_path


# ─── 1. All aligned ──────────────────────────────────────────────


def test_all_aligned(tmp_hub):
    """Every submodule on its tracked branch → ok=True."""
    _init_hub_repo(tmp_hub)
    _add_submodule_repo(tmp_hub, "api", branch="main")
    _add_submodule_repo(tmp_hub, "web", branch="main")

    result = validate_branches(root=tmp_hub)

    assert result["ok"] is True
    assert len(result["aligned"]) == 2
    names = {e["name"] for e in result["aligned"]}
    assert names == {"api", "web"}
    for entry in result["aligned"]:
        assert entry["branch"] == "main"
        assert entry["dirty"] is False
    assert result["misaligned"] == []
    assert result["detached"] == []
    assert result["missing"] == []


# ─── 2. One misaligned ───────────────────────────────────────────


def test_one_misaligned(tmp_hub):
    """Submodule on feature branch while .gitmodules says main → detected."""
    _init_hub_repo(tmp_hub)
    sub = _add_submodule_repo(tmp_hub, "api", branch="main")

    # Switch the submodule to a different branch
    _git(["checkout", "-b", "feature-x"], sub)

    result = validate_branches(root=tmp_hub)

    assert result["ok"] is False
    assert len(result["misaligned"]) == 1
    mis = result["misaligned"][0]
    assert mis["name"] == "api"
    assert mis["expected"] == "main"
    assert mis["actual"] == "feature-x"
    assert result["aligned"] == []


# ─── 3. Detached HEAD ────────────────────────────────────────────


def test_detached_head(tmp_hub):
    """After `git checkout <sha>` in submodule → reported as detached."""
    _init_hub_repo(tmp_hub)
    sub = _add_submodule_repo(tmp_hub, "api", branch="main")

    # Get the current commit SHA and check it out directly
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(sub), capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(["checkout", sha], sub)

    result = validate_branches(root=tmp_hub)

    # Default mode: detached is informational, ok=True
    assert result["ok"] is True
    assert len(result["detached"]) == 1
    assert result["detached"][0]["name"] == "api"
    assert result["detached"][0]["expected"] == "main"
    assert result["aligned"] == []


# ─── 4. Missing submodule dir ────────────────────────────────────


def test_missing_submodule_dir(tmp_hub):
    """Registered in config but projects/{name} doesn't exist → missing."""
    _init_hub_repo(tmp_hub)

    # Register a project without creating its directory
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("phantom")
    save_config(hub_config, tmp_hub)

    result = validate_branches(root=tmp_hub)

    assert result["ok"] is False
    assert len(result["missing"]) == 1
    assert result["missing"][0]["name"] == "phantom"


# ─── 5. No branch in .gitmodules ─────────────────────────────────


def test_no_branch_in_gitmodules(tmp_hub):
    """Branch field absent → handled gracefully (skipped)."""
    _init_hub_repo(tmp_hub)

    # Create a submodule repo but DON'T set a tracking branch in .gitmodules
    sub_path = tmp_hub / "projects" / "api"
    sub_path.mkdir(parents=True)
    _git(["init"], sub_path)
    _git(["config", "user.email", "test@test.com"], sub_path)
    _git(["config", "user.name", "Test"], sub_path)
    _git(["checkout", "-b", "main"], sub_path)
    (sub_path / "README.md").write_text("api\n")
    _git(["add", "README.md"], sub_path)
    _git(["commit", "-m", "init"], sub_path)

    # Register in hub config
    from projectman.config import load_config, save_config
    hub_config = load_config(tmp_hub)
    hub_config.projects.append("api")
    save_config(hub_config, tmp_hub)

    result = validate_branches(root=tmp_hub)

    # No tracking branch → skipped entirely, ok=True
    assert result["ok"] is True
    assert result["aligned"] == []
    assert result["misaligned"] == []
    assert result["detached"] == []
    assert result["missing"] == []


# ─── 6. Mixed state ──────────────────────────────────────────────


def test_mixed_state(tmp_hub):
    """Combination of aligned, misaligned, detached → summary accurate."""
    _init_hub_repo(tmp_hub)

    # aligned: "api" on main
    _add_submodule_repo(tmp_hub, "api", branch="main")

    # misaligned: "web" tracks main but is on develop
    sub_web = _add_submodule_repo(tmp_hub, "web", branch="main")
    _git(["checkout", "-b", "develop"], sub_web)

    # detached: "worker" tracks main but checked out to SHA
    sub_worker = _add_submodule_repo(tmp_hub, "worker", branch="main")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(sub_worker), capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(["checkout", sha], sub_worker)

    result = validate_branches(root=tmp_hub)

    assert result["ok"] is False  # misaligned makes ok=False
    assert len(result["aligned"]) == 1
    assert result["aligned"][0]["name"] == "api"
    assert len(result["misaligned"]) == 1
    assert result["misaligned"][0]["name"] == "web"
    assert result["misaligned"][0]["expected"] == "main"
    assert result["misaligned"][0]["actual"] == "develop"
    assert len(result["detached"]) == 1
    assert result["detached"][0]["name"] == "worker"

    # Summary includes counts for each category
    assert "1 misaligned" in result["summary"]
    assert "1 detached" in result["summary"]
    assert "1 ok" in result["summary"]


# ─── 7. CLI exit code ────────────────────────────────────────────


def test_cli_exit_0_on_all_aligned(tmp_hub):
    """CLI returns exit code 0 when all branches are aligned."""
    from click.testing import CliRunner
    from projectman.cli import cli

    _init_hub_repo(tmp_hub)
    _add_submodule_repo(tmp_hub, "api", branch="main")

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-branches"], env={"PROJECTMAN_ROOT": str(tmp_hub)})

    assert result.exit_code == 0
    assert "correct branch" in result.output


def test_cli_exit_1_on_mismatch(tmp_hub):
    """CLI returns exit code 1 when any submodule is misaligned."""
    from click.testing import CliRunner
    from projectman.cli import cli

    _init_hub_repo(tmp_hub)
    sub = _add_submodule_repo(tmp_hub, "api", branch="main")
    _git(["checkout", "-b", "feature-x"], sub)

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-branches"], env={"PROJECTMAN_ROOT": str(tmp_hub)})

    assert result.exit_code == 1
    assert "Branch mismatch" in result.output
    assert "expected 'main'" in result.output
    assert "actual 'feature-x'" in result.output
