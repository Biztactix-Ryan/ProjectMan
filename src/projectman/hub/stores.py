"""Where a hub keeps each subproject's PM data — the store map.

Layout (US-PM-31).  A subproject's PM data lives *inside that subproject's own
checkout*, at ``projects/{name}/.project``, which is a git worktree of the
submodule's ``projectman`` branch.  It used to live in the hub's own store,
under a ``projects/{name}`` subdirectory of it, which meant every task edit in
every project landed as a commit on the hub repo.  Nothing reads that old
location any more.

This module owns the two layout constants and is the only place under ``src/``
that joins them onto a root.  Every former hub-side subproject reader —
``server._project_dir_for_prefix`` / ``server._store_for_prefix``, ``hub/rollup.py``,
``indexer.py``, ``cli.py``, ``web/routes/api.py`` and ``hub/registry.py`` —
goes through :func:`hub_stores`, :func:`store_path` or
:func:`subproject_path`.  ``tests/test_hub_stores.py`` has a source-scan guard
that greps ``src/`` for the two old path constructions and fails if either
comes back, so a future move of the layout stays a single edit here.

What "attached" means
---------------------
A store is *attached* when a worktree is actually mounted at
``projects/{name}/.project`` and it carries a readable ``config.yaml``.  Two
things make that testable without every fixture having to build real git
worktrees:

* the strict clause — :func:`projectman.worktree.is_worktree`, i.e. the
  store's ``.git`` is a *file* pointing back at the submodule's git dir; and
* the fixture clause — the enclosing checkout at ``projects/{name}`` is not a
  git repository at all (no ``.git`` entry), which is what a ``tmp_path`` hub
  looks like.  A plain directory there is treated as attached.

Inside a real checkout (``projects/{name}/.git`` present, as any submodule
has) only the strict clause applies, so PM data that was *copied* into
``projects/{name}/.project`` rather than mounted reports ``attached: False``.
That is the case ``projectman migrate-hub`` (US-PM-31-8) exists to fix, and
the case the rollup reports as "not attached" rather than raising
(US-PM-31-9).  ``add-project`` (US-PM-31-7) is what makes a fresh subproject
attached in the strict sense.

Callers that need a different rule can pass their own ``attached_check`` —
``hub_stores(root, attached_check=...)`` bypasses the cache and is meant for
tests and for the migration commands, not for the read path.

Cost and caching
----------------
Building the map is a couple of ``stat`` calls and at most one small YAML
read per registered project, and the built list is cached per process keyed
by resolved root, the same way ``server._store_cache`` caches Stores.

The cache is checked against the stats rather than trusted blindly: a cached
map is reused only while the registered names, each ``config.yaml``'s
mtime/size and each attachment answer are unchanged.  So the YAML parse — the
expensive half — happens once, while a store that has just been mounted, or a
prefix that has just been rewritten, is picked up on the next call without
anyone having to remember to invalidate.  :func:`invalidate` is still there
for the cases stats cannot see, and ``config.clear_config_cache`` calls it
because the map is derived from ``config.projects``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import yaml

#: Directory under the hub root holding the subproject checkouts (submodules).
PROJECTS_DIRNAME = "projects"

#: The PM store directory name, both for the hub itself and inside a checkout.
STORE_DIRNAME = ".project"


def hub_store_dir(root: Path) -> Path:
    """The hub's own store directory (``{root}/.project``)."""
    return Path(root) / STORE_DIRNAME


def projects_dir(root: Path) -> Path:
    """The directory holding the subproject checkouts (``{root}/projects``)."""
    return Path(root) / PROJECTS_DIRNAME


def subproject_path(root: Path, name: str) -> Path:
    """The subproject's checkout directory (``{root}/projects/{name}``)."""
    return Path(root) / PROJECTS_DIRNAME / name


def store_path(root: Path, name: str) -> Path:
    """The subproject's PM store (``{root}/projects/{name}/.project``)."""
    return subproject_path(root, name) / STORE_DIRNAME


def default_attached_check(path: Path) -> bool:
    """Is a store mounted at *path*?  See the module docstring.

    True when ``path`` is a git worktree, or when the checkout that contains
    it is not a git repository at all (the plain-directory fixture case).
    """
    from ..worktree import is_worktree

    path = Path(path)
    if not path.is_dir():
        return False
    if is_worktree(path):
        return True
    return not (path.parent / ".git").exists()


