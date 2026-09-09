"""Acceptance criteria for the ``projectman orch-cost`` report (US-PM-52).

These tests assert the criteria *verbatim at the CLI level*: a synthetic
transcript goes into ``tmp_path``, ``projectman orch-cost <run-id>
--transcripts <dir>`` is invoked through click's ``CliRunner``, and both the
text report and ``--json`` are checked against numbers computed by hand from
the fixture.  ``test_orch_cost.py`` pins the same arithmetic one layer down
at ``analyze()``; the point here is that the *printed report* carries it.

The record builders are imported from ``test_orch_cost`` rather than
re-written, so a transcript's shape stays one definition.  Shared helpers for
the whole criteria file live at the top — US-PM-52-1 and US-PM-52-3 add their
criteria below and reuse them.
"""

import json
import os
import re

import pytest
from click.testing import CliRunner

from projectman.cli import cli
from test_orch_cost import (  # noqa: F401 — synthetic-transcript builders
    BASE,
    RUN,
    _assistant,
    _at,
    _text,
    _tool_result,
    _tool_use,
    _transcript,
    _usage,
    _user,
)

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

#: What the harness wraps a finished worker's hand-back in.  The analyser
#: matches on the opening marker; a realistic record carries both.
NOTIFICATION = "<task-notification>worker finished</task-notification>"


@pytest.fixture
def runner():
    return CliRunner()


def _root(tmp_path, name):
    """An isolated ``--transcripts`` directory, so one run finds one file."""
    root = tmp_path / name
    root.mkdir()
    return root


def _run(runner, root, *args, run_id=RUN):
    """Invoke ``orch-cost`` against ``root`` and assert it succeeded."""
    result = runner.invoke(
        cli, ["orch-cost", run_id, "--transcripts", str(root), *args]
    )
    assert result.exit_code == 0, result.output
    return result


def _report_json(runner, root, run_id=RUN):
    """The ``--json`` payload as a dict."""
    return json.loads(_run(runner, root, "--json", run_id=run_id).output)


def _section(output, header):
    """The indented body lines printed under ``header``, up to the blank line.

    The report is a flat block of text; a criterion about "the tool result
    bytes section" is a claim about the lines between that header and the
    next blank line, so the tests read exactly that rather than grepping the
    whole page and hoping the hit was in the right place.
    """
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == header:
            body = []
            for candidate in lines[index + 1 :]:
                if not candidate.strip():
                    break
                body.append(candidate)
            return body
    raise AssertionError(f"section {header!r} missing from:\n{output}")


def _tool_rows(output):
    """``[(tool name, bytes)]`` in the order the tool table printed them."""
    rows = []
    for line in _section(output, "tool result bytes"):
        match = re.match(r"^\s+(\S+)\s+([\d,]+)$", line)
        assert match, f"unparseable tool row {line!r}"
        rows.append((match.group(1), int(match.group(2).replace(",", ""))))
    return rows


def _waits_line(output):
    """The single ``worker waits`` line, stripped of its leading indent."""
    for line in output.splitlines():
        if line.strip().startswith("worker waits"):
            return line.strip()
    raise AssertionError(f"no worker waits line in:\n{output}")


# --------------------------------------------------------------------------
# Criterion: "The report lists tool result bytes by tool name and worker wait
# p50, p90 and max" (US-PM-52-2)
# --------------------------------------------------------------------------

#: An ``Agent`` hand-back, written the way the harness writes a rich result:
#: a *list* of text blocks.  100 + 20 ASCII characters = 120 bytes, and there
#: are five of them, so ``Agent`` totals 600 bytes.
AGENT_RESULT = [{"type": "text", "text": "A" * 100}, {"type": "text", "text": "B" * 20}]
AGENT_RESULT_BYTES = 120

#: A ``Read`` hand-back as a *plain string*: 1200 ASCII characters.
READ_RESULT = "R" * 1200
READ_RESULT_BYTES = 1200

#: A ``Bash`` hand-back as a plain string of 20 two-byte characters — bytes,
#: not characters, is what the criterion says, and 20 != 40 proves it.
BASH_RESULT = "é" * 20
BASH_RESULT_BYTES = 40

#: A ``Grep`` hand-back as a one-block list of 15 two-byte characters, so
#: the list branch is measured in bytes too, not in characters.
GREP_RESULT = [{"type": "text", "text": "ß" * 15}]
GREP_RESULT_BYTES = 30

#: Largest first, which is the order both the table and ``tool_bytes`` promise.
EXPECTED_TOOL_BYTES = [
    ("Read", READ_RESULT_BYTES),
    ("Agent", AGENT_RESULT_BYTES * 5),
    ("Bash", BASH_RESULT_BYTES),
    ("Grep", GREP_RESULT_BYTES),
]

#: Five dispatches, launched and answered at these minutes: waits of 5, 10,
#: 20, 40 and 90 minutes.  The middle two *overlap* — both are in flight at
#: minute 15 — because a real orchestrator runs workers concurrently, and
#: because that is the only way a launch/notification pairing that answered
#: the wrong launch would show up in the numbers.  Answering newest-first
#: instead would give waits of 5, 5, 25, 40 and 90, and so a p50 of 25.
LAUNCH_AND_NOTIFICATION_MINUTES = [(0, 5), (10, 20), (15, 35), (60, 100), (110, 200)]
EXPECTED_WAITS = [5.0, 10.0, 20.0, 40.0, 90.0]

