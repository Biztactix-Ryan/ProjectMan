"""Tests for `projectman build-plugin` (US-PM-56-8, ADR-006).

The plugin's agent and skills are rendered from src/projectman/templates, the
same templates setup-claude uses, so the templates stay the single source.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import CLAUDE_SKILLS, STALE_SKILLS, _render_template, cli


def _expected_files():
    files = {Path("agents") / "pm.md": _render_template("agent_pm.md.j2")}
    for skill_name, template_name in CLAUDE_SKILLS:
        files[Path("skills") / skill_name / "SKILL.md"] = _render_template(template_name)
    return files


@pytest.fixture
def built(tmp_path):
    result = CliRunner().invoke(cli, ["build-plugin", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_writes_every_skill_and_the_agent(built):
    written = {p.relative_to(built) for p in built.rglob("*") if p.is_file()}
    assert written == set(_expected_files())


def test_output_equals_rendered_templates(built):
    for rel, content in _expected_files().items():
        assert "template not found" not in content, rel
        assert (built / rel).read_text() == content, rel


def test_build_is_deterministic(built):
    first = {p: p.read_bytes() for p in built.rglob("*") if p.is_file()}
    result = CliRunner().invoke(cli, ["build-plugin", str(built)])
    assert result.exit_code == 0, result.output
    assert {p: p.read_bytes() for p in built.rglob("*") if p.is_file()} == first


def test_removes_stale_skills(tmp_path):
    stale = tmp_path / "skills" / STALE_SKILLS[0]
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("old")
    result = CliRunner().invoke(cli, ["build-plugin", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert not stale.exists()


def test_defaults_to_current_directory(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        result = runner.invoke(cli, ["build-plugin"])
        assert result.exit_code == 0, result.output
        assert (Path(cwd) / "agents" / "pm.md").exists()
        assert (Path(cwd) / "skills" / "pm" / "SKILL.md").exists()
