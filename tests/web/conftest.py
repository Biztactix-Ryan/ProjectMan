"""Shared fixtures for web API tests."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from starlette.testclient import TestClient


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal .project/ directory with sample data."""
    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()

    config = {
        "name": "test-project",
        "prefix": "TST",
        "description": "A test project",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Create docs
    (proj / "PROJECT.md").write_text("# test-project\nA test project.\n")
    (proj / "INFRASTRUCTURE.md").write_text("# Infrastructure\nLocal only.\n")
    (proj / "SECURITY.md").write_text("# Security\nNo auth.\n")
    (proj / "VISION.md").write_text("# Vision\nTest vision.\n")
    (proj / "ARCHITECTURE.md").write_text("# Architecture\nSimple.\n")
    (proj / "DECISIONS.md").write_text("# Decisions\nNone yet.\n")

    return tmp_path


@pytest.fixture
def client(tmp_project):
    """TestClient that uses the tmp_project as its project root."""
    # Patch at both import sites so all code paths resolve to tmp_project
    with patch(
        "projectman.web.routes.api.find_project_root", return_value=tmp_project
    ), patch(
        "projectman.config.find_project_root", return_value=tmp_project
    ):
        from projectman.web.app import app

        app.state.root = tmp_project
        app.state.store = None

        yield TestClient(app)
