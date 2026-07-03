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

    def _upgrade_env(self, monkeypatch, which_map, ran):
        """Fake pipx list/upgrade + executable lookup for upgrade tests."""
        import subprocess

        listing = {
            "venvs": {
                "projectman": {
                    "metadata": {
                        "main_package": {
                            "package_or_url": "git+https://example.com/projectman.git",
                            "package_version": "9.9.9",
                        }
                    }
                }
            }
        }

        def fake_run(cmd, **kwargs):
            ran.append(cmd)

            class R:
                returncode = 0
                stdout = json.dumps(listing)
                stderr = ""
            return R()

        monkeypatch.setattr(
            "projectman.cli.shutil.which", lambda name: which_map.get(name)
        )
        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_upgrade_refreshes_skills_via_new_binary(self, runner, monkeypatch):
        ran = []
        self._upgrade_env(
            monkeypatch,
            {"pipx": "/usr/bin/pipx", "projectman": "/fake/bin/projectman"},
            ran,
        )
        result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code == 0
        assert ["/fake/bin/projectman", "refresh-skills"] in ran

    def test_upgrade_no_skills_skips_refresh(self, runner, monkeypatch):
        ran = []
        self._upgrade_env(
            monkeypatch,
            {"pipx": "/usr/bin/pipx", "projectman": "/fake/bin/projectman"},
            ran,
        )
        result = runner.invoke(cli, ["upgrade", "--no-skills"])
        assert result.exit_code == 0
        assert ["/fake/bin/projectman", "refresh-skills"] not in ran

    def test_upgrade_warns_when_binary_missing(self, runner, monkeypatch):
        ran = []
        self._upgrade_env(monkeypatch, {"pipx": "/usr/bin/pipx"}, ran)
        result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code == 0
        assert "refresh-skills" in result.output  # manual-run hint


class TestRefreshSkills:
    def test_refresh_skills_no_installs(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["refresh-skills"])
            assert result.exit_code == 0
            assert "No installed pm skills found" in result.output

    def test_refresh_skills_updates_existing_locations(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Install globally and locally, then stamp both stale
            runner.invoke(cli, ["setup-claude", "--global", "--local-skills"])
            global_skill = fake_home / ".claude/skills/pm/SKILL.md"
            local_skill = Path(".claude/skills/pm/SKILL.md")
            global_skill.write_text("stale")
            local_skill.write_text("stale")

            result = runner.invoke(cli, ["refresh-skills"])
            assert result.exit_code == 0
            assert global_skill.read_text() != "stale"
            assert local_skill.read_text() != "stale"
            assert "Refreshed pm skills" in result.output

    def test_refresh_skills_does_not_install_new_locations(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["setup-claude", "--global"])
            result = runner.invoke(cli, ["refresh-skills"])
            assert result.exit_code == 0
            # Global refreshed, but no project-local install created
            assert not Path(".claude/skills/pm/SKILL.md").exists()