# Nearest rank over the five sorted waits [5, 10, 20, 40, 90]:
#   p50 -> ceil(0.5 * 5) = 3 -> the 3rd wait  = 20.0
#   p90 -> ceil(0.9 * 5) = 5 -> the 5th wait  = 90.0
#   max ->                     the last wait  = 90.0
EXPECTED_P50 = 20.0
EXPECTED_P90 = 90.0
EXPECTED_MAX = 90.0


@pytest.fixture
def measured(tmp_path):
    """A run with four named tools and five hand-computable worker waits.

    Four distinct tool names return known payloads — two as plain strings,
    two as lists of text blocks — and five ``Agent`` launches are each
    answered by a later ``<task-notification>`` user record, so every number
    the criterion names can be recomputed by hand from this list.
    """
    root = _root(tmp_path, "projects")
    records = [
        # The run id has to appear for the run to be found and for the
        # accounting to start; a real orchestrator stamps it in its opening.
        _assistant(
            0,
            usage=_usage(inputs=100, creation=900, read=0),
            blocks=[
                _text(f"starting run {RUN}"),
                _tool_use("a1", "Agent", prompt="task one"),
            ],
        ),
        _assistant(1, blocks=[_tool_use("r1", "Read", file_path="/a")]),
        _user(2, blocks=[_tool_result("r1", READ_RESULT)]),
        _user(5, blocks=[_text(NOTIFICATION), _tool_result("a1", AGENT_RESULT)]),
        _assistant(10, blocks=[_tool_use("a2", "Agent", prompt="task two")]),
        _assistant(12, blocks=[_tool_use("b1", "Bash", command="ls")]),
        _user(13, blocks=[_tool_result("b1", BASH_RESULT)]),
        # Launched while task two is still out: two workers in flight at once.
        _assistant(15, blocks=[_tool_use("a3", "Agent", prompt="task three")]),
        _user(20, blocks=[_text(NOTIFICATION), _tool_result("a2", AGENT_RESULT)]),
        _assistant(30, blocks=[_tool_use("g1", "Grep", pattern="x")]),
        _user(31, blocks=[_tool_result("g1", GREP_RESULT)]),
        _user(35, blocks=[_text(NOTIFICATION), _tool_result("a3", AGENT_RESULT)]),
        _assistant(60, blocks=[_tool_use("a4", "Agent", prompt="task four")]),
        _user(100, blocks=[_text(NOTIFICATION), _tool_result("a4", AGENT_RESULT)]),
        _assistant(110, blocks=[_tool_use("a5", "Agent", prompt="task five")]),
        _user(200, blocks=[_text(NOTIFICATION), _tool_result("a5", AGENT_RESULT)]),
    ]
    _transcript(root, records, name="measured.jsonl")
    return root


def test_text_report_lists_tool_result_bytes_by_tool_name(runner, measured):
    """Every tool name appears with its exact byte count, largest first."""
    output = _run(runner, measured).output

    assert _tool_rows(output) == EXPECTED_TOOL_BYTES


def test_text_report_tool_bytes_are_bytes_not_characters(runner, measured):
    """Bytes, not characters — for a string payload and for a list one.

    ``Bash`` handed back 20 two-byte characters as a plain string and
    ``Grep`` handed back 15 of them inside a text block; the table has to
    say 40 and 30, not 20 and 15.
    """
    rows = dict(_tool_rows(_run(runner, measured).output))

    assert len(BASH_RESULT) == 20
    assert rows["Bash"] == BASH_RESULT_BYTES == 40
    assert len(GREP_RESULT[0]["text"]) == 15
    assert rows["Grep"] == GREP_RESULT_BYTES == 30


def test_text_report_carries_wait_p50_p90_and_max(runner, measured):
    """The waits line quotes the three hand-computed percentiles, and n."""
    output = _run(runner, measured).output

    assert _waits_line(output) == (
        "worker waits (minutes)  p50 20.0  p90 90.0  max 90.0  (n=5)"
    )


def test_json_report_carries_the_same_tool_bytes_and_waits(runner, measured):
    """``--json`` is the same measurement, unformatted."""
    report = _report_json(runner, measured)

    assert list(report["tool_bytes"].items()) == EXPECTED_TOOL_BYTES
    assert report["waits"] == {
        "p50": EXPECTED_P50,
        "p90": EXPECTED_P90,
        "max": EXPECTED_MAX,
        "n": len(EXPECTED_WAITS),
    }
    assert report["dispatches"] == len(LAUNCH_AND_NOTIFICATION_MINUTES)


@pytest.fixture
def dispatchless(tmp_path):
    """The same run id, but a session that never launched a worker.

    Falsification: if the report invented percentiles or tool rows from
    nothing, the criterion's numbers would not be measurements.
    """
    root = _root(tmp_path, "quiet")
    _transcript(
        root,
        [
            _user(0, blocks=[_text(f"starting run {RUN}")]),
            _assistant(1, usage=_usage(inputs=100, creation=900, read=0)),
            _assistant(2, usage=_usage(inputs=10, creation=0, read=1490)),
        ],
        name="quiet.jsonl",
    )
    return root


