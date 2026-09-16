"""Smoke tests for ``projectman orch-cost`` (US-PM-52-6).

The arithmetic is pinned in ``test_orch_cost.py``; what is pinned here is the
command wiring — that the run id finds a transcript under ``--transcripts``,
that every section the report promises is printed, that ``--json`` emits the
analysis dict, and that an unknown run id fails loudly instead of printing an
empty report.  The record builders are imported rather than re-written so the
fixture shape stays one definition.
"""

import json

import pytest
from click.testing import CliRunner

from projectman.cli import cli
from test_orch_cost import (  # noqa: F401 — synthetic-transcript builders
    RUN,
    _assistant,
    _text,
    _tool_result,
    _tool_use,
    _transcript,
    _usage,
    _user,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def transcripts(tmp_path):
    """A tiny run: one dispatch, one accept, one wait, one full cache miss."""
    root = tmp_path / "projects"
    root.mkdir()
    _transcript(
        root,
        [
            _assistant(
                0,
                usage=_usage(inputs=10, creation=990, read=0),
                blocks=[
                    _text(f"starting run {RUN}"),
                    _tool_use("t1", "Agent", prompt="do the thing"),
                ],
            ),
            _user(70, blocks=[_text("<task-notification> worker finished")]),
            _assistant(
                71,
                usage=_usage(inputs=20, creation=1800, read=100),
                blocks=[
                    _tool_result("t1", "the worker's report"),
                    _tool_use("t2", "mcp__projectman__pm_accept", id="US-PM-1-1"),
                ],
            ),
        ],
        name="session.jsonl",
    )
    return root


def test_text_report_prints_every_section(runner, transcripts):
    result = runner.invoke(cli, ["orch-cost", RUN, "--transcripts", str(transcripts)])

    assert result.exit_code == 0, result.output
    for label in (
        "dispatches",
        "accepts",
        "calls",
        "base",
        "peak",
        "growth per dispatch",
        "growth per accepted task",
        "calls per dispatch",
        "output tokens per call",
        "tool result bytes",
        "worker waits (minutes)",
        "cache ttl (calls writing)",
        "heartbeats",
        "full cache misses",
    ):
        assert label in result.output, f"{label!r} missing from:\n{result.output}"
    assert "session.jsonl" in result.output
    assert "Agent" in result.output


def test_json_report_is_the_analysis_dict(runner, transcripts):
    result = runner.invoke(
        cli, ["orch-cost", RUN, "--transcripts", str(transcripts), "--json"]
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["path"].endswith("session.jsonl")
    assert report["dispatches"] == 1
    assert report["accepts"] == 1
    assert report["waits"]["n"] == 1
    assert report["tool_bytes"]["Agent"] > 0
    assert len(report["misses"]) == 2


def test_unknown_run_id_exits_non_zero(runner, transcripts):
    result = runner.invoke(
        cli, ["orch-cost", "orch-nobody", "--transcripts", str(transcripts)]
    )

    assert result.exit_code != 0
    assert "orch-nobody" in result.output
