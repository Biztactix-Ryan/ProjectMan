"""The SessionStart status block where the sprint band draws (US-PM-62-8).

The plugin's mod sets ``PROJECTMAN_BAND_SESSION`` to the session's id in its
``classic.SessionStart`` hook, before the chain reaches the plugin's command
hook, whenever a surface draws the band (tests/mod/band-session.test.ts pins
that side).  ``projectman session-context`` reduces the block only when that
value is this payload's own ``session_id``; anything else prints today's full
block byte for byte.

Every test runs in tmp_path: the store is the ``tmp_project`` fixture (its
root asserted first), the dedupe markers live under a tmp XDG_RUNTIME_DIR and
the band variable is set with monkeypatch only.
"""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from projectman.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "telemetry" / "session-context-size.md"
ENV = "PROJECTMAN_BAND_SESSION"

#: Same estimate the usage telemetry uses (tools/usage_telemetry/report.py).
CHARS_PER_TOKEN = 4

#: tmp_path stands in for this root in the measured text, so the measurement
#: does not move with the length of pytest's temporary directory.
MEASURED_ROOT = "/home/user/project"

NOTE = (
    "We decided to fix the SessionStart double-print by keying the dedupe marker "
    "on the session id and letting whichever hook runs first print; next, wire the "
    "band refresh into pm_update and re-measure the orchestrator's context per task."
)

FULL_ONLY = ("- epics:", "- stories:", "- tasks:", "- points:", "- in progress:", "- active sprint:")


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    run = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv(ENV, raising=False)
    return run


@pytest.fixture
def representative(store, tmp_project, runtime_dir):
    """A store shaped like a live one: a sprint running, six tasks in flight,
    an open decision, a long next-session note and a handoff."""
    assert store.project_dir == tmp_project / ".project"
    assert str(tmp_project).startswith(str(runtime_dir.parent))
    store.create_epic("Plugin packaging", "Epic body")
    store.create_epic("Orchestrator context", "Epic body")
    stories = [store.create_story(f"Story {n}", "Story body", points=p)[0] for n, p in ((1, 3), (2, 5), (3, 8))]
    tasks = []
    for story in stories:
        for n in range(3):
            tasks.append(store.create_task(story.id, f"Do part {n} of {story.title}", "Task body", points=2))
    for task in tasks[:6]:
        store.update(task.id, status="in-progress")
    store.update(tasks[6].id, status="done")
    sprint = store.create_sprint("Sprint 20 — The Project Asks, You Answer")
    store.update_sprint(sprint.id, status="active")
    store.create_decision("Drop or shorten the status block?", blocks=[stories[2].id])
    store.write_next(NOTE)
    (store.project_dir / "HANDOFF.md").write_text("# Handoff\n\nResume at US-PM-62-8.\n")
    return tmp_project


def _run(cwd, sid="s1", payload=None):
    if payload is None:
        payload = {"cwd": str(cwd), "session_id": sid}
    return CliRunner().invoke(cli, ["session-context"], input=json.dumps(payload))


def _fresh(runtime_dir):
    """Clear the dedupe markers so the next run prints again."""
    for marker in (runtime_dir / "claude-notify-tester").glob("pm-context-*"):
        marker.unlink()


def _full(project, runtime_dir, sid="s1"):
    """Today's block: no band variable at all."""
    _fresh(runtime_dir)
    result = _run(project, sid=sid)
    assert result.exit_code == 0, result.output
    _fresh(runtime_dir)
    return result.output


# --- US-PM-62-4: where the band draws the status is reduced ------------------


def test_us_pm_62_4_band_in_this_session_reduces_the_block(representative, runtime_dir, monkeypatch):
    """US-PM-62-4 criterion: where the band draws, the injected status is reduced."""
    full = _full(representative, runtime_dir)
    monkeypatch.setenv(ENV, "s1")
    result = _run(representative, sid="s1")
    assert result.exit_code == 0, result.output
    reduced = result.output
    lines = reduced.splitlines()

    assert len(reduced) < len(full)
    assert lines[0] == f"## ProjectMan context ({representative / '.project'})"
    assert lines[1] == "Project **test-project** (TST)"
    # What the band shows the person (and pm_context gives the model) is gone.
    for prefix in FULL_ONLY:
        assert not any(l.startswith(prefix) for l in lines), prefix
    # What steers the model's first move stays: decisions, the note, the handoff.
    assert any(l.startswith("- decisions: 1 open") for l in lines)
    assert any(l.startswith("- next-session note (pm_next, ") for l in lines)
    assert any(l.startswith("- last handoff: ") for l in lines)
    assert lines[-1].startswith("Counts, the active sprint and in-flight tasks are on the person's sprint band")
    assert "pm_context" in lines[-1]
    # Each kept line is word for word the full block's.
    full_lines = full.splitlines()
    for line in lines[:-1]:
        assert line in full_lines, line


def test_us_pm_62_4_reduced_block_keeps_the_note_text(representative, runtime_dir, monkeypatch):
    """The band is the person's; the model still needs the NEXT.md note."""
    monkeypatch.setenv(ENV, "s1")
    out = _run(representative, sid="s1").output
    assert "We decided to fix the SessionStart double-print" in out


def test_us_pm_62_4_reduced_block_still_dedupes(representative, runtime_dir, monkeypatch):
    monkeypatch.setenv(ENV, "dup")
    assert _run(representative, sid="dup").output
    assert _run(representative, sid="dup").output == ""


