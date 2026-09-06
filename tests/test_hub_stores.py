"""The hub store map — ``projectman.hub.stores`` (US-PM-31).

Verifies the story criterion:

  > A hub store map lists every subproject with its prefix and store path read
  > from projects/{name}/.project/config.yaml and no code path reads
  > .project/projects any more

Covers:
- every registered subproject appears, in registration order, with name,
  prefix and store path;
- the prefix comes from that subproject's *own* config.yaml, not the hub's;
- a store that is missing, empty, or has no config.yaml is listed with
  ``attached: False`` rather than dropped or raised over;
- a store that sits in a real checkout without being mounted is not attached;
- the per-process cache, its invalidation hook, and the fact that it does not
  serve a stale answer after a store appears;
- the readers (``server._store_for_prefix`` / ``_project_dir_for_prefix``,
  ``web.routes.api``, ``hub.rollup``, ``indexer``) go through the map;
- and a source scan pinning that nothing under ``src/`` builds either of the
  two old paths any more.
"""

import ast
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.stores import (
    PROJECTS_DIRNAME,
    STORE_DIRNAME,
    hub_store,
    hub_stores,
    invalidate,
    projects_dir,
    store_path,
    subproject_path,
)

SRC = Path(__file__).resolve().parent.parent / "src"


# ─── Helpers ─────────────────────────────────────────────────────


def register(hub_root, *names):
    """Add *names* to the hub's config.projects."""
    from projectman.config import load_config, save_config

    config = load_config(hub_root)
    for name in names:
        if name not in config.projects:
            config.projects.append(name)
    save_config(config, hub_root)


def make_store(hub_root, name, prefix=None, *, config=True):
    """Create a subproject checkout with (optionally) its own PM store."""
    path = store_path(hub_root, name)
    path.mkdir(parents=True, exist_ok=True)
    (path / "stories").mkdir(exist_ok=True)
    (path / "tasks").mkdir(exist_ok=True)
    if config:
        (path / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": name,
                    "prefix": prefix or name.upper()[:3],
                    "description": "",
                    "hub": False,
                    "next_story_id": 1,
                    "projects": [],
                }
            )
        )
    return path


def subproject(hub_root, name, prefix=None, *, config=True):
    register(hub_root, name)
    return make_store(hub_root, name, prefix, config=config)


# ─── Paths ───────────────────────────────────────────────────────


def test_the_store_path_is_inside_the_subprojects_own_checkout(tmp_hub):
    assert subproject_path(tmp_hub, "api") == tmp_hub / "projects" / "api"
    assert store_path(tmp_hub, "api") == tmp_hub / "projects" / "api" / ".project"
    assert projects_dir(tmp_hub) == tmp_hub / "projects"
    assert (PROJECTS_DIRNAME, STORE_DIRNAME) == ("projects", ".project")


# ─── The map ─────────────────────────────────────────────────────


def test_every_registered_subproject_is_listed_with_name_prefix_and_path(tmp_hub):
    subproject(tmp_hub, "api", "API")
    subproject(tmp_hub, "web", "WEB")

    entries = hub_stores(tmp_hub)

    assert [e["name"] for e in entries] == ["api", "web"]
    assert [e["prefix"] for e in entries] == ["API", "WEB"]
    assert [e["path"] for e in entries] == [
        tmp_hub / "projects" / "api" / ".project",
        tmp_hub / "projects" / "web" / ".project",
    ]
    assert all(e["attached"] for e in entries)


def test_the_prefix_comes_from_the_subprojects_own_config_not_the_hubs(tmp_hub):
    """The hub's prefix is HUB; the subproject's own file is what is read."""
    subproject(tmp_hub, "api", "ZZZ")

    entry = hub_store(tmp_hub, "api")

    assert entry["prefix"] == "ZZZ"
    on_disk = yaml.safe_load((entry["path"] / "config.yaml").read_text())
    assert on_disk["prefix"] == "ZZZ"


