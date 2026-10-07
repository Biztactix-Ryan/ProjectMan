"""The committed plugin files match the templates, and versions agree (US-PM-56-10, ADR-006).

The repo root is the Claude Code plugin. Its agents/ and skills/ are rendered
from src/projectman/templates by `projectman build-plugin` and committed, so a
template edit without a rebuild ships stale skills. These tests re-render
through the same code path into tmp_path and compare byte for byte.

The plugin version in .claude-plugin/plugin.json must equal pyproject.toml's:
Claude Code only offers a plugin update when that version rises.
"""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import CLAUDE_SKILLS, cli

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / ".claude-plugin"
REBUILD = "run `projectman build-plugin` from the repo root and commit the result"


def _files(root: Path, subdirs=("agents", "skills")) -> dict[Path, bytes]:
    found = {}
    for sub in subdirs:
        base = root / sub
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    found[path.relative_to(root)] = path.read_bytes()
    return found


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("plugin")
    result = CliRunner().invoke(cli, ["build-plugin", str(out)])
    assert result.exit_code == 0, result.output
    return _files(out)


def test_committed_plugin_files_match_templates(rendered):
    committed = _files(REPO_ROOT)
    missing = sorted(str(p) for p in rendered if p not in committed)
    stale = sorted(str(p) for p in rendered if p in committed and committed[p] != rendered[p])
    assert not missing, f"plugin files missing: {missing}; {REBUILD}"
    assert not stale, f"plugin files differ from the templates: {stale}; {REBUILD}"


def test_no_extra_plugin_files(rendered):
    extra = sorted(str(p) for p in _files(REPO_ROOT) if p not in rendered)
    assert not extra, (
        f"plugin files not produced by build-plugin: {extra}; remove them or add the "
        f"skill to CLAUDE_SKILLS, then {REBUILD}"
    )


def test_no_extra_skill_dirs():
    known = {name for name, _ in CLAUDE_SKILLS}
    dirs = {p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir()}
    extra = sorted(dirs - known)
    assert not extra, (
        f"skills/ holds dirs that are not in CLAUDE_SKILLS: {extra}; {REBUILD}"
    )


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text()
    try:
        import tomllib
    except ImportError:  # Python 3.10
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert match, "no version in pyproject.toml"
        return match.group(1)
    return tomllib.loads(text)["project"]["version"]


def test_plugin_version_matches_pyproject():
    plugin = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    assert plugin["version"] == _pyproject_version(), (
        "bump .claude-plugin/plugin.json's version together with pyproject.toml's"
    )


def test_marketplace_entry_does_not_pin_a_different_version():
    # plugin.json is the version source; the marketplace entry carries none.
    # If one is ever added it must agree, or the two silently disagree.
    marketplace = json.loads((PLUGIN_DIR / "marketplace.json").read_text())
    version = _pyproject_version()
    for entry in marketplace["plugins"]:
        if "version" in entry:
            assert entry["version"] == version, entry["name"]