def test_no_agent_launches_means_no_wait_percentiles(runner, dispatchless):
    """With nothing dispatched the percentiles print as ``-`` at n=0."""
    output = _run(runner, dispatchless).output

    assert _waits_line(output) == (
        "worker waits (minutes)  p50 -  p90 -  max -  (n=0)"
    )


def test_no_tool_results_means_an_empty_tool_table(runner, dispatchless):
    """The tool section is present but says ``(none)``, not a stale row."""
    output = _run(runner, dispatchless).output

    assert [line.strip() for line in _section(output, "tool result bytes")] == [
        "(none)"
    ]


def test_json_report_for_a_dispatchless_run_has_null_percentiles(
    runner, dispatchless
):
    report = _report_json(runner, dispatchless)

    assert report["tool_bytes"] == {}
    assert report["waits"] == {"p50": None, "p90": None, "max": None, "n": 0}
    assert report["dispatches"] == 0


# --------------------------------------------------------------------------
# Criterion: "The report lists each full cache miss with the gap in minutes
# before it" (US-PM-52-3)
# --------------------------------------------------------------------------

#: A call is a full cache miss when its fresh tokens (input + cache creation)
#: are *strictly greater* than half the context it saw — ``orch_cost`` writes
#: ``(inputs + creation) > context * MISS_FRACTION``, so a call sitting on
#: exactly half is a hit, not a miss.  The ``boundary`` fixture below pins
#: that both ways with adjacent calls at half and half-plus-one.
#:
#: The ``missy`` timeline, in minutes from ``BASE`` (2026-09-09 10:00Z):
#:
#:   0    100 fresh + 900 created, nothing read  -> MISS, no predecessor
#:   3    cache hit (30 fresh of 1,530)
#:   8    cache hit (30 fresh of 2,030)
#:   83   2,300 fresh of 2,400                   -> MISS, 75 minutes idle
#:   90   1,000 fresh of 2,000 — exactly half    -> hit, on the boundary
#:   95   cache hit (20 fresh of 2,420)
#:   225  2,900 fresh of 3,100                   -> MISS, 130 minutes idle
#:   230  cache hit (20 fresh of 3,120)
#:
#: The two long gaps are the shape the criterion exists to expose: a worker
#: waited on past the one-hour prefix-cache TTL, so the next call re-sent the
#: whole prompt.
EXPECTED_MISSES = [
    {"at": "2026-09-09T10:00:00+00:00", "gap_min": None, "tokens": 1000},
    {"at": "2026-09-09T11:23:00+00:00", "gap_min": 75.0, "tokens": 2300},
    {"at": "2026-09-09T13:45:00+00:00", "gap_min": 130.0, "tokens": 2900},
]

#: The exact-half call's timestamp, which must appear in *no* miss row.
BOUNDARY_AT = "2026-09-09T11:30:00+00:00"


def _miss_rows(output):
    """``[(iso timestamp, gap text, tokens)]`` as the miss section printed."""
    rows = []
    for line in _section(output, "full cache misses"):
        match = re.match(r"^\s+(\S+)\s+gap\s+(\S+)\s+min\s+([\d,]+)\s+tokens$", line)
        assert match, f"unparseable miss row {line!r}"
        rows.append(
            (match.group(1), match.group(2), int(match.group(3).replace(",", "")))
        )
    return rows


@pytest.fixture
def missy(tmp_path):
    """A run of mostly-cached calls with three full misses at known gaps."""
    root = _root(tmp_path, "missy")
    _transcript(
        root,
        [
            _assistant(
                0,
                usage=_usage(inputs=100, creation=900, read=0),
                blocks=[_text(f"starting run {RUN}")],
            ),
            _assistant(3, usage=_usage(inputs=10, creation=20, read=1500)),
            _assistant(8, usage=_usage(inputs=10, creation=20, read=2000)),
            # 75 minutes after the call at minute 8: the cache is gone.
            _assistant(83, usage=_usage(inputs=200, creation=2100, read=100)),
            # Exactly half the context is fresh — a hit, by the strict ``>``.
            _assistant(90, usage=_usage(inputs=100, creation=900, read=1000)),
            _assistant(95, usage=_usage(inputs=10, creation=10, read=2400)),
            # 130 minutes after the call at minute 95.
            _assistant(225, usage=_usage(inputs=300, creation=2600, read=200)),
            _assistant(230, usage=_usage(inputs=10, creation=10, read=3100)),
        ],
        name="missy.jsonl",
    )
    return root


def test_text_report_lists_each_full_cache_miss_with_its_gap(runner, missy):
    """Exactly the three misses, in transcript order, each with gap and size."""
    output = _run(runner, missy).output

    assert _miss_rows(output) == [
        ("2026-09-09T10:00:00+00:00", "-", 1000),
        ("2026-09-09T11:23:00+00:00", "75.0", 2300),
        ("2026-09-09T13:45:00+00:00", "130.0", 2900),
    ]


def test_text_report_omits_the_cached_calls_and_the_boundary_call(runner, missy):
    """Five of the eight calls are hits — including the exactly-half one."""
    output = _run(runner, missy).output
    stamps = [at for at, _, _ in _miss_rows(output)]

    assert BOUNDARY_AT not in stamps
    assert len(stamps) == 3
    report = _report_json(runner, missy)
    assert report["calls"] == 8


