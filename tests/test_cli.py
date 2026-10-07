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

    def test_init_already_exists(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["init", "--name", "proj"])
            assert result.exit_code != 0


class TestSetupClaude:
    def test_setup_claude(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["setup-claude", "--legacy"])
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
            runner.invoke(cli, ["setup-claude", "--legacy"])
            with open(".mcp.json") as f:
                config = json.load(f)
            assert "other" in config["mcpServers"]
            assert "projectman" in config["mcpServers"]

    def test_setup_claude_installs_orchestrate_skill(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["setup-claude", "--legacy"])
            assert result.exit_code == 0
            assert Path(".claude/skills/pm-orchestrate/SKILL.md").exists()
            assert Path(".claude/skills/pm-do/SKILL.md").exists()

    def test_install_alias(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            result = runner.invoke(cli, ["install", "--legacy"])
            assert result.exit_code == 0
            assert Path(".claude/skills/pm/SKILL.md").exists()

    def test_setup_claude_removes_stale_skills(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--name", "proj"])
            stale = Path(".claude/skills/pm-audit")
            stale.mkdir(parents=True)
            (stale / "SKILL.md").write_text("old")
            runner.invoke(cli, ["setup-claude", "--legacy"])
            assert not stale.exists()

    def test_setup_claude_global(self, runner, tmp_path, monkeypatch):
        import shutil as _shutil

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        # No claude CLI available — should print the manual command, not fail
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["setup-claude", "--legacy", "--global"])
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
            result = runner.invoke(cli, ["setup-claude", "--legacy", "--global", "--local-skills"])
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

    def _home_with_copies(self, tmp_path, monkeypatch, copies=True):
        """Point HOME at a tmp dir, optionally holding setup-claude skill copies."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        if copies:
            skill = fake_home / ".claude/skills/pm/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: pm\n---\n")

    def test_upgrade_refreshes_existing_copies_via_new_binary_legacy(self, runner, tmp_path, monkeypatch):
        """Existing setup-claude copies are re-rendered through the hidden --legacy path."""
        ran = []
        self._home_with_copies(tmp_path, monkeypatch)
        self._upgrade_env(
            monkeypatch,
            {"pipx": "/usr/bin/pipx", "projectman": "/fake/bin/projectman"},
            ran,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code == 0
        assert ["/fake/bin/projectman", "refresh-skills", "--legacy"] in ran
        assert "migrate-to-plugin" in result.output

    def test_upgrade_without_copies_refreshes_nothing(self, runner, tmp_path, monkeypatch):
        """No setup-claude copies (e.g. a plugin install): upgrade creates none."""
        ran = []
        self._home_with_copies(tmp_path, monkeypatch, copies=False)
        self._upgrade_env(
            monkeypatch,
            {"pipx": "/usr/bin/pipx", "projectman": "/fake/bin/projectman"},
            ran,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code == 0
        assert not any("refresh-skills" in cmd for cmd in ran)

    def test_upgrade_no_skills_skips_refresh(self, runner, tmp_path, monkeypatch):
        ran = []
        self._home_with_copies(tmp_path, monkeypatch)
        self._upgrade_env(
            monkeypatch,
            {"pipx": "/usr/bin/pipx", "projectman": "/fake/bin/projectman"},
            ran,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["upgrade", "--no-skills"])
        assert result.exit_code == 0
        assert not any("refresh-skills" in cmd for cmd in ran)

    def test_upgrade_warns_when_binary_missing(self, runner, tmp_path, monkeypatch):
        ran = []
        self._home_with_copies(tmp_path, monkeypatch)
        self._upgrade_env(monkeypatch, {"pipx": "/usr/bin/pipx"}, ran)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["upgrade"])
        assert result.exit_code == 0
        assert "refresh-skills --legacy" in result.output  # manual-run hint


class TestDeprecationShims:
    """setup-claude and refresh-skills point to the plugin and write nothing (US-PM-57-8)."""

    REPO = Path(__file__).resolve().parent.parent

    def _snapshot(self, *roots):
        return {
            str(p): (p.read_bytes() if p.is_file() else None)
            for root in roots
            for p in sorted(root.rglob("*"))
        }

    @pytest.mark.parametrize(
        "args",
        [
            ["setup-claude"],
            ["setup-claude", "--global", "--local-skills"],
            ["install"],
            ["refresh-skills"],
            ["refresh-skills", "--keep-local"],
        ],
    )
    def test_shim_prints_plugin_install_and_writes_nothing(self, runner, tmp_path, monkeypatch, args):
        import subprocess

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        work = tmp_path / "work"
        work.mkdir()
        # Existing copies present: the shim must not refresh or prune them either.
        for root in (fake_home, work):
            skill = root / ".claude/skills/pm/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("stale")

        def no_subprocess(cmd, **kwargs):
            raise AssertionError(f"shim ran a subprocess: {cmd}")

        monkeypatch.setattr(subprocess, "run", no_subprocess)
        monkeypatch.chdir(work)
        before = self._snapshot(fake_home, work)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert self._snapshot(fake_home, work) == before
        out = result.output
        assert "deprecated" in out
        assert "/plugin marketplace add Biztactix-Ryan/ProjectMan" in out
        assert "/plugin install projectman@projectman" in out
        assert "projectman migrate-to-plugin" in out
        assert "Nothing was written" in out

    def test_shim_names_match_marketplace_and_docs(self):
        """The printed names are the real marketplace/plugin names and the documented commands."""
        from projectman.cli import PLUGIN_INSTALL_REF, PLUGIN_MARKETPLACE_SOURCE

        market = json.loads((self.REPO / ".claude-plugin/marketplace.json").read_text())
        plugin_names = {p["name"] for p in market["plugins"]}
        plugin, _, marketplace = PLUGIN_INSTALL_REF.partition("@")
        assert marketplace == market["name"]
        assert plugin in plugin_names
        docs = (self.REPO / "docs/installation.md").read_text()
        section = docs.split("## Install as a Claude Code plugin", 1)[1]
        assert f"/plugin marketplace add {PLUGIN_MARKETPLACE_SOURCE}" in section
        assert f"/plugin install {PLUGIN_INSTALL_REF}" in section

    @pytest.mark.parametrize("command", ["setup-claude", "refresh-skills"])
    def test_legacy_flag_is_hidden(self, runner, command):
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0
        assert "--legacy" not in result.output.split("Options:", 1)[1]

    def test_setup_claude_legacy_still_installs(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["setup-claude", "--legacy"])
            assert result.exit_code == 0
            assert Path(".mcp.json").exists()
            assert Path(".claude/skills/pm/SKILL.md").exists()
            assert "deprecated" not in result.output

    def test_refresh_skills_legacy_still_refreshes(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["setup-claude", "--legacy"])
            local_skill = Path(".claude/skills/pm/SKILL.md")
            local_skill.write_text("stale")
            result = runner.invoke(cli, ["refresh-skills", "--legacy"])
            assert result.exit_code == 0
            assert local_skill.read_text() != "stale"
            assert "Refreshed pm skills" in result.output


class TestRefreshSkills:
    def test_refresh_skills_no_installs(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["refresh-skills", "--legacy"])
            assert result.exit_code == 0
            assert "No installed pm skills found" in result.output

    def test_refresh_skills_prunes_superseded_local_copies(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Install globally and locally — local copies are duplicates
            runner.invoke(cli, ["setup-claude", "--legacy", "--global", "--local-skills"])
            # A non-pm skill must survive the prune
            other = Path(".claude/skills/custom")
            other.mkdir(parents=True)
            (other / "SKILL.md").write_text("mine")
            global_skill = fake_home / ".claude/skills/pm/SKILL.md"
            global_skill.write_text("stale")

            result = runner.invoke(cli, ["refresh-skills", "--legacy"])
            assert result.exit_code == 0
            assert "superseded" in result.output
            # Local pm copies pruned, global refreshed, other skills untouched
            assert not Path(".claude/skills/pm/SKILL.md").exists()
            assert not Path(".claude/skills/pm-do").exists()
            assert not Path(".claude/agents/pm.md").exists()
            assert (other / "SKILL.md").read_text() == "mine"
            assert global_skill.read_text() != "stale"
            assert "Restart Claude Code" in result.output

    def test_refresh_skills_keep_local_refreshes_both(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["setup-claude", "--legacy", "--global", "--local-skills"])
            global_skill = fake_home / ".claude/skills/pm/SKILL.md"
            local_skill = Path(".claude/skills/pm/SKILL.md")
            global_skill.write_text("stale")
            local_skill.write_text("stale")

            result = runner.invoke(cli, ["refresh-skills", "--legacy", "--keep-local"])
            assert result.exit_code == 0
            assert global_skill.read_text() != "stale"
            assert local_skill.read_text() != "stale"
            assert "Refreshed pm skills" in result.output

    def test_refresh_skills_local_only_is_refreshed_not_pruned(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Local install only — no global to supersede it
            runner.invoke(cli, ["init", "--name", "proj"])
            runner.invoke(cli, ["setup-claude", "--legacy"])
            local_skill = Path(".claude/skills/pm/SKILL.md")
            local_skill.write_text("stale")

            result = runner.invoke(cli, ["refresh-skills", "--legacy"])
            assert result.exit_code == 0
            assert local_skill.read_text() != "stale"
            assert "Restart Claude Code" in result.output

    def test_refresh_skills_does_not_install_new_locations(self, runner, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["setup-claude", "--legacy", "--global"])
            result = runner.invoke(cli, ["refresh-skills", "--legacy"])
            assert result.exit_code == 0
            # Global refreshed, but no project-local install created
            assert not Path(".claude/skills/pm/SKILL.md").exists()
