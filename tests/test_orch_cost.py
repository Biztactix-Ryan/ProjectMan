"""Context-cost analysis of a session transcript (US-PM-52-5).

The input is a synthetic transcript written into ``tmp_path``.  A real
``~/.claude`` transcript is somebody's session — huge, private and different
every day — so the fixture *is* the spec here: each test writes the handful
of records that make its case and asserts on the arithmetic they imply.
The ``baseline_transcript`` fixture at the foot of the file is the one
exception: it carries every record shape at once and is the reference
transcript to extend when the report grows a section.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from projectman.orch_cost import analyze, find_transcripts

BASE = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)
RUN = "orch-2026-09-09-385a"


def _at(minute):
    return (BASE + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def _usage(*, inputs=10, creation=0, read=0, output=100, ttl=None):
    """A usage block; ``ttl`` ("5m" or "1h") adds the harness's per-TTL
    ``cache_creation`` breakdown for the ``creation`` tokens."""
    usage = {
        "input_tokens": inputs,
        "cache_creation_input_tokens": creation,
        "cache_read_input_tokens": read,
        "output_tokens": output,
    }
    if ttl is not None:
        usage["cache_creation"] = {
            "ephemeral_5m_input_tokens": creation if ttl == "5m" else 0,
            "ephemeral_1h_input_tokens": creation if ttl == "1h" else 0,
        }
    return usage


def _heartbeat(minute, run=RUN):
    """The skill's keep-alive cron prompt, as the transcript records it firing."""
    return _user(
        minute,
        blocks=[
            _text(
                f"Heartbeat {run}: worker out → reply in five words, no tools; "
                "no run in flight → CronDelete this job"
            )
        ],
    )


def _assistant(minute, *, usage=None, blocks=(), message_id=None):
    """One assistant record in Claude Code's transcript shape."""
    return {
        "type": "assistant",
        "timestamp": _at(minute),
        "message": {
            "id": message_id or f"msg_{minute}",
            "role": "assistant",
            "content": list(blocks),
            "usage": usage if usage is not None else _usage(),
        },
    }


def _user(minute, *, blocks=()):
    return {
        "type": "user",
        "timestamp": _at(minute),
        "message": {"role": "user", "content": list(blocks)},
    }


def _tool_use(block_id, name, **input_):
    return {"type": "tool_use", "id": block_id, "name": name, "input": input_}


def _tool_result(use_id, content):
    return {"type": "tool_result", "tool_use_id": use_id, "content": content}


def _text(text):
    return {"type": "text", "text": text}


def _write(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    return path


def _transcript(tmp_path, records, name="session.jsonl"):
    return _write(tmp_path / name, records)


def test_context_arithmetic_and_growth(tmp_path):
    """Context is input + cache read + cache creation; growth is peak - base."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(inputs=100, creation=900, read=0)),
            _assistant(1, usage=_usage(inputs=10, creation=0, read=2000)),
            _assistant(2, usage=_usage(inputs=10, creation=0, read=1500)),
        ],
    )
    report = analyze(path, RUN)

    assert report["base"] == 1000
    assert report["peak"] == 2010
    assert report["growth"] == 1010
    assert report["calls"] == 3
    assert report["output_per_call"] == 100.0


def test_records_sharing_a_message_id_are_counted_once(tmp_path):
    """The harness writes one record per block; usage is one call, not three."""
    usage = _usage(inputs=10, creation=0, read=990, output=60)
    dispatch = _tool_use("t1", "Agent", prompt="do the thing")
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(inputs=500, creation=0, read=0)),
            _assistant(1, message_id="msg_dup", usage=usage, blocks=[_text("ok")]),
            _assistant(1, message_id="msg_dup", usage=usage, blocks=[dispatch]),
            _assistant(1, message_id="msg_dup", usage=usage, blocks=[dispatch]),
        ],
    )
    report = analyze(path, RUN)

    assert report["calls"] == 2
    assert report["dispatches"] == 1
    assert report["output_per_call"] == 80.0


def test_dispatches_accepts_and_ratios(tmp_path):
    """Agent launches are dispatches; pm_accept / pm_done_next are accepts."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(inputs=1000, creation=0, read=0)),
            _assistant(1, blocks=[_tool_use("t1", "Agent")]),
            _assistant(2, blocks=[_tool_use("t2", "mcp__projectman__pm_accept")]),
            _assistant(3, blocks=[_tool_use("t3", "Agent")]),
            _assistant(
                4,
                usage=_usage(inputs=10, creation=0, read=2990),
                blocks=[_tool_use("t4", "mcp__projectman__pm_done_next")],
            ),
        ],
    )
    report = analyze(path, RUN)

    assert report["dispatches"] == 2
    assert report["accepts"] == 2
    assert report["growth"] == 2000
    assert report["per_dispatch"] == 1000.0
    assert report["per_task"] == 1000.0
    assert report["calls_per_dispatch"] == 2.5