def test_text_report_prints_a_dash_for_the_first_calls_missing_gap(runner, missy):
    """The first call has no predecessor to be idle from, so its gap is ``-``."""
    first_at, first_gap, _ = _miss_rows(_run(runner, missy).output)[0]

    assert first_at == "2026-09-09T10:00:00+00:00"
    assert first_gap == "-"


def test_json_report_carries_the_same_misses(runner, missy):
    """``--json`` says ``at``, ``gap_min`` and ``tokens``, same order."""
    report = _report_json(runner, missy)

    assert report["misses"] == EXPECTED_MISSES
    assert report["misses"][0]["gap_min"] is None


@pytest.fixture
def boundary(tmp_path):
    """Two adjacent calls: fresh tokens exactly half, then half plus one."""
    root = _root(tmp_path, "boundary")
    _transcript(
        root,
        [
            _user(0, blocks=[_text(f"starting run {RUN}")]),
            _assistant(1, usage=_usage(inputs=10, creation=10, read=1980)),
            # 1,000 fresh of 2,000 — exactly half.
            _assistant(2, usage=_usage(inputs=500, creation=500, read=1000)),
            # 1,001 fresh of 2,000 — one token over half.
            _assistant(3, usage=_usage(inputs=501, creation=500, read=999)),
        ],
        name="boundary.jsonl",
    )
    return root


def test_exactly_half_the_context_is_not_a_miss_but_one_token_over_is(
    runner, boundary
):
    """The threshold is strict ``>``: half is cached, half-plus-one is a miss."""
    output = _run(runner, boundary).output

    assert _miss_rows(output) == [("2026-09-09T10:03:00+00:00", "1.0", 1001)]
    assert _report_json(runner, boundary)["misses"] == [
        {"at": "2026-09-09T10:03:00+00:00", "gap_min": 1.0, "tokens": 1001}
    ]


@pytest.fixture
def missless(tmp_path):
    """A run whose every call read its prefix from cache."""
    root = _root(tmp_path, "missless")
    _transcript(
        root,
        [
            _user(0, blocks=[_text(f"starting run {RUN}")]),
            _assistant(1, usage=_usage(inputs=10, creation=10, read=1980)),
            _assistant(2, usage=_usage(inputs=20, creation=0, read=2400)),
            _assistant(9, usage=_usage(inputs=15, creation=40, read=3000)),
        ],
        name="missless.jsonl",
    )
    return root


def test_a_run_with_no_misses_prints_the_empty_marker(runner, missless):
    """The section is still printed — it says ``(none)``, not a stale row."""
    output = _run(runner, missless).output

    assert [line.strip() for line in _section(output, "full cache misses")] == [
        "(none)"
    ]


def test_json_report_for_a_missless_run_has_an_empty_miss_list(runner, missless):
    report = _report_json(runner, missless)

    assert report["misses"] == []
    assert report["calls"] == 3


# --------------------------------------------------------------------------
# Criterion: "Records sharing a message id are counted once" (US-PM-52-4)
# --------------------------------------------------------------------------

#: Claude Code does not write one transcript record per API call — it writes
#: one per *content block*, and every record of the one call repeats that
#: call's ``message.id`` and its ``usage`` verbatim.  A message that answered
#: with a sentence and a dispatch lands as two records; one that answered
#: with a sentence, a dispatch and a read lands as three; and the harness
#: sometimes repeats a record outright.  Counting records instead of message
#: ids would bill one API call several times over.
#:
#: Each entry below is ``(message id, minute, usage, [blocks per record])``.
#: The four messages, in transcript order:
#:
#:   msg_a  min 0   ctx 1,000  out 300   2 records  text + Agent
#:   msg_b  min 10  ctx 2,500  out  90   4 records  text + Agent + Agent again
#:                                                  (a repeated record) + Read
#:   msg_c  min 20  ctx 4,000  out  60   3 records  Agent + pm_accept +
#:                                                  pm_accept again
#:   msg_d  min 30  ctx 3,000  out 150   1 record   text
#:
#: 4 messages, 10 records: every number below separates the two.
DUPLICATED_MESSAGES = [
    (
        "msg_a",
        0,
        dict(inputs=200, creation=800, read=0, output=300),
        [
            [{"type": "text", "text": f"starting run {RUN}"}],
            [_tool_use("a1", "Agent", prompt="task one")],
        ],
    ),
    (
        "msg_b",
        10,
        dict(inputs=100, creation=100, read=2300, output=90),
        [
            [_text("dispatching task two and reading a file")],
            [_tool_use("b1", "Agent", prompt="task two")],
            # The same block written a second time: same block id, so it is
            # the same dispatch, not a second one.
            [_tool_use("b1", "Agent", prompt="task two")],
            [_tool_use("b2", "Read", file_path="/a")],
        ],
    ),
    (
        "msg_c",
        20,
        dict(inputs=50, creation=0, read=3950, output=60),
        [
            [_tool_use("c1", "Agent", prompt="task three")],
            [_tool_use("c2", "mcp__projectman__pm_accept", task_id="US-PM-52-4")],
            # The accept, repeated: one task was accepted, not two.
            [_tool_use("c2", "mcp__projectman__pm_accept", task_id="US-PM-52-4")],
        ],
    ),
    (
        "msg_d",
        30,
        dict(inputs=20, creation=0, read=2980, output=150),
        [[_text("worker finished")]],
    ),
]

