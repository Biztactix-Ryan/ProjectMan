"""Tests for `projectman migrate-to-plugin` (US-PM-57-6, US-PM-57-7).

Every test runs with HOME and Path.home() pointed into tmp_path, cwd in
tmp_path, and the `claude` CLI mocked — the real ~/.claude and the real
user-scope MCP server are never touched.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import CLAUDE_SKILLS, cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    return proj


@pytest.fixture
def no_claude(monkeypatch):
    """No claude binary; any subprocess call fails the test."""
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)

    def boom(cmd, **kwargs):
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(subprocess, "run", boom)


@pytest.fixture
def fake_claude(monkeypatch):
    """A mocked claude CLI. Set `state["user_entry"]` to control `mcp get`."""
    state = {"user_entry": True, "ran": []}
    monkeypatch.setattr(
        "projectman.cli.shutil.which",
        lambda name: "/fake/bin/claude" if name == "claude" else None,
    )

    def fake_run(cmd, **kwargs):
        state["ran"].append(list(cmd))
        if cmd[:3] == ["claude", "mcp", "get"]:
            if state["user_entry"]:
                out = "projectman:\n  Scope: User config (available in all your projects)\n"
                return subprocess.CompletedProcess(cmd, 0, out, "")
            return subprocess.CompletedProcess(cmd, 1, "", "No MCP server found")
        if cmd[:3] == ["claude", "mcp", "remove"]:
            return subprocess.CompletedProcess(cmd, 0, "Removed", "")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state


def _install(home: Path, project: Path, monkeypatch) -> None:
    """Install the way setup-claude does: globally and into the project."""
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
    result = CliRunner().invoke(cli, ["setup-claude", "--legacy", "--global", "--local-skills"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(cli, ["setup-claude", "--legacy"])  # writes ./.mcp.json
    assert result.exit_code == 0, result.output


def _snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def _invoke(*args):
    result = CliRunner().invoke(cli, ["migrate-to-plugin", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_dry_run_lists_changes_and_writes_nothing(home, project, monkeypatch):
    _install(home, project, monkeypatch)
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"projectman": {"command": "projectman"}}}))
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)
    before_home, before_proj = _snapshot(home), _snapshot(project)

    out = _invoke("--dry-run")

    assert _snapshot(home) == before_home
    assert _snapshot(project) == before_proj
    for root in (home / ".claude", project / ".claude"):
        assert f"would remove {root / 'agents' / 'pm.md'}" in out
        for name, _ in CLAUDE_SKILLS:
            assert f"would remove {root / 'skills' / name}/" in out
    assert f"would delete {project / '.mcp.json'}" in out
    assert "manual step: claude CLI not found — run claude mcp remove --scope user projectman" in out
    assert "nothing written" in out
    # every change line is a "would" line (or a manual step)
    change_lines = [l for l in out.splitlines() if l.startswith(("remove", "delete", "run"))]
    assert change_lines == []


def test_dry_run_with_claude_cli_lists_all_three_change_kinds(home, project, monkeypatch, fake_claude):
    """US-PM-57-3: with the claude CLI present (stubbed) and a user-scope
    entry registered, --dry-run lists the skills/agent removals in both
    .claude/ dirs, the user-scope MCP removal and the .mcp.json edit, and
    writes nothing — no file changes and no `claude mcp remove` call."""
    _install(home, project, monkeypatch)
    monkeypatch.setattr(  # _install hid the binary; restore the stub
        "projectman.cli.shutil.which",
        lambda name: "/fake/bin/claude" if name == "claude" else None,
    )
    mcp = project / ".mcp.json"
    data = json.loads(mcp.read_text())
    data["mcpServers"]["other"] = {"command": "other-server"}
    mcp.write_text(json.dumps(data))
    before_home, before_proj = _snapshot(home), _snapshot(project)
    assert before_home and any(k.startswith(".claude/skills/") for k in before_home)

    out = _invoke("--dry-run")

    # byte-identical trees: both .claude/ dirs, .mcp.json, everything else
    assert _snapshot(home) == before_home
    assert _snapshot(project) == before_proj
    # the user-scope entry was only queried, never removed
    assert fake_claude["ran"] == [["claude", "mcp", "get", "projectman"]]
    # 1. skills and agent in both .claude/ dirs
    for root in (home / ".claude", project / ".claude"):
        assert f"would remove {root / 'agents' / 'pm.md'}" in out
        for name, _ in CLAUDE_SKILLS:
            assert f"would remove {root / 'skills' / name}/" in out
    # 2. user-scope MCP server
    assert "would run claude mcp remove --scope user projectman" in out
    # 3. .mcp.json entry (other server kept)
    assert f"would remove projectman from {mcp} (keeping servers: other)" in out
    assert "nothing written" in out
    assert [l for l in out.splitlines() if l.startswith(("remove", "delete", "run"))] == []


def test_real_run_removes_managed_assets_in_home_and_project(home, project, monkeypatch, no_claude):
    _install(home, project, monkeypatch)
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)

    out = _invoke()

    for root in (home / ".claude", project / ".claude"):
        assert not (root / "agents" / "pm.md").exists()
        for name, _ in CLAUDE_SKILLS:
            assert not (root / "skills" / name).exists()
            assert f"remove {root / 'skills' / name}/" in out
        # emptied parents are cleaned up
        assert not (root / "skills").exists()
        assert not (root / "agents").exists()
    assert "would " not in out
    assert "Migrated:" in out


def test_user_authored_files_are_untouched(home, project, monkeypatch, no_claude):
    _install(home, project, monkeypatch)
    claude = home / ".claude"
    mine = claude / "skills" / "my-skill" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("---\nname: my-skill\n---\nmine\n")
    other_agent = claude / "agents" / "helper.md"
    other_agent.write_text("---\nname: helper\n---\n")
    extra = claude / "skills" / "pm-do" / "notes.txt"
    extra.write_text("my notes")
    # A SKILL.md at a pm path that ProjectMan did not write (no matching name)
    hijacked = project / ".claude" / "skills" / "pm-plan" / "SKILL.md"
    hijacked.write_text("my own planning skill, no frontmatter")
    settings = claude / "settings.json"
    settings.write_text('{"x": 1}')
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)

    out = _invoke()

    assert mine.read_text() == "---\nname: my-skill\n---\nmine\n"
    assert other_agent.exists()
    assert settings.read_text() == '{"x": 1}'
    # managed SKILL.md gone, the extra file and its dir kept
    assert extra.read_text() == "my notes"
    assert not (claude / "skills" / "pm-do" / "SKILL.md").exists()
    assert f"keep {extra}" in out
    assert hijacked.read_text() == "my own planning skill, no frontmatter"
    assert f"keep {hijacked}" in out


def test_user_authored_files_untouched_in_home_and_project(home, project, monkeypatch, no_claude):
    """US-PM-57-1: managed skills + agent go from both roots; every
    user-authored file in either .claude/ survives byte-identical."""
    _install(home, project, monkeypatch)
    home_claude, proj_claude = home / ".claude", project / ".claude"
    user_files = {}
    for root in (home_claude, proj_claude):
        user_files[root / "skills" / "my-skill" / "SKILL.md"] = b"---\nname: my-skill\n---\nmine\n"
        user_files[root / "skills" / "my-skill" / "ref.md"] = b"reference"
        user_files[root / "agents" / "helper.md"] = b"---\nname: helper\n---\n"
        user_files[root / "settings.json"] = b'{"x": 1}'
        user_files[root / "skills" / "pm-status" / "notes.txt"] = b"my notes"
    # The project's agents/pm.md replaced by a user-authored one (no name: pm).
    user_pm = proj_claude / "agents" / "pm.md"
    user_files[user_pm] = b"---\nname: my-pm-agent\n---\nmine\n"
    for path, data in user_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr("projectman.cli.shutil.which", lambda name: None)

    out = _invoke()

    for path, data in user_files.items():
        assert path.read_bytes() == data, path
    assert f"keep {user_pm}" in out
    # the managed assets are gone from both roots
    assert not (home_claude / "agents" / "pm.md").exists()
    for root in (home_claude, proj_claude):
        for name, _ in CLAUDE_SKILLS:
            assert not (root / "skills" / name / "SKILL.md").exists(), (root, name)
    # nothing beyond the user files remains under either .claude/
    for root in (home_claude, proj_claude):
        left = {p for p in root.rglob("*") if p.is_file()}
        assert left == {p for p in user_files if root in p.parents}, root


def test_mcp_json_projectman_removed_other_server_kept(home, project, monkeypatch, no_claude):
    mcp = project / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {
        "projectman": {"command": "projectman", "args": ["serve"], "type": "stdio"},
        "other": {"command": "other-server"},
    }}))

    out = _invoke("--dry-run")
    assert "projectman" in json.loads(mcp.read_text())["mcpServers"]
    assert f"would remove projectman from {mcp} (keeping servers: other)" in out

    out = _invoke()
    assert json.loads(mcp.read_text()) == {"mcpServers": {"other": {"command": "other-server"}}}
    assert f"remove projectman from {mcp}" in out


def test_mcp_json_deleted_only_when_projectman_wrote_it(home, project, no_claude):
    mcp = project / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"projectman": {"command": "projectman", "args": ["serve"], "type": "stdio"}}}))
    _invoke()
    assert not mcp.exists()

    # Hand-edited entry: key removed, file kept
    mcp.write_text(json.dumps({"mcpServers": {"projectman": {"command": "/opt/pm", "args": ["serve", "--x"]}}}))
    _invoke()
    assert json.loads(mcp.read_text()) == {"mcpServers": {}}


def test_mcp_remove_called_only_when_user_entry_exists(home, project, fake_claude):
    out = _invoke("--dry-run")
    assert ["claude", "mcp", "get", "projectman"] in fake_claude["ran"]
    assert not any(c[:3] == ["claude", "mcp", "remove"] for c in fake_claude["ran"])
    assert "would run claude mcp remove --scope user projectman" in out

    fake_claude["ran"].clear()
    out = _invoke()
    assert ["claude", "mcp", "remove", "--scope", "user", "projectman"] in fake_claude["ran"]
    assert "run claude mcp remove --scope user projectman" in out

    fake_claude["ran"].clear()
    fake_claude["user_entry"] = False
    out = _invoke()
    assert fake_claude["ran"] == [["claude", "mcp", "get", "projectman"]]
    assert "claude mcp remove" not in out
    assert "Nothing to migrate" in out


def test_missing_claude_binary_reported_as_manual_step(home, project, no_claude):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"projectman": {"command": "projectman"}}}))
    out = _invoke()
    assert "manual step: claude CLI not found — run claude mcp remove --scope user projectman" in out
    # ~/.claude.json is not edited by hand
    assert "projectman" in json.loads((home / ".claude.json").read_text())["mcpServers"]


# --- US-PM-57-7: per-project pm-context.sh hook ---------------------------

PM_CONTEXT_SCRIPT = """#!/usr/bin/env bash
# SessionStart: if the working directory is a ProjectMan project (.project/),
# print a compact status summary so every session opens with context.
input=$(cat)
marker="$run/pm-context-$sid"
echo "## ProjectMan context ($proj)"
exit 0
"""

PM_CONTEXT_ENTRY = {
    "hooks": [
        {
            "type": "command",
            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/pm-context.sh',
            "timeout": 20,
        }
    ]
}


def _write_pm_context(project: Path, settings: dict, script: str = PM_CONTEXT_SCRIPT) -> None:
    hooks_dir = project / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "pm-context.sh").write_text(script)
    (project / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")


def test_pm_context_hook_and_settings_only_entry_removed(home, project, no_claude):
    _write_pm_context(project, {"hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}})
    out = _invoke()
    script = project / ".claude" / "hooks" / "pm-context.sh"
    settings = project / ".claude" / "settings.json"
    assert f"remove {script}" in out
    assert f"delete {settings} (it held only the pm-context.sh SessionStart hook)" in out
    assert not script.exists()
    assert not (project / ".claude" / "hooks").exists()
    assert not settings.exists()
    assert "Migrated: 2 change(s)" in out


def test_pm_context_removal_keeps_other_hooks_and_settings(home, project, no_claude):
    other_start = {"type": "command", "command": "echo hi"}
    settings_data = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "SessionStart": [
                PM_CONTEXT_ENTRY,
                {"matcher": "startup", "hooks": [other_start, PM_CONTEXT_ENTRY["hooks"][0]]},
            ],
            "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt"}]}],
        },
    }
    _write_pm_context(project, settings_data)
    (project / ".claude" / "hooks" / "other.sh").write_text("#!/bin/sh\n")

    out = _invoke()

    settings = project / ".claude" / "settings.json"
    assert f"remove the pm-context.sh SessionStart hook from {settings} (keeping other settings)" in out
    got = json.loads(settings.read_text())
    assert got == {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [other_start]}],
            "PostToolUse": settings_data["hooks"]["PostToolUse"],
        },
    }
    assert settings.read_text().endswith("\n")
    assert not (project / ".claude" / "hooks" / "pm-context.sh").exists()
    assert (project / ".claude" / "hooks" / "other.sh").exists()


def test_empty_session_start_and_hooks_tidied_but_other_keys_kept(home, project, no_claude):
    _write_pm_context(project, {"model": "opus", "hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}})
    _invoke()
    assert json.loads((project / ".claude" / "settings.json").read_text()) == {"model": "opus"}


def test_user_modified_pm_context_script_and_entry_kept(home, project, no_claude):
    _write_pm_context(project, {"hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}}, script="#!/bin/sh\necho mine\n")
    before = _snapshot(project)
    out = _invoke()
    assert _snapshot(project) == before
    assert f"keep {project / '.claude' / 'hooks' / 'pm-context.sh'} (not recognised" in out
    assert "Nothing to migrate" in out


def test_dangling_pm_context_entry_removed_without_script(home, project, no_claude):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}, "env": {"A": "1"}})
    )
    out = _invoke()
    assert "remove the pm-context.sh SessionStart hook" in out
    assert json.loads((project / ".claude" / "settings.json").read_text()) == {"env": {"A": "1"}}


def test_settings_without_pm_context_entry_untouched(home, project, no_claude):
    (project / ".claude").mkdir()
    data = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo x"}]}]}}
    (project / ".claude" / "settings.json").write_text(json.dumps(data))
    before = _snapshot(project)
    out = _invoke()
    assert _snapshot(project) == before
    assert "pm-context" not in out


def test_pm_context_dry_run_lists_and_writes_nothing(home, project, no_claude):
    _write_pm_context(project, {"model": "opus", "hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}})
    before = _snapshot(project)
    out = _invoke("--dry-run")
    assert _snapshot(project) == before
    settings = project / ".claude" / "settings.json"
    assert f"would remove {project / '.claude' / 'hooks' / 'pm-context.sh'}" in out
    assert f"would remove the pm-context.sh SessionStart hook from {settings}" in out
    assert "Dry run: 2 change(s) listed, nothing written." in out


def test_global_session_start_hook_untouched_with_note(home, project, no_claude):
    hook = home / ".claude" / "hooks" / "session-start.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text(PM_CONTEXT_SCRIPT)
    global_settings = home / ".claude" / "settings.json"
    global_settings.write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "~/.claude/hooks/session-start.sh"}]}]}}))
    before = _snapshot(home)

    for args in (("--dry-run",), ()):
        out = _invoke(*args)
        assert f"note: {hook} (ClaudeDefaultSetup's global SessionStart hook) duplicates" in out
        assert _snapshot(home) == before
    assert "Nothing to migrate" in out  # the note is not counted as a change


def test_invalid_settings_json_kept(home, project, no_claude):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text("{not json")
    out = _invoke()
    assert "not valid JSON — remove the pm-context.sh SessionStart hook by hand" in out
    assert (project / ".claude" / "settings.json").read_text() == "{not json"


def test_real_run_removes_mcp_entries_and_pm_context_hook_listing_each_change(
    home, project, monkeypatch, fake_claude
):
    """US-PM-57-2: on a setup-claude-style install with a user-scope MCP
    entry, a ./.mcp.json projectman entry and a per-project pm-context.sh +
    SessionStart entry, a real run removes all of them and prints one line
    per change — the change lines match the summary count."""
    _install(home, project, monkeypatch)
    monkeypatch.setattr(  # _install hid the binary; restore the stub
        "projectman.cli.shutil.which",
        lambda name: "/fake/bin/claude" if name == "claude" else None,
    )
    mcp = project / ".mcp.json"
    assert "projectman" in json.loads(mcp.read_text())["mcpServers"]
    _write_pm_context(project, {"hooks": {"SessionStart": [PM_CONTEXT_ENTRY]}})
    script = project / ".claude" / "hooks" / "pm-context.sh"
    settings = project / ".claude" / "settings.json"

    out = _invoke()

    # user-scope MCP server removed through the claude CLI
    assert ["claude", "mcp", "remove", "--scope", "user", "projectman"] in fake_claude["ran"]
    assert "run claude mcp remove --scope user projectman" in out.splitlines()
    # projectman gone from .mcp.json (setup-claude wrote it alone, so it is deleted)
    assert not mcp.exists()
    assert f"delete {mcp} (it held only the projectman server)" in out.splitlines()
    # hook script and its SessionStart entry gone
    assert not script.exists()
    assert not settings.exists()
    assert f"remove {script}" in out.splitlines()
    assert f"delete {settings} (it held only the pm-context.sh SessionStart hook)" in out.splitlines()
    # every change has a printed line, and the count matches the summary
    change_lines = [l for l in out.splitlines() if l.startswith(("remove ", "delete ", "run "))]
    assert len(change_lines) == len(set(change_lines))
    assert f"Migrated: {len(change_lines)} change(s)" in out
    for root in (home / ".claude", project / ".claude"):
        assert f"remove {root / 'agents' / 'pm.md'}" in change_lines
    assert not any(l.startswith(("would ", "keep ", "manual step")) for l in out.splitlines())
