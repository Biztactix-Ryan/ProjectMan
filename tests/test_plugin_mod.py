"""Tests for the plugin's hooks module (US-PM-59-1).

The structural checks always run. The `claude plugin validate` / `claude plugin
test` checks run only when a `claude` binary is on PATH; both are read-only.
The plugin is never installed from here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"

CLAUDE = shutil.which("claude")
needs_claude = pytest.mark.skipif(
    CLAUDE is None,
    reason="`claude` binary not on PATH (e.g. CI); plugin validate/test checks skipped",
)


def test_hooks_json_lists_existing_module():
    modules = json.loads(HOOKS_JSON.read_text()).get("modules")
    assert isinstance(modules, list) and modules, "hooks.json has no 'modules' list"
    for module in modules:
        # Module paths are relative to the hooks/ directory.
        assert (HOOKS_JSON.parent / module).resolve().is_file(), f"missing module {module}"


def test_plugin_json_types_points_at_existing_file():
    types = json.loads(PLUGIN_JSON.read_text()).get("types")
    assert types, "plugin.json has no 'types' entry"
    assert (REPO_ROOT / types).resolve().is_file(), f"missing types file {types}"


def test_plugin_json_declares_guard_main_session_boolean_default_false():
    # US-PM-59-4: the main session is guarded only when the user opts in.
    field = json.loads(PLUGIN_JSON.read_text()).get("userConfig", {}).get("guard_main_session")
    assert field is not None, "plugin.json userConfig has no guard_main_session"
    assert field.get("type") == "boolean"
    assert field.get("default") is False


def test_mod_tests_exist():
    assert sorted((REPO_ROOT / "tests" / "mod").glob("*.test.ts")), "no tests/mod/*.test.ts"


def _run_claude(*args):
    result = subprocess.run(
        [CLAUDE, "plugin", *args, "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"claude plugin {' '.join(args)} failed ({result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    return result


@needs_claude
def test_claude_plugin_validate_passes():
    _run_claude("validate")


@needs_claude
def test_claude_plugin_test_passes():
    _run_claude("test")