#: What the transcript above says, read one call per message id.
DEDUPED_CALLS = 4
DEDUPED_DISPATCHES = 3  # a1, b1, c1 — b1's repeat is the same dispatch
DEDUPED_ACCEPTS = 1  # c2 — written twice, accepted once
DEDUPED_BASE = 1000  # msg_a: 200 fresh + 800 created + 0 read
DEDUPED_PEAK = 4000  # msg_c: 50 + 0 + 3,950
DEDUPED_GROWTH = 3000  # 4,000 - 1,000
DEDUPED_PER_DISPATCH = 1000.0  # 3,000 / 3
DEDUPED_PER_TASK = 3000.0  # 3,000 / 1
DEDUPED_CALLS_PER_DISPATCH = 1.3  # 4 / 3, to one decimal
#: 300 + 90 + 60 + 150 output tokens over four distinct messages.
DEDUPED_OUTPUT_PER_CALL = 150.0

#: And what it would say if a record were mistaken for a call.
RECORD_COUNT = 10
#: 300x2 + 90x4 + 60x3 + 150x1 = 1,290 output tokens over ten records.
PER_RECORD_OUTPUT_PER_CALL = 129.0
PER_RECORD_CALLS_PER_DISPATCH = 3.3  # 10 / 3
#: 1,000x2 + 2,500x4 + 4,000x3 + 3,000x1 — the context a reader that added up
#: every record's usage would report as the run's peak.
PER_RECORD_CONTEXT_SUM = 27000
PER_RECORD_GROWTH = PER_RECORD_CONTEXT_SUM - DEDUPED_BASE  # 26,000


def _duplicated_records(*, unique_ids):
    """The transcript above, deduped-by-message-id or with every id unique.

    ``unique_ids=True`` is the falsification control: the same records, the
    same usage, the same blocks, the same timestamps — only the message ids
    differ, so anything that changes changed *because* of the message id.
    """
    records = []
    for message_id, minute, usage, per_record in DUPLICATED_MESSAGES:
        for index, blocks in enumerate(per_record):
            records.append(
                _assistant(
                    minute,
                    message_id=f"{message_id}_{index}" if unique_ids else message_id,
                    usage=_usage(**usage),
                    blocks=blocks,
                )
            )
    return records


def _summary_rows(output):
    """``{label: printed value}`` for the leading block of counts and ratios."""
    rows = {}
    for line in output.splitlines()[1:]:  # line 0 is the transcript path
        if not line.strip():
            break
        label, _, value = line.strip().rpartition("  ")
        rows[label.strip()] = value.strip()
    return rows


@pytest.fixture
def blockwise(tmp_path):
    """A run written the way the harness writes one: a record per block."""
    root = _root(tmp_path, "blockwise")
    _transcript(root, _duplicated_records(unique_ids=False), name="blockwise.jsonl")
    return root


@pytest.fixture
def unkeyed(tmp_path):
    """The control: the same run with a unique message id on every record."""
    root = _root(tmp_path, "unkeyed")
    _transcript(root, _duplicated_records(unique_ids=True), name="unkeyed.jsonl")
    return root


def test_calls_counts_distinct_message_ids_not_records(runner, blockwise):
    """Ten records, four message ids, four API calls — in text and in JSON."""
    assert len(_duplicated_records(unique_ids=False)) == RECORD_COUNT
    assert len({entry[0] for entry in DUPLICATED_MESSAGES}) == DEDUPED_CALLS

    output = _run(runner, blockwise).output

    assert _summary_rows(output)["calls"] == str(DEDUPED_CALLS)
    assert _report_json(runner, blockwise)["calls"] == DEDUPED_CALLS


def test_a_repeated_record_does_not_repeat_its_dispatch_or_accept(
    runner, blockwise
):
    """``b1`` and ``c2`` were each written twice and each count once."""
    rows = _summary_rows(_run(runner, blockwise).output)
    report = _report_json(runner, blockwise)

    assert rows["dispatches"] == str(DEDUPED_DISPATCHES)
    assert rows["accepts"] == str(DEDUPED_ACCEPTS)
    assert report["dispatches"] == DEDUPED_DISPATCHES == 3
    assert report["accepts"] == DEDUPED_ACCEPTS == 1


def test_context_peak_and_growth_are_computed_from_the_deduped_usage(
    runner, blockwise
):
    """Peak is the largest message's context, not the sum over records."""
    rows = _summary_rows(_run(runner, blockwise).output)
    report = _report_json(runner, blockwise)

    assert (report["base"], report["peak"], report["growth"]) == (
        DEDUPED_BASE,
        DEDUPED_PEAK,
        DEDUPED_GROWTH,
    )
    assert report["peak"] != PER_RECORD_CONTEXT_SUM
    assert report["growth"] != PER_RECORD_GROWTH
    assert rows["base"] == "1,000"
    assert rows["peak"] == "4,000"
    assert rows["growth"] == "3,000"
    assert rows["growth per dispatch"] == "1,000.0"
    assert rows["growth per accepted task"] == "3,000.0"
    assert report["per_dispatch"] == DEDUPED_PER_DISPATCH
    assert report["per_task"] == DEDUPED_PER_TASK