def test_a_rewritten_prefix_is_picked_up(tmp_hub):
    subproject(tmp_hub, "api", "API")
    assert hub_store(tmp_hub, "api")["prefix"] == "API"

    path = store_path(tmp_hub, "api")
    data = yaml.safe_load((path / "config.yaml").read_text())
    data["prefix"] = "NEW"
    (path / "config.yaml").write_text(yaml.safe_dump(data))

    assert hub_store(tmp_hub, "api")["prefix"] == "NEW"


def test_a_map_entry_carries_exactly_the_documented_keys(tmp_hub):
    subproject(tmp_hub, "api", "API")
    assert set(hub_stores(tmp_hub)[0]) == {"name", "prefix", "path", "attached"}


def test_an_unregistered_store_is_not_in_the_map(tmp_hub):
    """The map walks config.projects — a directory alone does not join the hub."""
    make_store(tmp_hub, "stray", "STR")

    assert hub_stores(tmp_hub) == []
    assert hub_store(tmp_hub, "stray") is None


def test_a_non_hub_root_has_an_empty_map(tmp_project):
    assert hub_stores(tmp_project) == []


# ─── attached: False ─────────────────────────────────────────────


def test_a_registered_project_with_no_store_at_all_is_listed_unattached(tmp_hub):
    """Missing store: still listed, with its path, so callers can report it."""
    register(tmp_hub, "ghost")

    entry = hub_store(tmp_hub, "ghost")

    assert entry["name"] == "ghost"
    assert entry["path"] == tmp_hub / "projects" / "ghost" / ".project"
    assert entry["attached"] is False
    assert entry["prefix"] is None


def test_a_store_directory_without_a_config_is_unattached(tmp_hub):
    subproject(tmp_hub, "half", config=False)

    entry = hub_store(tmp_hub, "half")

    assert entry["attached"] is False
    assert entry["prefix"] is None


def test_an_unreadable_config_leaves_the_entry_unattached(tmp_hub):
    path = subproject(tmp_hub, "broken")
    (path / "config.yaml").write_text("prefix: [unclosed\n")

    entry = hub_store(tmp_hub, "broken")

    assert entry["attached"] is False
    assert entry["prefix"] is None


def test_a_store_copied_into_a_real_checkout_is_not_attached(tmp_hub):
    """Inside a git checkout only a genuine worktree counts as attached.

    This is the case ``projectman migrate-hub`` (US-PM-31-8) exists to fix: PM
    data sitting in the subproject as ordinary tracked files, rather than
    mounted from the submodule's ``projectman`` branch.
    """
    path = subproject(tmp_hub, "api", "API")
    checkout = subproject_path(tmp_hub, "api")
    subprocess.run(["git", "init"], cwd=str(checkout), capture_output=True, check=True)

    assert (checkout / ".git").exists()
    assert path.is_dir() and (path / "config.yaml").exists()
    assert hub_store(tmp_hub, "api")["attached"] is False


def test_an_unattached_store_does_not_hide_the_attached_ones(tmp_hub):
    subproject(tmp_hub, "api", "API")
    register(tmp_hub, "ghost")
    subproject(tmp_hub, "web", "WEB")

    entries = hub_stores(tmp_hub)

    assert [(e["name"], e["attached"]) for e in entries] == [
        ("api", True),
        ("ghost", False),
        ("web", True),
    ]


def test_an_explicit_attached_check_can_be_injected(tmp_hub):
    """Callers that know better (tests, the migrations) can supply the rule."""
    subproject(tmp_hub, "api", "API")

    assert hub_stores(tmp_hub, attached_check=lambda p: False)[0]["attached"] is False
    assert hub_stores(tmp_hub, attached_check=lambda p: True)[0]["attached"] is True
    # ...and the injected answer is never written to the shared cache.
    assert hub_stores(tmp_hub)[0]["attached"] is True