def _read_prefix(store_dir: Path) -> Optional[str]:
    """Return ``prefix`` from a store's own config.yaml, or None."""
    try:
        data = yaml.safe_load((store_dir / "config.yaml").read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    prefix = data.get("prefix")
    return str(prefix) if prefix else None


def _stamp(store_dir: Path, attached: bool) -> tuple:
    """The cheap facts a cached entry is only valid while they hold.

    ``config.yaml``'s mtime and size (the file the prefix was parsed from)
    plus the attachment answer — everything a rebuild would notice, at the
    cost of the two stats the docstring promises.
    """
    try:
        st = (store_dir / "config.yaml").stat()
        cfg: Optional[tuple] = (st.st_mtime_ns, st.st_size)
    except OSError:
        cfg = None
    return (cfg, attached)


#: Per-process map cache, keyed by resolved hub root: ``(entries, stamps)``.
#: See :func:`invalidate`.
_map_cache: dict[Path, tuple[list[dict], list[tuple]]] = {}


def invalidate(root: Optional[Path] = None) -> None:
    """Drop the cached map for *root*, or the whole cache when root is None."""
    if root is None:
        _map_cache.clear()
        return
    _map_cache.pop(Path(root).resolve(), None)


def hub_stores(
    root: Path,
    *,
    attached_check: Optional[Callable[[Path], bool]] = None,
) -> list[dict]:
    """Locate every registered subproject's store.

    Walks ``config.projects`` in registration order and returns one entry per
    project::

        {"name": str, "prefix": str | None, "path": Path, "attached": bool}

    ``path`` is always ``{root}/projects/{name}/.project`` — the place the
    store belongs, whether or not anything is there yet.  ``attached`` is
    False for a store that is missing, is not mounted, or has no readable
    ``config.yaml``; ``prefix`` is read from that config.yaml and is None when
    it cannot be read.  A non-hub root has no subprojects, so the map is
    empty.

    The result is cached per process (see :func:`invalidate`).  Passing an
    explicit ``attached_check`` bypasses the cache entirely.
    """
    from ..config import load_config

    root = Path(root)
    key = root.resolve()
    check = attached_check or default_attached_check

    config = load_config(root)
    names = list(config.projects) if config.hub else []

    # Every store's cheap facts, computed fresh: this is the stat half of the
    # cost, and it is also the cache's validity check.
    stamps = [
        _stamp(store_path(root, name), check(store_path(root, name)))
        for name in names
    ]

    if attached_check is None:
        cached = _map_cache.get(key)
        if (
            cached is not None
            and [e["name"] for e in cached[0]] == names
            and cached[1] == stamps
        ):
            return cached[0]

    entries: list[dict] = []
    for name, (_cfg_stamp, attached) in zip(names, stamps):
        path = store_path(root, name)
        prefix = _read_prefix(path)
        entries.append(
            {
                "name": name,
                "prefix": prefix,
                "path": path,
                "attached": bool(prefix is not None and attached),
            }
        )

    if attached_check is None:
        _map_cache[key] = (entries, stamps)
    return entries


#: What a caller is told to do about a subproject whose store is not mounted.
#: One wording, so the rollup, the dashboards, ``pm_status`` and the web API
#: all point at the same two commands (US-PM-31-9).
NOT_ATTACHED = "not attached"


def attach_hint(name: str) -> str:
    """The one-line "how do I fix this" for an unattached subproject.

    Two commands, because there are exactly two ways a store ends up
    unmounted: PM data still sitting in the hub from the pre-US-PM-31 layout
    (``migrate-hub`` moves it), or a subproject that never had one
    (``add-project`` scaffolds and attaches it).
    """
    return (
        f"no store mounted at {PROJECTS_DIRNAME}/{name}/{STORE_DIRNAME} — run "
        f"`projectman migrate-hub` if this project's PM data is still in the "
        f"hub, or `projectman add-project {name} <url>` to attach a fresh one"
    )


def not_attached_row(entry: dict) -> dict:
    """The report row for an unattached map entry.

    Every hub read path renders an unattached subproject with this, so
    ``rollup``, the dashboards, ``pm_status`` and ``GET /api/status`` agree on
    the keys and on the wording.  No ``Store`` is constructed for it — that is
    the whole point: an unattached store has nothing to open, and opening it
    is what used to raise.
    """
    return {
        "name": entry["name"],
        "prefix": entry.get("prefix"),
        "status": NOT_ATTACHED,
        "hint": attach_hint(entry["name"]),
    }


def subproject_status(
    root: Path,
    *,
    attached_check: Optional[Callable[[Path], bool]] = None,
) -> list[dict]:
    """Every registered subproject with its attachment state, in hub order.

    ``[{"name", "prefix", "attached"}]``, plus ``status`` and ``hint`` on the
    unattached ones.  This is the listing ``pm_status`` and ``GET
    /api/status`` return for a hub with no project named: it reads the map and
    nothing else, so one unattached subproject cannot make the call fail.
    """
    rows: list[dict] = []
    for entry in hub_stores(root, attached_check=attached_check):
        row = {
            "name": entry["name"],
            "prefix": entry.get("prefix"),
            "attached": bool(entry["attached"]),
        }
        if not row["attached"]:
            row["status"] = NOT_ATTACHED
            row["hint"] = attach_hint(entry["name"])
        rows.append(row)
    return rows


def hub_store(
    root: Path,
    name: str,
    *,
    attached_check: Optional[Callable[[Path], bool]] = None,
) -> Optional[dict]:
    """The map entry for one subproject, or None when it is not registered."""
    for entry in hub_stores(root, attached_check=attached_check):
        if entry["name"] == name:
            return entry
    return None


def attached_store_path(root: Path, name: str) -> Path:
    """The store path for *name*, or raise if it is not an attached store.

    The single "resolve a ``--project``" helper behind ``_project_dir_for_prefix``
    and its siblings, so they all fail with the same message.
    """
    entry = hub_store(root, name)
    if entry is None or not entry["attached"]:
        raise FileNotFoundError(f"Project '{name}' not found in hub")
    return entry["path"]