def test_output_tokens_per_call_is_averaged_over_distinct_messages(
    runner, blockwise
):
    """600 output tokens over 4 calls is 150.0 — over 10 records it is 129.0."""
    rows = _summary_rows(_run(runner, blockwise).output)
    report = _report_json(runner, blockwise)

    assert rows["output tokens per call"] == "150.0"
    assert rows["calls per dispatch"] == "1.3"
    assert report["output_per_call"] == DEDUPED_OUTPUT_PER_CALL
    assert report["output_per_call"] != PER_RECORD_OUTPUT_PER_CALL
    assert report["calls_per_dispatch"] == DEDUPED_CALLS_PER_DISPATCH


def test_a_repeated_record_is_not_a_second_cache_miss(runner, blockwise):
    """``msg_a`` re-sent the whole prompt once, and its repeat adds nothing."""
    report = _report_json(runner, blockwise)

    assert report["misses"] == [
        {"at": "2026-09-09T10:00:00+00:00", "gap_min": None, "tokens": 1000}
    ]
    assert _miss_rows(_run(runner, blockwise).output) == [
        ("2026-09-09T10:00:00+00:00", "-", 1000)
    ]


def test_unique_message_ids_per_record_yield_the_uncollapsed_counts(
    runner, unkeyed
):
    """Falsification: change only the message ids and the call counts move.

    Same blocks, same usage, same timestamps — so if the counts collapsed on
    anything other than ``message.id`` they would be unmoved here.  They are
    not: ten calls instead of four, the output average and the calls-per-
    dispatch ratio recomputed over records, and ``msg_a``'s repeat now
    reported as a second full cache miss zero minutes after the first.
    """
    rows = _summary_rows(_run(runner, unkeyed).output)
    report = _report_json(runner, unkeyed)

    assert report["calls"] == RECORD_COUNT > DEDUPED_CALLS
    assert rows["calls"] == str(RECORD_COUNT)
    assert report["output_per_call"] == PER_RECORD_OUTPUT_PER_CALL
    assert report["calls_per_dispatch"] == PER_RECORD_CALLS_PER_DISPATCH
    assert [miss["gap_min"] for miss in report["misses"]] == [None, 0.0]


def test_unique_message_ids_do_not_multiply_dispatches_or_accepts(
    runner, unkeyed
):
    """The other half of the control: tool_use collapses on its *block* id.

    Making every message id unique leaves ``b1``'s and ``c2``'s repeats
    collapsed, which is what keeps the two keys distinct — usage is counted
    once per message, a tool call once per block.  Peak and base are a
    maximum and a first value, so they are unmoved too.
    """
    report = _report_json(runner, unkeyed)

    assert report["dispatches"] == DEDUPED_DISPATCHES
    assert report["accepts"] == DEDUPED_ACCEPTS
    assert report["base"] == DEDUPED_BASE
    assert report["peak"] == DEDUPED_PEAK
    assert report["growth"] == DEDUPED_GROWTH


# --------------------------------------------------------------------------
# Criterion: "projectman orch-cost <run-id> finds the transcript containing
# that run id and prints growth per dispatch and per accepted task, calls per
# dispatch and output tokens per call" (US-PM-52-1)
# --------------------------------------------------------------------------

#: Another run's id, for the transcripts that must *not* be picked up.  It is
#: shaped like a real one so the discovery test proves the command matched on
#: the id it was given rather than on "looks like an orch- run".
OTHER_RUN = "orch-2026-09-08-9999"


def _paths(output):
    """The transcript paths the text report printed, in printed order.

    Every line of a report body is indented; a path is the only line flush
    with the left margin, so the unindented lines are exactly the files the
    command decided to report on.
    """
    return [line for line in output.splitlines() if line and not line[0].isspace()]


def _error_text(result):
    """Everything the failed invocation said, wherever click put it."""
    text = result.output or ""
    try:
        text += result.stderr or ""
    except ValueError:  # click <8.2 mixes stderr into output already
        pass
    return text


def _nested(root, project, name, records):
    """Write a transcript at ``root/<project>/<name>``.

    ``~/.claude/projects`` is a directory per project holding a file per
    session, so the fixtures are laid out that way: a flat search would find
    these files by luck, and the nesting is what makes the recursion real.
    """
    directory = root / project
    directory.mkdir(exist_ok=True)
    return _transcript(directory, records, name=name)


@pytest.fixture
def one_hit(tmp_path):
    """Three ``.jsonl`` files in two project directories; one is the run."""
    root = _root(tmp_path, "one_hit")
    hit = _nested(
        root,
        "-mnt-repos-ProjectMan",
        "hit.jsonl",
        [_user(0, blocks=[_text(f"starting run {RUN}")])],
    )
    _nested(
        root,
        "-mnt-repos-Other",
        "other-run.jsonl",
        [_user(0, blocks=[_text(f"starting run {OTHER_RUN}")])],
    )
    # A ``.jsonl`` that is not a session transcript at all — no run id, no
    # usage, no messages.  Discovery must step over it, not measure it.
    (root / "-mnt-repos-ProjectMan" / "notes.jsonl").write_text(
        json.dumps({"kind": "note", "text": "no run id in here"}) + "\n",
        encoding="utf-8",
    )
    return root, hit


