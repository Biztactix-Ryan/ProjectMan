"""Tests for `projectman session-context` and the plugin's SessionStart hook (US-PM-56-9).

The command prints the same status block as ClaudeDefaultSetup's
session-start.sh and shares its per-session dedupe marker, so the two never
both print into one session.
"""

import json
import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    run = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("USER", "tester")
    return run


def _marker(runtime_dir, sid):
    return runtime_dir / "claude-notify-tester" / f"pm-context-{sid}"


def _run(cwd, sid="s1"):
    payload = json.dumps({"cwd": str(cwd), "session_id": sid})
    return CliRunner().invoke(cli, ["session-context"], input=payload)


@pytest.fixture
def populated(store, tmp_project):
    store.create_epic("Big epic", "Epic body")
    story, _ = store.create_story("A story", "Story body", points=3)
    task = store.create_task(story.id, "Doing it", "Task body")
    store.create_task(story.id, "Later", "Task body")
    store.update(task.id, status="in-progress")
    store.write_next("We decided to fix X by doing Y and Z.")
    return tmp_project


def test_prints_status_block_for_a_store(populated, runtime_dir):
    result = _run(populated)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == f"## ProjectMan context ({populated / '.project'})"
    assert lines[1] == "Project **test-project** (TST)"
    assert "- epics: 1 (" in result.output
    assert "- stories: 1 (" in result.output
    assert "- tasks: 2 (" in result.output
    assert "- points: " in result.output
    assert any(l.startswith("- in progress: US-TST-1-1 Doing it") for l in lines)
    assert "We decided to fix X by doing Y and Z." in result.output
    assert lines[-1].startswith("Use pm_context for full context")


def test_active_sprint_line(store, tmp_project, runtime_dir):
    sprint = store.create_sprint("Sprint one")
    store.update_sprint(sprint.id, status="active")
    result = _run(tmp_project)
    assert f"- active sprint: {sprint.id} Sprint one" in result.output


def test_silent_outside_a_store(tmp_path, runtime_dir):
    result = _run(tmp_path)
    assert result.exit_code == 0
    assert result.output == ""
    assert not _marker(runtime_dir, "s1").exists()


def test_silent_on_garbage_stdin(tmp_path, runtime_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["session-context"], input="not json")
    assert result.exit_code == 0
    assert result.output == ""


def test_touches_the_shared_marker(tmp_project, runtime_dir):
    result = _run(tmp_project, sid="abc")
    assert result.exit_code == 0
    assert result.output
    assert _marker(runtime_dir, "abc").is_file()


def test_fresh_marker_suppresses_output(tmp_project, runtime_dir):
    marker = _marker(runtime_dir, "abc")
    marker.parent.mkdir(parents=True)
    marker.touch()
    result = _run(tmp_project, sid="abc")
    assert result.exit_code == 0
    assert result.output == ""


def test_stale_marker_prints_and_is_retouched(tmp_project, runtime_dir):
    marker = _marker(runtime_dir, "abc")
    marker.parent.mkdir(parents=True)
    marker.touch()
    old = time.time() - 60
    os.utime(marker, (old, old))
    result = _run(tmp_project, sid="abc")
    assert result.output.startswith("## ProjectMan context")
    assert marker.stat().st_mtime > old + 30


def test_second_call_in_same_session_is_silent(tmp_project, runtime_dir):
    assert _run(tmp_project, sid="dup").output
    assert _run(tmp_project, sid="dup").output == ""
    assert _run(tmp_project, sid="other").output


def test_hooks_json_has_session_start_command():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [h for group in hooks["SessionStart"] for h in group["hooks"]]
    commands = [h["command"] for h in entries if h["type"] == "command"]
    assert len(commands) == 1
    command = commands[0]
    assert '--project "${CLAUDE_PLUGIN_ROOT}"' in command
    assert command.rstrip().endswith("projectman session-context")
    assert "command -v uv" in command
