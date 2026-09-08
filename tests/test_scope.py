"""Store scope after hub mode was removed (EPIC-PM-6).

The story this file was written for (US-PRJ-3, "hub vs subproject scope is
configurable") no longer has a subject: there is one store per project and
``Store(root)`` resolves it.  What survives is the single-store half of the
old assertions — the default scope, and the server's ``_store()`` reaching
the same directory — kept so a future refactor cannot quietly reintroduce a
second resolution path.
"""

from projectman.store import Store


def test_store_default_scope_uses_root_project_dir(tmp_project):
    """Store(root) defaults project_dir to root/.project/."""
    s = Store(tmp_project)
    assert s.project_dir == tmp_project / ".project"


def test_store_explicit_project_dir_is_honoured(tmp_project, tmp_path):
    """Store(root, project_dir=...) uses the given directory as scope."""
    other = tmp_path / "elsewhere" / ".project"
    other.mkdir(parents=True)
    (other / "stories").mkdir()
    (other / "tasks").mkdir()
    (other / "config.yaml").write_text("name: other\nprefix: OTH\nnext_story_id: 1\n")

    s = Store(tmp_project, project_dir=other)
    assert s.project_dir == other
    assert s.config.name == "other"


def test_resolve_store_uses_the_one_root_store(tmp_project, monkeypatch):
    """``server._store()`` returns a Store at the root's .project/."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store

    assert _store().project_dir == tmp_project / ".project"