def test_per_task_is_none_without_accepts(tmp_path):
    path = _transcript(tmp_path, [_assistant(0), _assistant(1)])
    report = analyze(path, RUN)

    assert report["per_task"] is None
    assert report["per_dispatch"] is None


def test_tool_bytes_by_tool_name(tmp_path):
    """Result bytes are filed under the name of the matching tool_use id."""
    path = _transcript(
        tmp_path,
        [
            _assistant(
                0,
                blocks=[
                    _tool_use("t1", "Read", file_path="/a"),
                    _tool_use("t2", "Bash", command="ls"),
                    _tool_use("t3", "Read", file_path="/b"),
                ],
            ),
            _user(1, blocks=[_tool_result("t1", "abcde")]),
            _user(2, blocks=[_tool_result("t2", [_text("xy"), _text("z")])]),
            _user(3, blocks=[_tool_result("t3", "fg")]),
        ],
    )
    report = analyze(path, RUN)

    assert report["tool_bytes"] == {"Read": 7, "Bash": 3}


def test_waits_pair_launches_with_task_notifications(tmp_path):
    """Each Agent launch waits for the next task notification, in order."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, blocks=[_tool_use("t1", "Agent")]),
            _assistant(1, blocks=[_tool_use("t2", "Agent")]),
            _user(11, blocks=[_text("<task-notification>done</task-notification>")]),
            _assistant(12, blocks=[_tool_use("t3", "Agent")]),
            _user(41, blocks=[_text("<task-notification>done</task-notification>")]),
            _user(90, blocks=[_text("<task-notification>done</task-notification>")]),
        ],
    )
    report = analyze(path, RUN)

    assert report["waits"]["n"] == 3
    assert report["waits"]["p50"] == 40.0
    assert report["waits"]["p90"] == 78.0
    assert report["waits"]["max"] == 78.0


def test_full_cache_miss_records_the_gap_before_it(tmp_path):
    """Fresh tokens over half the context are a miss; the gap is the idle time."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(inputs=10, creation=990, read=0)),
            _assistant(5, usage=_usage(inputs=10, creation=0, read=1500)),
            _assistant(70, usage=_usage(inputs=20, creation=1800, read=100)),
        ],
    )
    report = analyze(path, RUN)

    assert len(report["misses"]) == 2
    first, second = report["misses"]
    assert first["gap_min"] is None
    assert first["tokens"] == 1000
    assert second["at"] == "2026-09-09T11:10:00+00:00"
    assert second["gap_min"] == 65.0
    assert second["tokens"] == 1820


def test_ttl_mix_counts_calls_by_the_cache_they_wrote_to(tmp_path):
    """One call per TTL it wrote under; a call that wrote nothing counts in neither."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(creation=500, ttl="1h")),
            _assistant(1, usage=_usage(creation=500, ttl="1h")),
            _assistant(2, usage=_usage(creation=500, ttl="5m")),
            _assistant(3, usage=_usage(creation=0, read=1500, ttl="1h")),
            _assistant(4, usage=_usage(creation=500)),  # no breakdown at all
        ],
    )
    assert analyze(path)["ttl"] == {"5m": 1, "1h": 2}


def test_heartbeats_are_the_keep_alive_prompt_firing(tmp_path):
    """Counted by the prompt's opening, so a person mentioning a heartbeat is not one."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0),
            _heartbeat(30),
            _assistant(31),
            _user(40, blocks=[_text("was that a Heartbeat orch- firing?")]),
            _heartbeat(60),
            _assistant(61),
        ],
    )
    assert analyze(path)["heartbeats"] == 2


def test_malformed_lines_and_usage_free_records_are_skipped(tmp_path):
    """A transcript is history: bad lines are stepped over, never raised on."""
    path = tmp_path / "session.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_assistant(0, usage=_usage(inputs=1000))) + "\n")
        fh.write("{not json at all\n")
        fh.write("\n")
        fh.write("[1, 2, 3]\n")
        fh.write(json.dumps({"type": "assistant", "message": {"id": "x"}}) + "\n")
        fh.write(json.dumps({"type": "summary", "summary": "nope"}) + "\n")
        fh.write(
            json.dumps(_assistant(1, usage=_usage(inputs=10, read=2990))) + "\n"
        )
    report = analyze(path, RUN)

    assert report["calls"] == 2
    assert report["base"] == 1000
    assert report["growth"] == 2000