@pytest.fixture
def two_hits(tmp_path):
    """Two sessions of the same run, the second one touched later."""
    root = _root(tmp_path, "two_hits")
    older = _nested(
        root,
        "-mnt-repos-ProjectMan",
        "older.jsonl",
        [_user(0, blocks=[_text(f"starting run {RUN}")])],
    )
    newer = _nested(
        root,
        "-mnt-repos-ProjectMan-worktree",
        "newer.jsonl",
        [_user(0, blocks=[_text(f"resuming run {RUN}")])],
    )
    os.utime(older, (1_600_000_000, 1_600_000_000))
    os.utime(newer, (1_700_000_000, 1_700_000_000))
    return root, newer, older


@pytest.fixture
def no_hits(tmp_path):
    """A root holding somebody else's run and nothing of ours."""
    root = _root(tmp_path, "no_hits")
    _nested(
        root,
        "-mnt-repos-Other",
        "other-run.jsonl",
        [_user(0, blocks=[_text(f"starting run {OTHER_RUN}")])],
    )
    return root


def test_the_report_names_the_transcript_containing_the_run_id(runner, one_hit):
    """One file mentions the run id, so one file is reported — and only it."""
    root, hit = one_hit
    output = _run(runner, root).output

    assert _paths(output) == [str(hit)]
    assert "other-run.jsonl" not in output
    assert "notes.jsonl" not in output


def test_the_json_report_names_the_same_single_transcript(runner, one_hit):
    """``--json`` for a single match is one object carrying that path."""
    root, hit = one_hit
    report = _report_json(runner, root)

    assert isinstance(report, dict)
    assert report["path"] == str(hit)


def test_two_transcripts_of_one_run_are_both_reported_newest_first(
    runner, two_hits
):
    """A run that spanned two sessions is two reports, most recent first."""
    root, newer, older = two_hits
    output = _run(runner, root).output
    report = _report_json(runner, root)

    assert _paths(output) == [str(newer), str(older)]
    assert [entry["path"] for entry in report] == [str(newer), str(older)]


def test_a_run_id_no_transcript_mentions_fails_loudly(runner, no_hits):
    """No match is an error with the run id and the root in it, not zeros."""
    result = runner.invoke(
        cli, ["orch-cost", RUN, "--transcripts", str(no_hits)]
    )
    message = _error_text(result)

    assert result.exit_code != 0
    assert RUN in message
    assert str(no_hits) in message
    assert "dispatches" not in message


# The measured run, by hand.  Six assistant messages carry four ``Agent``
# dispatches and two accepts; the context runs 2,000 -> 10,000 -> 9,000, so
# the peak is the fifth call and the growth is 8,000.  Every ratio below is
# that arithmetic and nothing else.
METRIC_DISPATCHES = 4  # d1, d2, d3, d4
METRIC_ACCEPTS = 2  # one pm_accept, one pm_done_next
METRIC_CALLS = 6
METRIC_BASE = 2000
METRIC_PEAK = 10000
METRIC_GROWTH = METRIC_PEAK - METRIC_BASE  # 8,000
#: 100 + 200 + 300 + 150 + 250 + 200 output tokens across the six messages.
METRIC_OUTPUT = 1200
METRIC_PER_DISPATCH = 2000.0  # 8,000 / 4
METRIC_PER_TASK = 4000.0  # 8,000 / 2
METRIC_CALLS_PER_DISPATCH = 1.5  # 6 / 4
METRIC_OUTPUT_PER_CALL = 200.0  # 1,200 / 6

#: The context of the call *before* the run started.  Five times the peak, so
#: a reader that measured the whole file instead of the run would report a
#: base of 50,000 and no growth at all.
PRE_RUN_CONTEXT = 50_000


def _metric_records(*, accepts=True):
    """The measured run, optionally with its accepts taken out.

    Dropping the accepts leaves every message, every dispatch and every usage
    where it was — only the denominator of "growth per accepted task" goes to
    zero, which is what makes the ``-`` row a consequence of the accepts and
    not of a different fixture.
    """
    accept = [_tool_use("x1", "mcp__projectman__pm_accept", id="US-PM-52-1")]
    done_next = [_tool_use("x2", "mcp__projectman__pm_done_next")]
    return [
        # Before the run: a big call from whatever this session did earlier.
        _assistant(
            0,
            usage=_usage(inputs=PRE_RUN_CONTEXT, creation=0, read=0, output=999),
            blocks=[_text(f"finishing run {OTHER_RUN}")],
        ),
        _assistant(
            1,
            usage=_usage(inputs=200, creation=1800, read=0, output=100),
            blocks=[_text(f"starting run {RUN}")],
        ),
        _assistant(
            5,
            usage=_usage(inputs=50, creation=0, read=3950, output=200),
            blocks=[_tool_use("d1", "Agent", prompt="task one")],
        ),
        _assistant(
            10,
            usage=_usage(inputs=50, creation=0, read=5950, output=300),
            blocks=[_tool_use("d2", "Agent", prompt="task two")],
        ),
        _assistant(
            15,
            usage=_usage(inputs=100, creation=0, read=7900, output=150),
            blocks=[_tool_use("d3", "Agent", prompt="task three")]
            + (accept if accepts else []),
        ),
        _assistant(
            20,
            usage=_usage(inputs=100, creation=0, read=9900, output=250),
            blocks=[_tool_use("d4", "Agent", prompt="task four")],
        ),
        _assistant(
            25,
            usage=_usage(inputs=100, creation=0, read=8900, output=200),
            blocks=[_text("wrapping up")] + (done_next if accepts else []),
        ),
    ]