# ─── Caching ─────────────────────────────────────────────────────


def test_the_map_is_cached_per_process(tmp_hub):
    subproject(tmp_hub, "api", "API")

    first = hub_stores(tmp_hub)
    assert hub_stores(tmp_hub) is first


def test_invalidate_drops_the_cached_map(tmp_hub):
    subproject(tmp_hub, "api", "API")
    first = hub_stores(tmp_hub)

    invalidate(tmp_hub)

    second = hub_stores(tmp_hub)
    assert second is not first
    assert second == first


def test_invalidate_with_no_root_drops_everything(tmp_hub):
    subproject(tmp_hub, "api", "API")
    first = hub_stores(tmp_hub)

    invalidate()

    assert hub_stores(tmp_hub) is not first


def test_the_cache_does_not_outlive_a_store_appearing(tmp_hub):
    """A store mounted after the first read must not be reported missing.

    The cache is validated against the stats it was built from, so nobody has
    to remember to invalidate for this — which is exactly the bug that a
    blindly trusted map produces (a subproject store mounted by
    ``migrate-worktree`` still reading as unattached).
    """
    register(tmp_hub, "api")
    assert hub_store(tmp_hub, "api")["attached"] is False

    make_store(tmp_hub, "api", "API")

    entry = hub_store(tmp_hub, "api")
    assert entry["attached"] is True
    assert entry["prefix"] == "API"


def test_the_cache_does_not_outlive_a_newly_registered_project(tmp_hub):
    subproject(tmp_hub, "api", "API")
    assert [e["name"] for e in hub_stores(tmp_hub)] == ["api"]

    subproject(tmp_hub, "web", "WEB")

    assert [e["name"] for e in hub_stores(tmp_hub)] == ["api", "web"]


# ─── The readers go through the map ──────────────────────────────


def test_server_store_resolves_a_subproject_through_the_map(tmp_hub, monkeypatch):
    subproject(tmp_hub, "api", "API")
    monkeypatch.chdir(tmp_hub)
    from projectman.server import _project_dir_for_prefix, _store_for_prefix

    assert _store_for_prefix("API").project_dir == store_path(tmp_hub, "api")
    assert _project_dir_for_prefix("API") == store_path(tmp_hub, "api")
    assert _project_dir_for_prefix() == tmp_hub / ".project"


def test_server_store_refuses_a_subproject_with_no_store_on_disk(tmp_hub, monkeypatch):
    """Registered but storeless: it claims no prefix, so nothing addresses it.

    The old ``_store(project="ghost")`` failed on the missing directory; with
    US-PM-34 there is no name to pass, and the map simply has no entry for the
    prefix — the coded ``not_found`` that lists the prefixes that do exist.
    """
    register(tmp_hub, "ghost")
    monkeypatch.chdir(tmp_hub)
    from projectman.errors import NotFoundError
    from projectman.server import _store_for_prefix

    with pytest.raises(NotFoundError, match="GHOST"):
        _store_for_prefix("GHOST")


def test_the_web_api_resolves_a_subproject_through_the_map(tmp_hub, monkeypatch):
    subproject(tmp_hub, "api", "API")
    monkeypatch.chdir(tmp_hub)
    from projectman.web.routes import api

    monkeypatch.setattr(api, "find_project_root", lambda: tmp_hub)
    api._hub_store_cache.clear()

    assert api.get_project_dir(project="api") == store_path(tmp_hub, "api")
    assert api.get_store(project="api").project_dir == store_path(tmp_hub, "api")

    from fastapi import HTTPException

    register(tmp_hub, "ghost")
    with pytest.raises(HTTPException):
        api.get_project_dir(project="ghost")


