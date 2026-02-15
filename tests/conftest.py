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
    from projectman.store import Store
    return Store(tmp_project)
