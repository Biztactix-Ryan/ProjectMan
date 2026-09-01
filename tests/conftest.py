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


@pytest.fixture(scope="module")
def all_tool_families():
    """Register the config-gated tool families for a whole module (US-PM-15-5).

    The changeset, maintenance and web families are hidden from
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
