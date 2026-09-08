"""Tests for Web API Store caching (BUG 3 fix).

The routes take their store from ``routes.api.get_store``, and there is
exactly one: the store over ``{root}/.project`` (US-PM-45).  What is under
test here is that a request never builds a fresh ``Store`` — it gets
``app.state.store`` when startup built one for this root, and otherwise one
cached object per store directory in ``routes.api._store_cache``.
"""

from pathlib import Path


class TestWebStoreCaching:
    """Tests that the routes use cached Store instances correctly."""

    def test_get_store_returns_the_app_store(self, store, monkeypatch):
        """The dependency hands back app.state.store, not a new Store."""
        from projectman.web.app import app
        from projectman.web.routes import api

        # Startup normally populates app.state.store; set it explicitly here so
        # the test does not depend on a running app / project-root discovery.
        app.state.store = store
        monkeypatch.setattr(
            api, "find_project_root", lambda: Path(store.project_dir).parent
        )
        result = api.get_store()
        assert result is app.state.store
        assert result is store

    def test_get_store_caches_one_store_per_root(self, tmp_project, monkeypatch):
        """With no app store for this root, one Store is built and reused."""
        from projectman.web.app import app
        from projectman.web.routes import api

        app.state.store = None
        api._store_cache.clear()
        monkeypatch.setattr(api, "find_project_root", lambda: tmp_project)

        first = api.get_store()
        second = api.get_store()

        assert first is second
        assert Path(first.project_dir) == tmp_project / ".project"
        assert api._store_cache[tmp_project / ".project"] is first

    def test_get_store_ignores_an_app_store_from_another_root(
        self, tmp_project, monkeypatch
    ):
        """A Store left on app.state for a different root is never handed back."""
        import shutil

        from projectman.store import Store
        from projectman.web.app import app
        from projectman.web.routes import api

        other_root = tmp_project.parent / "other-root"
        shutil.copytree(tmp_project / ".project", other_root / ".project")
        app.state.store = Store(other_root)
        api._store_cache.clear()
        monkeypatch.setattr(api, "find_project_root", lambda: tmp_project)

        result = api.get_store()

        assert result is not app.state.store
        assert Path(result.project_dir) == tmp_project / ".project"
