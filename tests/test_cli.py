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

    def test_setup_claude_installs_orchestrate_skill(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["setup-claude"])
            assert result.exit_code == 0
            assert Path(".claude/skills/pm-orchestrate/SKILL.md").exists()
            assert Path(".claude/skills/pm-do/SKILL.md").exists()

    def test_install_alias(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["install"])
            assert result.exit_code == 0
            assert Path(".claude/skills/pm/SKILL.md").exists()

    def test_setup_claude_removes_stale_skills(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            stale = Path(".claude/skills/pm-audit")
            stale.mkdir(parents=True)
            (stale / "SKILL.md").write_text("old")
            runner.invoke(cli, ["setup-claude"])
            assert not stale.exists()

    def test_setup_claude_global(self, runner, tmp_path, monkeypatch):
        import shutil as _shutil

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        # No claude CLI available — should print the manual command, not fail
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["setup-claude", "--global"])
            assert result.exit_code == 0
            assert (fake_home / ".claude/skills/pm/SKILL.md").exists()
            assert (fake_home / ".claude/skills/pm-orchestrate/SKILL.md").exists()
            assert (fake_home / ".claude/agents/pm.md").exists()
            # No project-level files without --local-skills
            assert not Path(".claude/skills/pm/SKILL.md").exists()
            assert not Path(".mcp.json").exists()
            assert "claude mcp add" in result.output

    def test_setup_claude_global_with_local_skills(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home2"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["setup-claude", "--global", "--local-skills"])
            assert result.exit_code == 0
            assert (fake_home / ".claude/skills/pm/SKILL.md").exists()
            assert Path(".claude/skills/pm/SKILL.md").exists()


class TestUpgrade:
    def test_upgrade_without_pipx(self, runner, monkeypatch):
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code != 0
        assert "pipx not found" in result.output

    def test_upgrade_check_not_pipx_managed(self, runner, monkeypatch):
        import subprocess

        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: "/usr/bin/pipx")

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = json.dumps({"venvs": {}})
                stderr = ""
            return R()

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = runner.invoke(cli, ["upgrade", "--check"])
        assert result.exit_code != 0
        assert "not managed by pipx" in result.output

    def test_upgrade_check_shows_source(self, runner, monkeypatch):
        import subprocess

        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: "/usr/bin/pipx")
        listing = {
            "venvs": {
                "projectman": {
                    "metadata": {
                        "main_package": {
                            "package_or_url": "git+https://example.com/projectman.git",
                            "package_version": "0.8.10",
                        }
                    }
                }
            }
        }

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = json.dumps(listing)
                stderr = ""
            return R()

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = runner.invoke(cli, ["upgrade", "--check"])
        assert result.exit_code == 0
        assert "git+https://example.com/projectman.git" in result.output

    def test_update_alias(self, runner, monkeypatch):
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        result = runner.invoke(cli, ["update"])
        assert result.exit_code != 0
        assert "pipx not found" in result.output