def test_analysis_starts_at_the_first_record_naming_the_run(tmp_path):
    """A session can hold several runs; base is this run's opening context."""
    path = _transcript(
        tmp_path,
        [
            _assistant(0, usage=_usage(inputs=50_000, creation=0, read=0)),
            _user(1, blocks=[_text(f"start run {RUN}")]),
            _assistant(2, usage=_usage(inputs=100, creation=900, read=0)),
            _assistant(3, usage=_usage(inputs=10, creation=0, read=1490)),
        ],
    )
    report = analyze(path, RUN)

    assert report["base"] == 1000
    assert report["peak"] == 1500
    assert report["calls"] == 2


def test_find_transcripts_locates_the_file_by_run_id(tmp_path):
    """The file that mentions the run id is the file that recorded the run."""
    project = tmp_path / "-mnt-repos-ProjectMan"
    other = tmp_path / "-mnt-repos-Other"
    project.mkdir()
    other.mkdir()
    hit = _transcript(
        project,
        [_user(0, blocks=[_text(f"run {RUN}")])],
        name="hit.jsonl",
    )
    _transcript(other, [_user(0, blocks=[_text("run orch-other")])], name="miss.jsonl")
    (project / "notes.txt").write_text(RUN, encoding="utf-8")

    found = find_transcripts(RUN, root=tmp_path)

    assert found == [hit]
    assert find_transcripts("orch-nobody", root=tmp_path) == []
    assert find_transcripts("", root=tmp_path) == []


def test_find_transcripts_sorts_newest_first(tmp_path):
    import os

    first = _transcript(tmp_path, [_user(0, blocks=[_text(RUN)])], name="a.jsonl")
    second = _transcript(tmp_path, [_user(0, blocks=[_text(RUN)])], name="b.jsonl")
    os.utime(first, (1_600_000_000, 1_600_000_000))
    os.utime(second, (1_700_000_000, 1_700_000_000))

    assert find_transcripts(RUN, root=tmp_path) == [second, first]


# --------------------------------------------------------------------------
# The reference transcript (US-PM-52-7)
# --------------------------------------------------------------------------
#
# Every test above writes the two or three records its own claim needs.  This
# last section writes *one* transcript that carries all of them at once — the
# shape a real orchestrator session has — and reads the whole report off a
# single ``analyze()`` call, then off the CLI.  It is the fixture to extend
# when the report grows a section: if a change survives here it survives an
# end-to-end run, and the numbers below are the arithmetic of the records,
# worked by hand.
#
#   min  0   call 1   base 20,000, names the run
#   min  1   call 2   three records, one message id, one Agent launch (t1)
#   min  2   call 3   Agent launch (t2), context 22,000
#   min  3   call 4   pm_grab + pm_get launched, context 24,000
#   min  4            their results: 512 and 256 bytes
#   min  5            the heartbeat cron fires (idle, both workers out)
#   min  6   call 5   its few-word reply, a five-minute-TTL write, context 25,000
#   min  9            <task-notification> answers t1     -> 8 min wait
#   min 10   call 6   context 26,000 (the peak before the miss)
#   min 72            <task-notification> answers t2     -> 70 min wait
#   min 73   call 7   full cache miss after a 63 min gap; pm_accept (t5)
#   min 74            pm_accept's result: 128 bytes
#
# Calls 2 and 7 write one-hour entries, call 5 a five-minute one, so the TTL
# mix is {5m: 1, 1h: 2}; the heartbeat at minute 5 is the one firing.

BASELINE_CALLS = 7
BASELINE_BASE = 20_000
BASELINE_PEAK = 30_000
BASELINE_GROWTH = BASELINE_PEAK - BASELINE_BASE