def test_the_rollup_reads_each_subproject_from_its_own_store(tmp_hub):
    from projectman.hub.rollup import rollup
    from projectman.store import Store

    subproject(tmp_hub, "api", "API")
    Store(tmp_hub, project_dir=store_path(tmp_hub, "api")).create_story(
        "A story", "Body", points=5
    )
    register(tmp_hub, "ghost")

    result = rollup(tmp_hub)

    by_name = {p["name"]: p for p in result["projects"]}
    assert by_name["api"]["stories"] == 1
    assert by_name["api"]["total_points"] == 5
    # A registered project with no store is reported, never raised over
    # (US-PM-31-9) — see tests/test_hub_unattached.py for the full rule.
    assert by_name["ghost"]["status"] == "not attached"


def test_workflow_badges_are_discovered_in_the_subprojects_checkout(tmp_hub):
    from projectman.indexer import _discover_badges

    workflows = subproject_path(tmp_hub, "api") / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\n")

    badges = _discover_badges(tmp_hub, "api", "owner/api")

    assert len(badges) == 1
    assert "CI" in badges[0]


# ─── Source scan ─────────────────────────────────────────────────

#: The two constructions US-PM-31 retired: the hub-side store path, and any
#: hand-rolled join onto the ``projects`` directory.  ``hub/stores.py`` builds
#: both from its own constants, so neither literal survives anywhere.
OLD_PATHS = re.compile(r'\.project/projects|"projects" /')


#: The single exemption.  ``projectman migrate-hub`` (US-PM-31-8) is the one
#: thing that still has to *find* the retired layout — it is the command that
#: takes a hub off it — so ``hub/migrate.py`` keeps one clearly named helper
#: for the old location and nothing else may name it.  The allow-list is by
#: (file, function), resolved through ``ast`` to that function's own line
#: span, so a stray reference elsewhere in ``migrate.py`` still fails.
LEGACY_PATH_EXEMPTIONS = {("hub/migrate.py", "legacy_store_path")}


def _python_sources():
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _exempt_lines(path):
    """The line numbers of the allow-listed functions in *path*."""
    rel = path.relative_to(SRC / "projectman").as_posix()
    wanted = {func for file, func in LEGACY_PATH_EXEMPTIONS if file == rel}
    if not wanted:
        return set()
    tree = ast.parse(path.read_text())
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            lines |= set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def test_the_source_scan_finds_the_python_files_it_is_supposed_to():
    """Guard the guard: an empty scan must not be able to pass silently."""
    names = {p.name for p in _python_sources()}
    assert {"server.py", "cli.py", "indexer.py", "registry.py", "stores.py"} <= names


def test_the_exempted_helper_exists_and_is_the_only_one():
    """Guard the exemption: it may not quietly stop matching anything."""
    migrate = SRC / "projectman" / "hub" / "migrate.py"
    exempt = _exempt_lines(migrate)
    assert exempt, "hub/migrate.py no longer defines legacy_store_path"
    text = migrate.read_text().splitlines()
    hits = {n for n in exempt if OLD_PATHS.search(text[n - 1])}
    assert hits, (
        "legacy_store_path no longer names the retired layout — if the old "
        "path is really gone, delete the exemption too"
    )


def test_no_source_file_builds_the_old_subproject_store_path():
    """``grep -rn "\\.project/projects\\|\\"projects\\" /" src/`` finds nothing.

    Both spellings are gone: ``.project/projects`` (the hub-side store, in
    code and in prose) and ``"projects" /`` (any path built by joining the
    literal onto a root).  ``projectman.hub.stores`` owns the layout now, and
    builds it from ``PROJECTS_DIRNAME``/``STORE_DIRNAME`` so not even its own
    definition matches.

    One exemption, ``LEGACY_PATH_EXEMPTIONS``: ``migrate-hub`` has to name the
    old location to migrate off it, and does so from exactly one helper.
    """
    offenders = []
    for path in _python_sources():
        exempt = _exempt_lines(path)
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if lineno in exempt:
                continue
            if OLD_PATHS.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "these still build or name the retired subproject store path — route "
        "them through projectman.hub.stores:\n" + "\n".join(offenders)
    )
