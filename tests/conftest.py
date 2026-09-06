"""Shared test fixtures."""

import functools
import pytest
from pathlib import Path
from typing import NamedTuple
import yaml


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Keep the per-root config cache from leaking between tests.

    ``config.load_config`` memoises parsed configs keyed by resolved project
    root (US-PRJ-30).  ``tmp_path`` roots are unique per test so collisions
    are unlikely, but a test that pins a root (``PROJECTMAN_ROOT``, the repo
    itself) or rewrites config.yaml in place would otherwise see another
    test's entry.  Cleared on both sides so the state is fresh going in and
    nothing is left behind.
    """
    from projectman.config import clear_config_cache

    clear_config_cache()
    yield
    clear_config_cache()


@pytest.fixture(autouse=True)
def _clear_hub_store_map():
    """Keep the per-process hub store map from leaking between tests.

    ``hub.stores.hub_stores`` caches its map keyed by resolved root the way
    ``server._store_cache`` caches Stores (US-PM-31).  Fixtures build a hub
    directory tree *after* something may already have read the map for that
    root, so it is dropped on both sides of every test.
    """
    from projectman.hub.stores import invalidate

    invalidate()
    yield
    invalidate()


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
    (proj / "roadmap").mkdir()
    (proj / "dashboards").mkdir()
    # Subproject checkouts live beside the hub store, each with its own
    # .project/ inside it (US-PM-31) — see projectman.hub.stores.
    (tmp_path / "projects").mkdir()

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


# ─── Hub subprojects (US-PM-31) ────────────────────────────────────


def _register_in_hub(hub_root, name):
    """Add *name* to the hub's config.projects if it isn't already there."""
    from projectman.config import load_config, save_config

    hub_config = load_config(hub_root)
    if name not in hub_config.projects:
        hub_config.projects.append(name)
        save_config(hub_config, hub_root)


def make_hub_subproject(
    hub_root,
    name,
    prefix="SUB",
    *,
    attached=True,
    register=True,
):
    """Build a subproject store at ``projects/{name}/.project`` and register it.

    This is *the* place tests build hub subprojects, so the layout lives in
    one file (US-PM-31): the store is inside the subproject's own checkout,
    never in the hub's ``.project/``.

    ``attached=False`` produces the case the migration exists to fix — a store
    that was *copied* into a real checkout rather than mounted as a worktree.
    It plants a ``.git`` directory beside the store, which is what makes
    ``hub.stores.default_attached_check`` fall back to its strict clause and
    answer False.  Everything else about the store is identical, so a test can
    prove that the unattached path is chosen by the mount state and not by
    missing data.

    Returns the store directory (``{hub_root}/projects/{name}/.project``).
    """
    from projectman.hub.stores import invalidate, store_path, subproject_path

    sub_path = subproject_path(hub_root, name)
    sub_path.mkdir(parents=True, exist_ok=True)

    pm_dir = store_path(hub_root, name)
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "stories").mkdir(exist_ok=True)
    (pm_dir / "tasks").mkdir(exist_ok=True)
    (pm_dir / "epics").mkdir(exist_ok=True)

    config = {
        "name": name,
        "prefix": prefix,
        "description": "",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(pm_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    if not attached:
        # A checkout that *is* a git repository: the store beside it is now
        # only attached if it is a real worktree, and a plain directory isn't.
        (sub_path / ".git").mkdir(exist_ok=True)

    if register:
        _register_in_hub(hub_root, name)

    # The map caches per root and the tree just changed underneath it.
    invalidate(hub_root)
    return pm_dir


def make_unattached_hub_subproject(hub_root, name, prefix="SUB", **kwargs):
    """A registered subproject whose store exists but is not mounted."""
    return make_hub_subproject(hub_root, name, prefix, attached=False, **kwargs)


def register_hub_subproject_without_store(hub_root, name):
    """Register *name* in the hub with no checkout and no store at all.

    The other flavour of unattached: nothing has been cloned yet, so there is
    no ``projects/{name}`` either.  Reads must report it, not raise.
    """
    from projectman.hub.stores import invalidate

    _register_in_hub(hub_root, name)
    invalidate(hub_root)
    return None


def make_legacy_hub_side_store(hub_root, name, prefix="SUB", *, register=True):
    """Build a *pre*-US-PM-31 store at ``.project/projects/{name}/``.

    The only place in the suite that writes the old layout, and it writes it
    deliberately: this is the leftover ``projectman repair`` reports and
    ``projectman migrate-hub`` (US-PM-31-8) moves.  Nothing reads it — a test
    that wants a *readable* subproject wants :func:`make_hub_subproject`.

    The checkout at ``projects/{name}`` is created too, empty, because that is
    what a hub looks like mid-migration: the submodule is cloned, its store is
    still in the hub.
    """
    from projectman.hub.stores import PROJECTS_DIRNAME, invalidate, subproject_path

    subproject_path(hub_root, name).mkdir(parents=True, exist_ok=True)

    hub_side = hub_root / ".project" / PROJECTS_DIRNAME / name
    (hub_side / "stories").mkdir(parents=True, exist_ok=True)
    (hub_side / "tasks").mkdir(parents=True, exist_ok=True)
    with open(hub_side / "config.yaml", "w") as f:
        yaml.dump(
            {
                "name": name,
                "prefix": prefix,
                "description": "",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            },
            f,
        )

    if register:
        _register_in_hub(hub_root, name)

    invalidate(hub_root)
    return hub_side


@pytest.fixture
def legacy_hub_side_store():
    """Factory for the pre-US-PM-31 hub-side store that migrate-hub moves."""
    return make_legacy_hub_side_store


@pytest.fixture
def hub_subproject():
    """Factory: ``hub_subproject(hub_root, name, prefix="SUB")`` -> store dir.

    The attached case — use it wherever a test needs a subproject the hub can
    actually read.
    """
    return make_hub_subproject


@pytest.fixture
def hub_unattached_subproject():
    """Factory for a subproject whose store is present but not mounted.

    ``hub_unattached_subproject(hub_root, name, prefix="SUB")`` -> store dir.
    Pair it with :func:`hub_subproject` to prove a hub read reports the
    unattached one while still returning the attached one's numbers.
    """
    return make_unattached_hub_subproject


@pytest.fixture
def hub_registered_subproject_only():
    """Factory for a name in ``config.projects`` with nothing on disk."""
    return register_hub_subproject_without_store


@pytest.fixture
def store(tmp_project):
    """Create a Store instance for testing."""
    from projectman.store import Store, _cache
    _cache.clear()
    return Store(tmp_project)


def _seed_indexes(root):
    """Bring the store to the state ``projectman init`` leaves it in.

    Since US-PM-29 mutating tools no longer rewrite the indexes; ``pm_reindex``,
    ``pm_commit``, ``projectman reindex`` and ``indexer.ensure_fresh`` on the
    read path regenerate them instead.  Two consequences the fixtures have to
    reproduce, or "a clean store has nothing to commit" would never hold:

    * the five files exist on disk from the start, as they do in any store
      that has been read or reindexed once, so a later rebuild is a no-op
      rather than five additions; and
    * they are gitignored (US-PM-29-6), as a scaffolded store's are, so the
      initial ``git add .`` does not track them.
    """
    from projectman.indexer import write_index, write_store_gitignore
    from projectman.store import Store

    store = Store(root)
    write_index(store)
    write_store_gitignore(store.project_dir)


@pytest.fixture
def tmp_git_project(tmp_project):
    """Create a tmp_project inside a git repository with an initial commit."""
    import subprocess

    _seed_indexes(tmp_project)
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

    _seed_indexes(tmp_hub)
    subprocess.run(["git", "init"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_hub), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_hub), capture_output=True, check=True)

    return tmp_hub


@pytest.fixture(scope="module")
def all_tool_families():
    """Register the config-gated tool families for a whole module (US-PM-15-5).

    The maintenance and web families are hidden from
    ``tools/list`` unless a project opts in, and a hidden tool answers
    ``tools/call`` with ``Unknown tool``.  A module that asserts a property of *every*
    ``@mcp.tool`` function — error-body shape, ``is_error`` on the wire, the
    ID-alias rollout — is testing the tools, not the gate, so it turns the
    gate off and sweeps the full surface.  ``tests/test_tool_gating.py``
    is where the gate itself is asserted.

    Use it module-wide::

        pytestmark = pytest.mark.usefixtures("all_tool_families")

    The previous visibility is restored on teardown, so the modules that run
    after this one still see the default tool list.
    """
    from projectman.server import TOOL_FAMILIES, apply_tool_gating, gated_tool_state

    before = gated_tool_state()
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    yield
    apply_tool_gating(before)


# ─── Store call-counting spy (US-PRJ-63-5) ─────────────────────────


#: Store read methods the spy wraps.  Ordered as: single-item reads,
#: then listings.  ``list_tasks_with_bodies`` is here because
#: ``Store.list_tasks`` delegates to it (store.py) — a test that only
#: watched ``list_tasks`` would miss a caller that reaches for bodies
#: directly, and one that only watched the bodies variant would be
#: fooled by the delegation.
SPIED_STORE_METHODS = (
    "get",
    "get_task",
    "get_story",
    "get_epic",
    "list_tasks",
    "list_tasks_with_bodies",
    "list_stories",
    "list_epics",
    "list_all",
)


class SpyCall(NamedTuple):
    """One recorded ``Store`` read: the method name and how it was called."""

    name: str
    args: tuple
    kwargs: dict


class StoreSpy:
    """Counts and records ``Store`` read calls made anywhere in the process.

    The wrappers are installed on the ``Store`` *class*, so every instance —
    including the one a server tool builds for itself via ``_store()`` — is
    counted.

    Two consequences worth knowing before asserting exact numbers:

    * ``Store.get`` dispatches to ``get_epic`` / ``get_story`` / ``get_task``,
      so one ``get("US-TST-1-1")`` bumps both ``get`` and ``get_task``.
    * ``Store.list_tasks`` delegates to ``Store.list_tasks_with_bodies``, and
      ``Store.list_all`` calls the listing for its item type, so those inner
      calls are counted too.

    Attributes:
        counts: ``{method_name: int}`` for every name in
            :data:`SPIED_STORE_METHODS`.
        calls: every :class:`SpyCall` in the order it happened.
    """

    def __init__(self):
        self.counts: dict[str, int] = {name: 0 for name in SPIED_STORE_METHODS}
        self.calls: list[SpyCall] = []

    def reset(self) -> None:
        """Zero the counters and drop the recorded calls.

        Call this after fixture setup (or any warm-up) so a measurement
        starts from a clean slate.
        """
        for name in self.counts:
            self.counts[name] = 0
        self.calls.clear()

    def calls_to(self, name: str) -> list[SpyCall]:
        """Every recorded call to *name*, in order."""
        if name not in self.counts:
            raise KeyError(f"{name} is not spied; known: {sorted(self.counts)}")
        return [c for c in self.calls if c.name == name]

    def nonzero(self) -> dict[str, int]:
        """Just the methods that were actually called — handy in assert messages."""
        return {k: v for k, v in self.counts.items() if v}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"StoreSpy({self.nonzero()})"


@pytest.fixture
def store_spy(monkeypatch):
    """Wrap ``Store``'s read methods with counters; yields a :class:`StoreSpy`.

    ``monkeypatch.setattr`` reverts the wrappers when the test ends, so
    nothing leaks into the next test.

    Fixture ordering matters: pytest sets fixtures up in the order they
    appear in the test signature, so list any data-building fixture
    *before* ``store_spy`` — or call ``spy.reset()`` once setup is done —
    otherwise the setup's own reads land in the counts.
    """
    from projectman.store import Store

    spy = StoreSpy()

    def make_wrapper(name, original):
        @functools.wraps(original)
        def wrapper(self, *args, **kwargs):
            spy.counts[name] += 1
            spy.calls.append(SpyCall(name, args, dict(kwargs)))
            return original(self, *args, **kwargs)

        return wrapper

    for name in SPIED_STORE_METHODS:
        original = getattr(Store, name)
        monkeypatch.setattr(Store, name, make_wrapper(name, original))

    return spy