@pytest.fixture
def baseline_transcript(tmp_path):
    """One transcript exercising every part of the report at once."""
    dispatch = _tool_use("t1", "Agent", prompt="US-PM-52-7")
    notification = _text("<task-notification>worker finished</task-notification>")
    return _transcript(
        tmp_path,
        [
            _assistant(
                0,
                message_id="msg_start",
                usage=_usage(inputs=10, creation=0, read=19_990),
                blocks=[_text(f"starting run {RUN}")],
            ),
            # One API call, three records: the harness splits a message into
            # one record per content block, all carrying the same usage.
            _assistant(
                1,
                message_id="msg_dispatch",
                usage=_usage(inputs=10, creation=490, read=19_500, ttl="1h"),
                blocks=[_text("dispatching")],
            ),
            _assistant(
                1,
                message_id="msg_dispatch",
                usage=_usage(inputs=10, creation=490, read=19_500, ttl="1h"),
                blocks=[dispatch],
            ),
            _assistant(
                1,
                message_id="msg_dispatch",
                usage=_usage(inputs=10, creation=490, read=19_500, ttl="1h"),
                blocks=[dispatch],
            ),
            _assistant(
                2,
                message_id="msg_dispatch_2",
                usage=_usage(inputs=10, creation=0, read=21_990),
                blocks=[_tool_use("t2", "Agent", prompt="US-PM-52-8")],
            ),
            _assistant(
                3,
                message_id="msg_pm",
                usage=_usage(inputs=10, creation=0, read=23_990),
                blocks=[
                    _tool_use("t3", "mcp__projectman__pm_grab", id="US-PM-52-7"),
                    _tool_use("t4", "mcp__projectman__pm_get", id="US-PM-52"),
                ],
            ),
            _user(
                4,
                blocks=[_tool_result("t3", "g" * 512), _tool_result("t4", "e" * 256)],
            ),
            _heartbeat(5),
            _assistant(
                6,
                message_id="msg_beat",
                usage=_usage(inputs=10, creation=990, read=24_000, ttl="5m"),
                blocks=[_text("Still here, workers out.")],
            ),
            _user(9, blocks=[notification]),
            _assistant(
                10,
                message_id="msg_between",
                usage=_usage(inputs=10, creation=0, read=25_990),
                blocks=[_text("waiting on the second worker")],
            ),
            _user(72, blocks=[notification]),
            # The cache TTL expired during that 70-minute wait: the whole
            # prompt came back as fresh tokens.
            _assistant(
                73,
                message_id="msg_miss",
                usage=_usage(inputs=100, creation=24_900, read=5_000, ttl="1h"),
                blocks=[
                    _tool_use("t5", "mcp__projectman__pm_accept", id="US-PM-52-7"),
                ],
            ),
            _user(74, blocks=[_tool_result("t5", "a" * 128)]),
        ],
    )


def test_the_reference_transcript_reports_every_number(baseline_transcript):
    """One analyze() call over the whole fixture, checked end to end."""
    report = analyze(baseline_transcript, RUN)

    # Dedupe: nine assistant records, seven distinct message ids.
    assert report["calls"] == BASELINE_CALLS
    assert report["dispatches"] == 2
    assert report["accepts"] == 1

    assert report["base"] == BASELINE_BASE
    assert report["peak"] == BASELINE_PEAK
    assert report["growth"] == BASELINE_GROWTH
    assert report["per_dispatch"] == 5000.0
    assert report["per_task"] == 10000.0
    assert report["calls_per_dispatch"] == 3.5
    assert report["output_per_call"] == 100.0

    assert report["ttl"] == {"5m": 1, "1h": 2}
    assert report["heartbeats"] == 1

    assert report["waits"] == {"p50": 8.0, "p90": 70.0, "max": 70.0, "n": 2}

    assert report["misses"] == [
        {
            "at": _at(73).replace("Z", "+00:00"),
            "gap_min": 63.0,
            "tokens": 25_000,
        }
    ]

    assert report["tool_bytes"] == {
        "mcp__projectman__pm_grab": 512,
        "mcp__projectman__pm_get": 256,
        "mcp__projectman__pm_accept": 128,
    }


def test_the_cli_prints_and_serialises_the_reference_report(baseline_transcript):
    """``orch-cost <run> --transcripts <dir>`` over the same fixture."""
    from click.testing import CliRunner

    from projectman.cli import cli

    runner = CliRunner()
    root = str(baseline_transcript.parent)

    text = runner.invoke(cli, ["orch-cost", RUN, "--transcripts", root])
    assert text.exit_code == 0, text.output
    for headline in (
        "20,000", "30,000", "10,000", "5,000.0", "10,000.0", "63.0",
        "5m 1  1h 2  heartbeats 1",
    ):
        assert headline in text.output, f"{headline!r} missing:\n{text.output}"

    payload = runner.invoke(
        cli, ["orch-cost", RUN, "--transcripts", root, "--json"]
    )
    assert payload.exit_code == 0, payload.output
    assert json.loads(payload.output) == {
        "path": str(baseline_transcript),
        **analyze(baseline_transcript, RUN),
    }
