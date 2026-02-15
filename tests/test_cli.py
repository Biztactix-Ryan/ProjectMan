"""Tests for CLI commands."""

import json
import pytest
from click.testing import CliRunner
from pathlib import Path

from projectman.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestInit:
    def test_init_basic(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--name", "myproject", "--prefix", "MY"])
            assert result.exit_code == 0
            assert Path(".project/config.yaml").exists()
            assert Path(".project/stories").is_dir()
            assert Path(".project/tasks").is_dir()

    def test_init_hub(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--name", "myhub", "--hub"])
            assert result.exit_code == 0
            assert Path(".project/projects").is_dir()
            assert Path(".project/roadmap").is_dir()
            assert Path(".project/dashboards").is_dir()

    def test_init_already_exists(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["init", "--name", "proj"])
            assert result.exit_code != 0


class TestSetupClaude:
    def test_setup_claude(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["setup-claude"])
            assert result.exit_code == 0
            assert Path(".mcp.json").exists()
            assert Path(".claude/agents/pm.md").exists()
            assert Path(".claude/skills/pm/SKILL.md").exists()
            assert Path(".claude/skills/pm-status/SKILL.md").exists()

    def test_setup_claude_merges_mcp(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            # Write existing .mcp.json
            existing = {"mcpServers": {"other": {"command": "other"}}}
            Path(".mcp.json").write_text(json.dumps(existing))
            runner.invoke(cli, ["setup-claude"])
            with open(".mcp.json") as f:
                config = json.load(f)
            assert "other" in config["mcpServers"]
            assert "projectman" in config["mcpServers"]