@pytest.fixture
def measured_run(tmp_path):
    """A run whose four ratios are computable on the back of an envelope."""
    root = _root(tmp_path, "measured_run")
    _nested(root, "-mnt-repos-ProjectMan", "run.jsonl", _metric_records())
    return root


@pytest.fixture
def acceptless_run(tmp_path):
    """The same run with nothing accepted — the zero-denominator case."""
    root = _root(tmp_path, "acceptless_run")
    _nested(
        root,
        "-mnt-repos-ProjectMan",
        "run.jsonl",
        _metric_records(accepts=False),
    )
    return root


def test_the_counts_the_four_ratios_are_built_from(runner, measured_run):
    """Four dispatches, two accepts, six calls, 8,000 tokens of growth."""
    rows = _summary_rows(_run(runner, measured_run).output)
    report = _report_json(runner, measured_run)

    assert (report["dispatches"], report["accepts"], report["calls"]) == (
        METRIC_DISPATCHES,
        METRIC_ACCEPTS,
        METRIC_CALLS,
    )
    assert (report["base"], report["peak"], report["growth"]) == (
        METRIC_BASE,
        METRIC_PEAK,
        METRIC_GROWTH,
    )
    assert rows["dispatches"] == str(METRIC_DISPATCHES)
    assert rows["accepts"] == str(METRIC_ACCEPTS)
    assert rows["calls"] == str(METRIC_CALLS)
    assert rows["growth"] == "8,000"


def test_text_report_prints_growth_per_dispatch_and_per_accepted_task(
    runner, measured_run
):
    """(peak - base) / dispatches and / accepts, as the report prints them."""
    rows = _summary_rows(_run(runner, measured_run).output)

    assert METRIC_PER_DISPATCH == METRIC_GROWTH / METRIC_DISPATCHES
    assert METRIC_PER_TASK == METRIC_GROWTH / METRIC_ACCEPTS
    assert rows["growth per dispatch"] == "2,000.0"
    assert rows["growth per accepted task"] == "4,000.0"


def test_text_report_prints_calls_per_dispatch_and_output_per_call(
    runner, measured_run
):
    """calls / dispatches and output tokens / calls, likewise."""
    rows = _summary_rows(_run(runner, measured_run).output)

    assert METRIC_CALLS_PER_DISPATCH == METRIC_CALLS / METRIC_DISPATCHES
    assert METRIC_OUTPUT_PER_CALL == METRIC_OUTPUT / METRIC_CALLS
    assert rows["calls per dispatch"] == "1.5"
    assert rows["output tokens per call"] == "200.0"


def test_json_report_carries_the_same_four_ratios(runner, measured_run):
    """``--json`` is the same four numbers under their machine names."""
    report = _report_json(runner, measured_run)

    assert report["per_dispatch"] == METRIC_PER_DISPATCH
    assert report["per_task"] == METRIC_PER_TASK
    assert report["calls_per_dispatch"] == METRIC_CALLS_PER_DISPATCH
    assert report["output_per_call"] == METRIC_OUTPUT_PER_CALL


def test_growth_per_accepted_task_is_a_dash_when_nothing_was_accepted(
    runner, acceptless_run
):
    """Zero accepts is an undefined ratio, printed ``-`` and JSON ``null``."""
    rows = _summary_rows(_run(runner, acceptless_run).output)
    report = _report_json(runner, acceptless_run)

    assert report["accepts"] == 0
    assert report["per_task"] is None
    assert rows["accepts"] == "0"
    assert rows["growth per accepted task"] == "-"
    # The other three ratios still have denominators, so they still print.
    assert report["per_dispatch"] == METRIC_PER_DISPATCH
    assert rows["growth per dispatch"] == "2,000.0"
    assert rows["calls per dispatch"] == "1.5"
    assert rows["output tokens per call"] == "200.0"


def test_accounting_starts_at_the_first_record_naming_the_run(
    runner, measured_run
):
    """The call before the run began sets nothing — not the base, not a call.

    The pre-run message is five times the peak and carries 999 output tokens
    of its own, so every one of the four ratios would move if the command
    measured the file rather than the run: the base would be 50,000, growth
    zero, and the output average 314.1 over seven calls.
    """
    rows = _summary_rows(_run(runner, measured_run).output)
    report = _report_json(runner, measured_run)

    assert report["base"] == METRIC_BASE < PRE_RUN_CONTEXT
    assert report["calls"] == METRIC_CALLS
    assert rows["base"] == "2,000"
    assert rows["peak"] == "10,000"
    assert report["peak"] == METRIC_PEAK
    assert report["growth"] == METRIC_GROWTH
    assert report["output_per_call"] == METRIC_OUTPUT_PER_CALL
