"""US-PM-46 — ``src/projectman/hub`` is gone and nothing under ``src`` imports it.

Hub mode was removed in EPIC-PM-6: one store per project, one config shape,
one init path.  The package that carried the multi-project registry, the
subproject store map, the rollup and the migration is deleted.

A grep would be enough to notice the directory coming back, but not enough to
notice an import: ``from .hub import registry`` and
``importlib.import_module("projectman.hub.stores")`` are the same mistake
spelled differently, and one of them survives a naive search.  So the import
half is checked against the *parsed* source of every module under ``src`` —
:mod:`ast` walks ``import`` and ``from ... import`` statements, including
relative ones, and resolves each to the absolute module it names.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "projectman"

#: Every ``.py`` file shipped in the package, so the sweep cannot silently
#: shrink to nothing if the layout moves.
MODULES = sorted(p for p in PACKAGE.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names *path* imports, relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # The package a relative import inside this file is relative to.
    parts = path.relative_to(SRC).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    package = list(parts[:-1]) if parts and parts[-1] != "" else list(parts)

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            if prefix:
                names.add(prefix)
                names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return names


def test_the_hub_package_directory_does_not_exist():
    assert not (PACKAGE / "hub").exists(), (
        f"{PACKAGE / 'hub'} is back — hub mode was removed in EPIC-PM-6"
    )


def test_the_sweep_actually_covers_the_package():
    """A guard on the guard: an empty MODULES list would pass every test below."""
    assert len(MODULES) > 10, MODULES
    assert (PACKAGE / "server.py") in MODULES
    assert (PACKAGE / "cli.py") in MODULES


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_module_under_src_imports_projectman_hub(path: Path):
    offenders = {
        name
        for name in _imported_modules(path)
        if name == "projectman.hub" or name.startswith("projectman.hub.")
    }
    assert not offenders, f"{path.relative_to(SRC)} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_module_under_src_names_the_hub_package_in_text(path: Path):
    """Catches the dynamic spellings ``ast`` cannot see (importlib, __import__)."""
    text = path.read_text(encoding="utf-8")
    assert "projectman.hub" not in text, path.relative_to(SRC)
    assert "from .hub" not in text, path.relative_to(SRC)
    assert "from ..hub" not in text, path.relative_to(SRC)
