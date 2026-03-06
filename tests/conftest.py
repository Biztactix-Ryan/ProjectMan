"""Shared test fixtures."""

import pytest
from pathlib import Path
import yaml


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal .project/ directory for testing."""
    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()

    config = {
        "name": "test-project",
        "prefix": "TST",
        "description": "A test project",
        "hub": False,
        "next_story_id": 1,
        "projects": [],
    }
    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Create documentation files
    (proj / "PROJECT.md").write_text("# test-project\n\nA test project.\n\n## Architecture\n\nPython CLI tool.\n\n## Key Decisions\n\nUse pytest for testing.\n")
    (proj / "INFRASTRUCTURE.md").write_text("# test-project — Infrastructure\n\n## Environments\n\nLocal development only.\nNo staging or production environments.\n\n## CI/CD\n\nGitHub Actions runs pytest on push.\nNo deployment pipeline configured.\n")
    (proj / "SECURITY.md").write_text("# test-project — Security\n\n## Authentication\n\nNone — CLI tool.\n\n## Authorization\n\nN/A.\n\n## Known Risks\n\nNone identified.\n")

    return tmp_path


@pytest.fixture
def tmp_hub(tmp_path):
    """Create a minimal hub project for testing."""
    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "projects").mkdir()
    (proj / "roadmap").mkdir()
    (proj / "dashboards").mkdir()

    config = {
        "name": "test-hub",
        "prefix": "HUB",
        "description": "A test hub",
        "hub": True,
        "next_story_id": 1,
        "projects": [],
    }
    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    return tmp_path


@pytest.fixture
def store(tmp_project):
    """Create a Store instance for testing."""
    from projectman.store import Store, _cache
    _cache.clear()
    return Store(tmp_project)


@pytest.fixture
def tmp_git_project(tmp_project):
    """Create a tmp_project inside a git repository with an initial commit."""
    import subprocess

    subprocess.run(["git", "init"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_project), capture_output=True, check=True)

    return tmp_project


@pytest.fixture
def tmp_git_project_with_remote(tmp_git_project, tmp_path_factory):
    """A tmp_git_project with a bare remote for push testing."""
    import subprocess

    bare = tmp_path_factory.mktemp("bare")
    bare_repo = bare / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare_repo)], capture_output=True, check=True)

    subprocess.run(
        ["git", "remote", "add", "origin", str(bare_repo)],
        cwd=str(tmp_git_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "master"],
        cwd=str(tmp_git_project), capture_output=True,
        # Don't check — branch may be "main" instead
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(tmp_git_project), capture_output=True,
        # Don't check — branch may be "master" instead
    )

    return tmp_git_project


@pytest.fixture
def tmp_git_hub(tmp_hub):
    """Create a tmp_hub inside a git repository with an initial commit."""
    import subprocess

    subprocess.run(["git", "init"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_hub), capture_output=True, check=True)

    return tmp_hub
