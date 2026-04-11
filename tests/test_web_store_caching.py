"""Tests for Web API Store caching (BUG 3 fix)."""

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


class TestWebStoreCaching:
    """Tests that get_store uses cached Store instances correctly."""

    def test_get_store_returns_same_instance_for_main_project(self, store):
        """get_store for the main project (no project param) returns app.state.store."""
        from projectman.web.routes.api import get_store
        from projectman.web.app import app

        # The app already has a store from startup
        result = get_store(project=None)
        assert result is app.state.store

    def test_hub_store_cache_isolated_per_hub_project(self, tmp_path):
        """Hub subproject stores are cached separately by project name."""
        import yaml
        from projectman.store import Store
        from projectman.web.routes.api import _hub_store_cache, get_store

        # Clear any existing cache
        _hub_store_cache.clear()

        # Create a minimal hub structure
        hub_root = tmp_path / "hub"
        hub_proj = hub_root / ".project"
        hub_proj.mkdir(parents=True)
        (hub_proj / "stories").mkdir()
        (hub_proj / "tasks").mkdir()
        (hub_proj / "projects").mkdir()

        hub_config = {
            "name": "hub",
            "prefix": "HUB",
            "hub": True,
            "next_story_id": 1,
            "next_epic_id": 1,
            "projects": ["api"],
        }
        with open(hub_proj / "config.yaml", "w") as f:
            yaml.dump(hub_config, f)

        pm_dir = hub_proj / "projects" / "api"
        pm_dir.mkdir()
        (pm_dir / "stories").mkdir()
        (pm_dir / "tasks").mkdir()
        api_config = {
            "name": "api",
            "prefix": "API",
            "hub": False,
            "next_story_id": 1,
            "next_epic_id": 1,
            "projects": [],
        }
        with open(pm_dir / "config.yaml", "w") as f:
            yaml.dump(api_config, f)

        # Patch find_project_root to return our hub
        with patch(
            "projectman.web.routes.api.find_project_root", return_value=hub_root
        ):
            store1 = get_store(project="api")
            store2 = get_store(project="api")

            # Same cached instance
            assert store1 is store2
            assert "api" in _hub_store_cache

            # Different project would get different instance
            pm_dir2 = hub_proj / "projects" / "web"
            pm_dir2.mkdir()
            (pm_dir2 / "stories").mkdir()
            (pm_dir2 / "tasks").mkdir()
            web_config = {
                "name": "web",
                "prefix": "WEB",
                "hub": False,
                "next_story_id": 1,
                "next_epic_id": 1,
                "projects": [],
            }
            with open(pm_dir2 / "config.yaml", "w") as f:
                yaml.dump(web_config, f)
            _hub_store_cache.clear()

            store3 = get_store(project="web")
            store4 = get_store(project="web")
            assert store3 is store4
            assert store3 is not store1
