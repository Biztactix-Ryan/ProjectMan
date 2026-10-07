"""Tests for the Claude Code plugin and marketplace manifests (US-PM-56-7, ADR-006).

The repo root is both the marketplace and the plugin. Version sync with
pyproject.toml is checked separately (US-PM-56-10).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / ".claude-plugin"

LAUNCH_ARGS = [
    "run", "--project", "${CLAUDE_PLUGIN_ROOT}", "--extra", "all", "projectman", "serve",
]


def _load(name):
    return json.loads((PLUGIN_DIR / name).read_text())


def test_plugin_json_names_projectman():
    plugin = _load("plugin.json")
    assert plugin["name"] == "projectman"
    assert plugin["version"]


def test_plugin_launches_server_with_uv_run():
    server = _load("plugin.json")["mcpServers"]["projectman"]
    assert server["command"] == "uv"
    assert server["args"] == LAUNCH_ARGS


def test_no_root_mcp_json():
    # A root .mcp.json would also be read as this repo's project-scope MCP
    # config and start a second server for developers; the server is inline.
    assert not (REPO_ROOT / ".mcp.json").exists()


def test_marketplace_lists_root_plugin():
    marketplace = _load("marketplace.json")
    entries = {p["name"]: p for p in marketplace["plugins"]}
    assert entries["projectman"]["source"] == "./"