def test_us_pm_62_4_reduced_block_on_a_bare_store(tmp_project, store, runtime_dir, monkeypatch):
    """No note, decision or handoff: header, project line and the pointer."""
    assert store.project_dir == tmp_project / ".project"
    monkeypatch.setenv(ENV, "s1")
    lines = _run(tmp_project, sid="s1").output.splitlines()
    assert lines[0].startswith("## ProjectMan context (")
    assert lines[1] == "Project **test-project** (TST)"
    assert len(lines) == 3
    assert lines[2].startswith("Counts, the active sprint and in-flight tasks")


# --- US-PM-62-5: where nothing draws the injection is today's ----------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="unset (claude -p, SDK, vscode or mobile only, mod disabled)"),
        pytest.param("", id="empty"),
        pytest.param("other-session", id="another session (nested claude -p, before /clear)"),
        pytest.param(" s1", id="malformed: leading space"),
        pytest.param("s1\n", id="malformed: trailing newline"),
        pytest.param("S1", id="malformed: case"),
        pytest.param("s1,s2", id="malformed: a list"),
    ],
)
def test_us_pm_62_5_no_band_evidence_prints_todays_block(representative, runtime_dir, monkeypatch, value):
    """US-PM-62-5 criterion: where nothing draws, the injection keeps working as today."""
    full = _full(representative, runtime_dir)
    if value is not None:
        monkeypatch.setenv(ENV, value)
    result = _run(representative, sid="s1")
    assert result.exit_code == 0, result.output
    assert result.output == full
    for prefix in FULL_ONLY:
        assert prefix in full


@pytest.mark.parametrize(
    "payload_sid",
    [
        pytest.param(None, id="payload without session_id"),
        pytest.param("", id="empty session_id"),
        pytest.param(17, id="non-string session_id"),
    ],
)
def test_us_pm_62_5_payload_without_a_usable_id_prints_todays_block(
    representative, runtime_dir, monkeypatch, payload_sid
):
    payload = {"cwd": str(representative)}
    if payload_sid is not None:
        payload["session_id"] = payload_sid
    _fresh(runtime_dir)
    expected = _run(representative, payload=payload).output
    _fresh(runtime_dir)
    # Even a variable equal to the dedupe fallback or the raw value reduces nothing.
    monkeypatch.setenv(ENV, "nosession" if payload_sid in (None, "") else str(payload_sid))
    result = _run(representative, payload=payload)
    assert result.exit_code == 0, result.output
    assert result.output == expected
    assert "- tasks: " in result.output


def test_us_pm_62_5_stale_value_after_clear_prints_todays_block(representative, runtime_dir, monkeypatch):
    """A /clear moves to a new id: the old session's value is stale evidence."""
    full_new = _full(representative, runtime_dir, sid="after-clear")
    monkeypatch.setenv(ENV, "before-clear")
    assert _run(representative, sid="after-clear").output == full_new


def test_us_pm_62_5_silent_outside_a_store_even_with_the_band(tmp_path, runtime_dir, monkeypatch):
    monkeypatch.setenv(ENV, "s1")
    result = _run(tmp_path, sid="s1")
    assert result.exit_code == 0
    assert result.output == ""


def test_us_pm_62_5_the_mod_sets_the_variable_the_cli_reads():
    """The two sides name the same variable."""
    register = (REPO_ROOT / "hooks" / "register.ts").read_text()
    assert f"$.env.set('{ENV}'" in register
    from projectman import cli as cli_module

    assert cli_module._BAND_SESSION_ENV == ENV


# --- the context saved, recorded ----------------------------------------------


def _measure(text: str, root: Path) -> dict:
    normalised = text.replace(str(root), MEASURED_ROOT)
    size = len(normalised.encode("utf-8"))
    chars = len(normalised)
    return {"bytes": size, "chars": chars, "est_tokens": chars // CHARS_PER_TOKEN, "lines": len(normalised.splitlines())}


def measurement(full: str, reduced: str, root: Path) -> dict:
    f = _measure(full, root)
    r = _measure(reduced, root)
    saved_bytes = f["bytes"] - r["bytes"]
    return {
        "schema": "projectman.session-context-size/1",
        "fixture": "tests/test_session_context_band.py::representative",
        "estimate": f"chars // {CHARS_PER_TOKEN}",
        "full": f,
        "reduced": r,
        "saved": {
            "bytes": saved_bytes,
            "est_tokens": f["est_tokens"] - r["est_tokens"],
            "pct": round(saved_bytes * 100 / f["bytes"], 1),
        },
    }


def test_us_pm_62_4_context_saved_is_recorded(representative, runtime_dir, monkeypatch):
    """US-PM-62-4 criterion: the saving is measured and recorded in the telemetry doc."""
    full = _full(representative, runtime_dir)
    monkeypatch.setenv(ENV, "s1")
    reduced = _run(representative, sid="s1").output
    measured = measurement(full, reduced, representative)
    assert measured["saved"]["bytes"] > 0

    match = re.search(
        r"<!-- session-context-size:measurement -->\s*```json\n(.*?)\n```", DOC.read_text(), re.S
    )
    assert match, f"{DOC} has no measurement block"
    recorded = json.loads(match.group(1))
    assert recorded == measured, (
        "the block moved; paste this into docs/telemetry/session-context-size.md:\n"
        + json.dumps(measured, indent=2, sort_keys=True)
    )
