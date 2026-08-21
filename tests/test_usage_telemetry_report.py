"""Tests for the usage-telemetry metrics report (US-PM-6-8).

Covers story AC 3: per-tool call counts, response bytes and consecutive-run
lengths, plus the adjacency bigrams the plan's bulk-call stories are argued
from.

The load-bearing property is the transcript boundary: runs and bigrams must
never join the last call of one transcript file to the first call of the next.
The corpus walk is sorted, so a cross-file pair would look entirely plausible
and be entirely fictional -- ``test_runs_never_span_transcript_files`` and
``test_bigrams_never_span_transcript_files`` pin it down.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tools.usage_telemetry as tx_pkg
from tools.usage_telemetry import report as rp
from tools.usage_telemetry.classify import classify_all
from tools.usage_telemetry.extract import DEFAULT_PREVIEW_CHARS, ToolCall, ToolResult, scan

REPO_ROOT = Path(__file__).resolve().parents[1]

SOFT_NOTE_LIMIT = '{"result":"error: Run-log note must be 1024 characters or fewer"}'


# ---------------------------------------------------------------- fixtures --


def make_call(
    tool="pm_update",
    session="sess-a",
    seq=0,
    text="ok",
    is_error=False,
    tool_input=None,
    with_result=True,
    tool_use_id=None,
):
    """A joined :class:`ToolCall`, positioned at ``seq`` inside ``session``."""
    call = ToolCall(
        tool_use_id=tool_use_id or f"{session}-{seq}",
        name=f"mcp__projectman__{tool}",
        input={} if tool_input is None else tool_input,
        timestamp="2026-07-29T00:00:00Z",
        session=session,
        session_id=session,
        project="proj",
        source_file=f"/tmp/{session}.jsonl",
        line_no=seq + 1,
        seq=seq,
    )
    if with_result:
        call.result = ToolResult(
            tool_use_id=call.tool_use_id, is_error=is_error, text=text
        )
    return call


def sequence(session, tools, text="ok"):
    """Calls for ``tools`` in order, numbered 0..n-1 within ``session``."""
    return [
        make_call(tool=tool, session=session, seq=i, text=text)
        for i, tool in enumerate(tools)
    ]


def _record(content, session="sess-a"):
    return {
        "type": "assistant",
        "sessionId": session,
        "timestamp": "2026-07-29T00:00:00Z",
        "message": {"content": content},
    }


def _tool_use(tool_use_id, name, tool_input=None):
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": name,
        "input": {} if tool_input is None else tool_input,
    }


def _tool_result(tool_use_id, content="ok", is_error=False):
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _write_transcript(root, project, session, records):
    path = root / project / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


@pytest.fixture
def corpus(tmp_path):
    """Two transcripts, each ending and starting with ``pm_update``.

    Deliberately shaped so that a boundary bug shows up as a longer run and an
    extra ``pm_update -> pm_update`` bigram.
    """
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "-home-ryan-Repo-ProjectMan",
        "sess-a",
        [
            _record([_tool_use("a1", "mcp__projectman__pm_grab", {"task_id": "US-X-1"})]),
            _record([_tool_result("a1", "x" * 5000)]),  # over the 4k preview cut
            _record([_tool_use("a2", "mcp__projectman__pm_update", {"id": "US-X-1"})]),
            _record([_tool_result("a2", "ok")]),
            _record([_tool_use("a3", "mcp__projectman__pm_update", {"id": "US-X-2"})]),
            _record([_tool_result("a3", SOFT_NOTE_LIMIT)]),
        ],
    )
    _write_transcript(
        root,
        "-home-ryan-Repo-ProjectMan",
        "sess-b",
        [
            _record([_tool_use("b1", "mcp__projectman__pm_update", {"id": "US-Y-1"})], "s2"),
            _record([_tool_result("b1", "ok")], "s2"),
            _record([_tool_use("b2", "mcp__projectman__pm_get", {"id": "US-Y-1"})], "s2"),
            _record([_tool_result("b2", "héllo")], "s2"),
        ],
    )
    return root


# --------------------------------------------------------------- quantiles --


def test_percentile_is_nearest_rank_so_every_value_really_occurred():
    sample = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert rp.percentile(sample, 0.5) == 5  # lower of the two central values
    assert rp.percentile(sample, 0.9) == 9
    assert rp.percentile(sample, 0.95) == 10
    assert rp.percentile(sample, 1.0) == 10
    assert rp.percentile(sample, 0.0) == 1
    for q in (0.0, 0.25, 0.5, 0.9, 0.99, 1.0):
        assert rp.percentile(sample, q) in sample


def test_percentile_of_an_empty_sample_is_none_not_zero():
    assert rp.percentile([], 0.5) is None


def test_percentile_rejects_a_non_fraction_quantile():
    with pytest.raises(ValueError):
        rp.percentile([1, 2, 3], 95)
    with pytest.raises(ValueError):
        rp.percentile([1, 2, 3], float("nan"))


def test_percentile_does_not_require_sorted_input():
    assert rp.percentile([9, 1, 5, 3, 7], 0.5) == 5


def test_distribution_of_empty_sample_reports_none_not_a_misleading_zero():
    dist = rp.Distribution.of([])
    assert dist.count == 0
    assert dist.total == 0
    assert dist.median is None
    assert dist.maximum is None
    assert dist.as_dict()["p99"] is None


def test_distribution_reports_total_and_every_required_quantile():
    dist = rp.Distribution.of([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    assert dist.total == 550
    assert dist.mean == 55.0
    assert dist.minimum == 10
    assert dist.maximum == 100
    assert set(dist.as_dict()) == {
        "count",
        "total",
        "mean",
        "min",
        "median",
        "p90",
        "p95",
        "p99",
        "max",
    }


# ------------------------------------------------------------ call counts --


def test_reports_per_tool_call_counts():
    calls = sequence("s1", ["pm_update", "pm_update", "pm_get", "pm_grab", "pm_update"])
    report = rp.build_report(calls)

    assert report.total_calls == 5
    assert {u.tool: u.calls for u in report.by_calls()} == {
        "pm_update": 3,
        "pm_get": 1,
        "pm_grab": 1,
    }
    assert report.by_calls()[0].tool == "pm_update"
    assert report.tools["pm_update"].calls / report.total_calls == pytest.approx(0.6)


def test_call_counts_sum_to_the_corpus_total():
    calls = sequence("s1", ["pm_update", "pm_get"]) + sequence("s2", ["pm_grab"])
    report = rp.build_report(calls)
    assert sum(u.calls for u in report.tools.values()) == report.total_calls == 3
    assert report.sessions == 2


def test_per_tool_call_counts_sum_exactly_to_the_total_and_shares_to_one():
    calls = (
        sequence("s1", ["pm_update", "pm_get", "pm_update"])
        + sequence("s2", ["pm_grab", "pm_update"])
        + sequence("s3", ["pm_get"])
    )
    report = rp.build_report(calls)

    assert report.total_calls == 6
    assert sum(u.calls for u in report.tools.values()) == 6
    payload = report.as_dict()
    assert sum(row["calls"] for row in payload["by_tool"]) == 6
    assert payload["totals"]["calls"] == 6
    assert payload["totals"]["tools"] == len(payload["by_tool"]) == 3
    # No call is dropped and none is counted twice.
    assert sum(row["call_share"] for row in payload["by_tool"]) == pytest.approx(1.0)


def test_a_tool_used_in_several_transcripts_aggregates_into_one_row():
    calls = (
        sequence("s1", ["pm_update", "pm_update"], text="a")
        + sequence("s2", ["pm_update"], text="bb")
        + sequence("s3", ["pm_update"], text="ccc")
    )
    report = rp.build_report(calls)

    assert len(report.tools) == 1  # one row, not one per transcript
    usage = report.tools["pm_update"]
    assert usage.calls == 4
    assert usage.result_bytes == 1 + 1 + 2 + 3
    assert report.sessions == 3
    # Counts aggregate across files; runs deliberately do not.
    assert usage.runs.lengths == [2, 1, 1]


def test_the_short_tool_name_is_derived_from_the_mcp_prefix():
    calls = [make_call("pm_done_next", "s1", 0), make_call("pm_web_start", "s1", 1)]
    assert calls[0].name == "mcp__projectman__pm_done_next"

    report = rp.build_report(calls)
    assert set(report.tools) == {"pm_done_next", "pm_web_start"}
    assert all(not tool.startswith("mcp__") for tool in report.tools)
    assert [row["tool"] for row in report.as_dict()["by_tool"]] == [
        "pm_done_next",
        "pm_web_start",
    ]


def test_a_tool_without_the_mcp_prefix_keeps_its_full_name():
    """``--prefix ''`` reports non-MCP tools too; those have nothing to strip."""
    call = make_call("pm_get", "s1", 0)
    call.name = "Bash"
    assert set(rp.build_report([call]).tools) == {"Bash"}


# --------------------------------------------------------- response bytes --


def test_reports_total_response_bytes_per_tool_and_overall():
    calls = [
        make_call("pm_grab", "s1", 0, text="a" * 1000),
        make_call("pm_grab", "s1", 1, text="b" * 500),
        make_call("pm_update", "s1", 2, text="ok"),
    ]
    report = rp.build_report(calls)

    assert report.tools["pm_grab"].result_bytes == 1500
    assert report.tools["pm_update"].result_bytes == 2
    assert report.total_bytes == 1502
    assert report.tools["pm_grab"].result_bytes / report.total_bytes == pytest.approx(
        1500 / 1502
    )


def test_bytes_are_utf8_bytes_not_characters():
    call = make_call("pm_get", "s1", 0, text="héllo")  # 5 chars, 6 bytes
    report = rp.build_report([call])
    assert report.tools["pm_get"].result_chars == 5
    assert report.tools["pm_get"].result_bytes == 6
    assert report.total_bytes == 6


def test_response_bytes_come_from_the_full_body_not_the_stored_preview(corpus):
    """The studies that counted a 3k/4k preview understated the big payloads."""
    extraction = scan(root=corpus)
    report = rp.report_from_extraction(extraction)

    grab = report.tools["pm_grab"]
    assert grab.result_bytes == 5000 > DEFAULT_PREVIEW_CHARS
    assert grab.bytes_per_call.maximum == 5000

    # ...and the preview really is shorter, i.e. the test is not vacuous.
    record = next(c for c in extraction.calls if c.tool == "pm_grab").to_record()
    assert len(record["result_text"]) == DEFAULT_PREVIEW_CHARS
    assert record["result_truncated"] is True
    assert record["result_bytes"] == 5000


def test_reports_a_byte_distribution_not_only_a_mean():
    # One 100 KB read among 99 tiny acks: the mean is a lie, the p99 is not.
    calls = [make_call("pm_get", "s1", i, text="x" * 10) for i in range(99)]
    calls.append(make_call("pm_get", "s1", 99, text="x" * 100_000))
    report = rp.build_report(calls)

    dist = report.tools["pm_get"].bytes_per_call
    assert dist.count == 100
    assert dist.median == 10
    assert dist.p90 == 10
    assert dist.p95 == 10
    assert dist.p99 == 10
    assert dist.maximum == 100_000
    assert dist.mean > 1000  # the mean alone would report ~1,010 bytes/call


def test_corpus_wide_byte_distribution_covers_every_matched_call():
    calls = sequence("s1", ["pm_get", "pm_update"], text="12345")
    report = rp.build_report(calls)
    assert report.bytes_per_call.count == 2
    assert report.bytes_per_call.total == report.total_bytes == 10


def test_unmatched_calls_count_as_calls_but_not_as_zero_byte_responses():
    calls = [
        make_call("pm_get", "s1", 0, text="1234"),
        make_call("pm_get", "s1", 1, with_result=False),
    ]
    report = rp.build_report(calls)

    usage = report.tools["pm_get"]
    assert usage.calls == 2
    assert usage.unmatched == 1
    assert usage.result_bytes == 4
    # A zero sample would drag the median to 2 and understate the real payload.
    assert usage.bytes_per_call.count == 1
    assert usage.bytes_per_call.median == 4
    assert report.unmatched_calls == 1


def test_tools_are_ordered_by_total_bytes_the_headline_number():
    calls = [
        make_call("pm_update", "s1", 0, text="ok"),
        make_call("pm_update", "s1", 1, text="ok"),
        make_call("pm_update", "s1", 2, text="ok"),
        make_call("pm_grab", "s1", 3, text="x" * 4000),
    ]
    report = rp.build_report(calls)
    assert [u.tool for u in report.by_bytes()] == ["pm_grab", "pm_update"]
    assert [u.tool for u in report.by_calls()] == ["pm_update", "pm_grab"]


def test_per_tool_byte_totals_sum_exactly_to_the_corpus_total():
    calls = sequence("s1", ["pm_grab"], text="x" * 900) + sequence(
        "s2", ["pm_update", "pm_get"], text="y" * 30
    )
    report = rp.build_report(calls)

    assert sum(u.result_bytes for u in report.tools.values()) == report.total_bytes == 960
    assert report.bytes_per_call.total == report.total_bytes
    payload = report.as_dict()
    assert sum(row["result_bytes"] for row in payload["by_tool"]) == 960
    assert payload["totals"]["response_bytes"] == 960
    assert sum(row["byte_share"] for row in payload["by_tool"]) == pytest.approx(1.0)


def test_multibyte_bodies_over_the_preview_limit_count_full_utf8_bytes(tmp_path, capsys):
    """5,000 EUR signs: 5,000 chars, 15,000 bytes, 12,000 bytes of preview.

    One number distinguishes all three, so counting characters, counting the
    truncated preview, or counting preview *bytes* each fail here.
    """
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("t1", "mcp__projectman__pm_get")]),
            _record([_tool_result("t1", "€" * 5000)]),
        ],
    )
    assert rp.main(["--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    row = payload["by_tool"][0]
    assert row["result_chars"] == 5000
    assert row["result_bytes"] == 15000
    assert row["bytes_per_call"]["max"] == 15000
    assert row["bytes_per_call"]["median"] == 15000
    assert payload["totals"]["response_bytes"] == 15000
    assert 5000 > DEFAULT_PREVIEW_CHARS  # the body really is truncated on disk


def test_byte_percentiles_are_exact_on_a_hand_computable_dataset():
    """100 calls returning 1..100 bytes; nearest rank puts every quantile on a
    distinct known value, so an interpolating or off-by-one implementation fails.
    """
    calls = [make_call("pm_get", "s1", i, text="x" * (i + 1)) for i in range(100)]
    report = rp.build_report(calls)

    for dist in (report.tools["pm_get"].bytes_per_call, report.bytes_per_call):
        assert dist.count == 100
        assert dist.total == 5050
        assert dist.mean == 50.5
        assert dist.minimum == 1
        assert dist.median == 50
        assert dist.p90 == 90
        assert dist.p95 == 95
        assert dist.p99 == 99
        assert dist.maximum == 100


def test_byte_percentiles_use_nearest_rank_on_a_sample_that_does_not_divide_evenly():
    """13 responses of 100..1300 bytes, sorted; nearest rank is ``ceil(q*13)``.

    Every quantile here lands on a different value than a floor/truncating rank
    would pick (median 700 vs 600, p90 1200 vs 1100, p95/p99 1300 vs 1200), so
    an off-by-one in the rank cannot pass. ``n=100`` above cannot show this:
    ``q*n`` is a whole number there and ceil and floor agree.
    """
    sizes = [100 * i for i in range(1, 14)]
    calls = [make_call("pm_get", "s1", i, text="x" * size) for i, size in enumerate(sizes)]
    dist = rp.build_report(calls).tools["pm_get"].bytes_per_call

    assert dist.count == 13
    assert dist.total == 9100
    assert dist.minimum == 100
    assert dist.median == 700  # ceil(0.5*13) = 7 -> the 7th smallest
    assert dist.p90 == 1200  # ceil(0.9*13) = 12
    assert dist.p95 == 1300  # ceil(0.95*13) = 13
    assert dist.p99 == 1300  # ceil(0.99*13) = 13
    assert dist.maximum == 1300
    # Every reported percentile is a byte count that really occurred.
    for value in (dist.median, dist.p90, dist.p95, dist.p99, dist.maximum):
        assert value in sizes


def test_a_tool_whose_calls_are_all_unmatched_reports_zero_bytes_without_crashing():
    calls = [make_call("pm_update", "s1", i, with_result=False) for i in range(3)]
    report = rp.build_report(calls)

    usage = report.tools["pm_update"]
    assert usage.calls == 3
    assert usage.unmatched == 3
    assert usage.result_bytes == 0
    assert usage.mean_bytes == 0.0
    dist = usage.bytes_per_call
    assert dist.count == 0
    assert dist.median is None and dist.maximum is None
    assert report.total_bytes == 0
    assert report.bytes_per_call.count == 0

    payload = report.as_dict()
    assert payload["by_tool"][0]["byte_share"] == 0.0
    assert json.dumps(payload)
    assert "pm_update" in rp.format_usage_report(report)


def test_unmatched_calls_lower_the_per_call_mean_but_not_the_per_response_stats():
    """Deliberate: ``mean_bytes`` is per *call*, the distribution is per *response*."""
    calls = [
        make_call("pm_get", "s1", 0, text="x" * 100),
        make_call("pm_get", "s1", 1, with_result=False),
    ]
    usage = rp.build_report(calls).tools["pm_get"]

    assert usage.mean_bytes == 50.0
    assert usage.bytes_per_call.mean == 100.0
    assert usage.bytes_per_call.median == 100


def test_estimated_tokens_uses_chars_not_bytes():
    report = rp.build_report([make_call("pm_get", "s1", 0, text="é" * 400)])
    assert report.total_chars == 400
    assert report.total_bytes == 800
    assert report.estimated_tokens == 100


# ------------------------------------------------------ consecutive runs --


def test_reports_consecutive_run_lengths_per_tool():
    calls = sequence(
        "s1",
        ["pm_update", "pm_update", "pm_update", "pm_get", "pm_update", "pm_update"],
    )
    report = rp.build_report(calls)

    profile = report.tools["pm_update"].runs
    assert sorted(profile.lengths) == [2, 3]
    assert profile.runs == 2
    assert profile.longest == 3
    assert profile.calls_in_runs == 5
    assert profile.histogram == {2: 1, 3: 1}
    assert report.tools["pm_get"].runs.lengths == [1]


def test_run_length_one_is_recorded_so_the_histogram_has_a_denominator():
    report = rp.build_report(sequence("s1", ["pm_get", "pm_update", "pm_get"]))
    assert report.run_histogram() == {1: 3}
    assert report.tools["pm_get"].runs.runs == 2
    assert report.tools["pm_get"].runs.runs_at_least(2) == 0


def test_removable_calls_is_run_length_minus_one_per_run():
    # A 4-run and a 2-run: a bulk call would leave one call per run.
    calls = sequence(
        "s1", ["pm_update"] * 4 + ["pm_get"] + ["pm_update"] * 2
    )
    profile = rp.build_report(calls).tools["pm_update"].runs
    assert profile.calls_in_runs == 6
    assert profile.removable_calls == 4  # (4-1) + (2-1)
    assert profile.runs_at_least(3) == 1
    assert profile.calls_at_least(3) == 4


def test_longest_runs_are_reported_with_their_location():
    calls = sequence("s1", ["pm_update"] * 5 + ["pm_get"]) + sequence(
        "s2", ["pm_archive"] * 9
    )
    report = rp.build_report(calls)

    longest = report.longest_runs(2)
    assert [(r.tool, r.length) for r in longest] == [("pm_archive", 9), ("pm_update", 5)]
    assert longest[0].session == "s2"
    assert longest[0].start_seq == 0
    assert longest[0].end_seq == 8


def test_runs_follow_transcript_order_not_list_order():
    """``seq`` is the truth; a shuffled input list must not invent runs."""
    ordered = ["pm_update", "pm_get", "pm_update", "pm_update"]
    calls = sequence("s1", ordered)
    shuffled = [calls[3], calls[0], calls[2], calls[1]]

    profile = rp.build_report(shuffled).tools["pm_update"].runs
    assert sorted(profile.lengths) == [1, 2]
    assert profile.longest == 2


def test_runs_never_span_transcript_files():
    """Two transcripts of 3 ``pm_update`` each is 2 runs of 3, never one of 6."""
    calls = sequence("sess-a", ["pm_update"] * 3) + sequence("sess-b", ["pm_update"] * 3)
    report = rp.build_report(calls)

    profile = report.tools["pm_update"].runs
    assert profile.lengths == [3, 3]
    assert profile.longest == 3
    assert profile.runs == 2
    assert {r.session for r in report.runs} == {"sess-a", "sess-b"}
    assert all(r.length == 3 for r in report.runs)


def test_runs_do_not_span_files_that_share_a_session_id():
    """One ``sessionId`` across two transcripts is still two boundaries."""
    a = [make_call("pm_update", "file-1", i) for i in range(2)]
    b = [make_call("pm_update", "file-2", i) for i in range(2)]
    for call in a + b:
        call.session_id = "same-session-id"

    profile = rp.build_report(a + b).tools["pm_update"].runs
    assert profile.lengths == [2, 2]
    assert profile.longest == 2


def test_runs_are_maximal_a_run_of_five_is_not_also_runs_of_two_and_three():
    """Five in a row is exactly one run, not the 4+3+2 sub-runs inside it."""
    report = rp.build_report(sequence("s1", ["pm_update"] * 5))

    profile = report.tools["pm_update"].runs
    assert profile.lengths == [5]
    assert profile.runs == 1
    assert profile.histogram == {5: 1}
    assert profile.runs_at_least(2) == 1  # a sub-run counter would say 4
    assert profile.runs_at_least(3) == 1  # ...and 3 here
    assert profile.calls_at_least(2) == 5  # ...and 5+4+3+2 = 14 here
    assert profile.removable_calls == 4
    assert report.run_histogram() == {5: 1}
    assert len(report.runs) == 1
    assert (report.runs[0].start_seq, report.runs[0].end_seq) == (0, 4)


def test_run_length_histogram_sums_to_the_total_call_count():
    """Runs partition the calls: every call is in exactly one run."""
    calls = sequence("s1", ["pm_update"] * 3 + ["pm_get"] + ["pm_update"] * 2) + sequence(
        "s2", ["pm_grab", "pm_grab", "pm_get"]
    )
    report = rp.build_report(calls)

    histogram = report.run_histogram()
    assert histogram == {1: 2, 2: 2, 3: 1}
    assert sum(length * count for length, count in histogram.items()) == 9
    assert report.total_calls == 9
    assert sum(histogram.values()) == len(report.runs) == 5

    for usage in report.tools.values():
        assert usage.runs.calls_in_runs == usage.calls
        assert sum(n * c for n, c in usage.runs.histogram.items()) == usage.calls

    runs_payload = report.as_dict()["runs"]
    assert sum(int(n) * c for n, c in runs_payload["histogram"].items()) == 9
    assert runs_payload["total"] == sum(runs_payload["histogram"].values()) == 5


def test_removable_calls_arithmetic_a_run_of_n_implies_n_minus_one_avoidable():
    calls = sequence("s1", ["pm_update"] * 7 + ["pm_get"] + ["pm_update"] * 2) + sequence(
        "s2", ["pm_update"]
    )
    report = rp.build_report(calls)

    profile = report.tools["pm_update"].runs
    assert profile.lengths == [7, 2, 1]
    assert profile.removable_calls == (7 - 1) + (2 - 1) + (1 - 1) == 7
    assert profile.removable_calls == profile.calls_in_runs - profile.runs
    assert report.tools["pm_get"].runs.removable_calls == 0
    # Corpus-wide the same identity holds: one call per run is unavoidable.
    total_removable = sum(u.runs.removable_calls for u in report.tools.values())
    assert total_removable == report.total_calls - len(report.runs) == 7


def test_an_isolated_call_is_a_run_of_one():
    report = rp.build_report(sequence("s1", ["pm_get"]))

    profile = report.tools["pm_get"].runs
    assert profile.lengths == [1]
    assert profile.runs == 1
    assert profile.longest == 1
    assert profile.removable_calls == 0
    assert profile.runs_at_least(2) == 0
    assert report.run_histogram() == {1: 1}


def test_interleaving_a_b_a_yields_runs_of_one_not_a_run_of_two():
    """The two ``pm_update`` calls are not adjacent, so they are not a run."""
    report = rp.build_report(sequence("s1", ["pm_update", "pm_get", "pm_update"]))

    profile = report.tools["pm_update"].runs
    assert profile.lengths == [1, 1]
    assert profile.longest == 1
    assert profile.removable_calls == 0
    assert report.run_histogram() == {1: 3}
    assert len(report.runs) == 3


def test_run_boundaries_do_not_inflate_the_removable_count_across_files():
    """3 + 3 across two transcripts is 4 avoidable calls; one run of 6 would say 5."""
    calls = sequence("sess-a", ["pm_update"] * 3) + sequence("sess-b", ["pm_update"] * 3)
    profile = rp.build_report(calls).tools["pm_update"].runs

    assert profile.lengths == [3, 3]
    assert profile.longest == 3
    assert profile.removable_calls == 4


def test_unmatched_calls_still_break_and_form_runs():
    """Adjacency is about calls; a missing result does not erase the call."""
    calls = [
        make_call("pm_update", "s1", 0),
        make_call("pm_update", "s1", 1, with_result=False),
        make_call("pm_update", "s1", 2),
    ]
    assert rp.build_report(calls).tools["pm_update"].runs.lengths == [3]


# ------------------------------------------------------------- adjacency --


def test_reports_top_adjacency_bigrams():
    calls = sequence(
        "s1",
        ["pm_grab", "pm_update", "pm_update", "pm_get", "pm_update", "pm_update"],
    )
    report = rp.build_report(calls)

    assert report.bigrams[("pm_update", "pm_update")] == 2
    assert report.bigrams[("pm_grab", "pm_update")] == 1
    assert report.bigrams[("pm_update", "pm_get")] == 1
    assert report.bigrams[("pm_get", "pm_update")] == 1
    assert report.top_bigrams(1) == [("pm_update", "pm_update", 2)]
    assert sum(report.bigrams.values()) == len(calls) - 1


def test_bigrams_never_span_transcript_files():
    """``... -> pm_get | pm_update -> ...`` across files is not an adjacency."""
    calls = sequence("sess-a", ["pm_grab", "pm_get"]) + sequence(
        "sess-b", ["pm_update", "pm_audit"]
    )
    report = rp.build_report(calls)

    assert ("pm_get", "pm_update") not in report.bigrams
    assert report.bigrams == {
        ("pm_grab", "pm_get"): 1,
        ("pm_update", "pm_audit"): 1,
    }
    # n transcripts of length k give k-1 pairs each, never n*k-1.
    assert sum(report.bigrams.values()) == 2


def test_bigram_pairs_are_directional():
    calls = sequence("s1", ["pm_grab", "pm_update", "pm_grab"])
    report = rp.build_report(calls)
    assert report.bigrams[("pm_grab", "pm_update")] == 1
    assert report.bigrams[("pm_update", "pm_grab")] == 1


def test_a_single_call_transcript_contributes_no_bigrams():
    report = rp.build_report(sequence("s1", ["pm_update"]))
    assert report.bigrams == {}
    assert report.top_bigrams() == []


@pytest.mark.parametrize(
    "sessions",
    [
        {"s1": ["pm_update"]},
        {"s1": ["pm_update", "pm_get"]},
        {"s1": ["pm_update"] * 5, "s2": ["pm_get", "pm_update", "pm_get"]},
        {"s1": ["pm_a"], "s2": ["pm_b"], "s3": ["pm_c"]},
        {f"s{i}": ["pm_update", "pm_get", "pm_update"] for i in range(4)},
    ],
)
def test_bigram_total_is_always_calls_minus_transcripts(sessions):
    """The boundary invariant: k calls in a transcript give exactly k-1 pairs."""
    calls = [c for name, tools in sessions.items() for c in sequence(name, tools)]
    report = rp.build_report(calls)

    expected = report.total_calls - report.sessions
    assert sum(report.bigrams.values()) == expected
    assert sum(b["count"] for b in report.as_dict()["bigrams"]) == expected


def test_bigram_ordering_is_deterministic_for_equal_counts():
    calls = sequence("s1", ["pm_a", "pm_b", "pm_c", "pm_d"])
    first = rp.build_report(calls).top_bigrams()
    second = rp.build_report(list(reversed(calls))).top_bigrams()
    assert first == second == [("pm_a", "pm_b", 1), ("pm_b", "pm_c", 1), ("pm_c", "pm_d", 1)]


# ------------------------------------------------------- classify re-use --


def test_failures_come_from_the_classifier_not_a_second_definition():
    calls = [
        make_call("pm_update", "s1", 0, text=SOFT_NOTE_LIMIT),  # soft error
        make_call("pm_update", "s1", 1, text="boom", is_error=True),  # hard error
        make_call("pm_update", "s1", 2, text="ok"),
        make_call("pm_get", "s1", 3, text="ok"),
    ]
    report = rp.build_report(calls)

    assert report.tools["pm_update"].failures == 2
    assert report.tools["pm_get"].failures == 0
    assert report.classification is not None
    assert report.classification.failures == 2
    assert report.as_dict()["failures"]["rates"]["combined_failure_rate"] == 0.5


def test_a_supplied_classification_is_reused_rather_than_recomputed():
    calls = sequence("s1", ["pm_update", "pm_get"])
    classification = classify_all(calls)
    report = rp.build_report(calls, classification=classification)
    assert report.classification is classification


# ------------------------------------------------------------------ json --


def test_json_mode_is_a_complete_stable_structure():
    calls = sequence("s1", ["pm_grab", "pm_update", "pm_update"]) + sequence(
        "s2", ["pm_get"]
    )
    payload = rp.build_report(calls).as_dict()

    assert set(payload) >= {"corpus", "totals", "by_tool", "runs", "bigrams", "failures"}
    assert set(payload["totals"]) == {
        "calls",
        "matched",
        "unmatched",
        "sessions",
        "tools",
        "response_bytes",
        "response_chars",
        "estimated_tokens",
        "bytes_per_call",
        "calls_per_session",
    }
    row = payload["by_tool"][0]
    assert set(row) == {
        "tool",
        "calls",
        "call_share",
        "unmatched",
        "failures",
        "result_bytes",
        "byte_share",
        "result_chars",
        "bytes_per_call",
        "runs",
    }
    assert set(row["runs"]) == {
        "runs",
        "longest",
        "calls_in_runs",
        "runs_ge2",
        "calls_in_runs_ge2",
        "runs_ge3",
        "calls_in_runs_ge3",
        "removable_calls",
        "histogram",
    }
    assert payload["bigrams"] == [
        {"from": "pm_grab", "to": "pm_update", "count": 1},
        {"from": "pm_update", "to": "pm_update", "count": 1},
    ]
    assert payload["totals"]["sessions"] == 2


def test_json_mode_is_serialisable_and_round_trips():
    calls = sequence("s1", ["pm_grab", "pm_update"]) + sequence("s2", ["pm_get"])
    payload = rp.build_report(calls).as_dict()
    assert json.loads(json.dumps(payload)) == payload


def test_json_bigram_list_is_not_truncated_by_the_display_limit():
    tools = [f"pm_t{i}" for i in range(40)]
    report = rp.build_report(sequence("s1", tools))
    assert len(report.bigrams) == 39
    assert len(report.as_dict()["bigrams"]) == 39
    assert len(rp.format_usage_report(report, top=5).splitlines()) < 120


def test_json_run_histograms_are_complete_per_tool():
    calls = sequence("s1", ["pm_update"] * 3 + ["pm_get"] + ["pm_update"] * 2)
    payload = rp.build_report(calls).as_dict()
    row = next(r for r in payload["by_tool"] if r["tool"] == "pm_update")
    assert row["runs"]["histogram"] == {"2": 1, "3": 1}
    assert payload["runs"]["histogram"] == {"1": 1, "2": 1, "3": 1}
    assert payload["runs"]["total"] == 3


def test_empty_corpus_produces_a_valid_empty_report():
    report = rp.build_report([])
    payload = report.as_dict()
    assert payload["totals"]["calls"] == 0
    assert payload["totals"]["response_bytes"] == 0
    assert payload["totals"]["bytes_per_call"]["median"] is None
    assert payload["by_tool"] == []
    assert payload["bigrams"] == []
    assert json.dumps(payload)
    assert "calls" in rp.format_usage_report(report)


# ------------------------------------------------------------------- cli --


def test_cli_text_report_names_every_required_metric(corpus, capsys):
    assert rp.main(["--root", str(corpus)]) == 0
    out = capsys.readouterr().out

    assert "response bytes" in out
    assert "bytes per call" in out
    assert "median" in out and "p90" in out and "p95" in out
    assert "consecutive runs" in out
    assert "run-length histogram" in out
    assert "adjacency bigrams" in out
    assert "pm_grab" in out and "pm_update" in out


def test_cli_json_report_matches_the_api(corpus, capsys):
    assert rp.main(["--root", str(corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["totals"]["calls"] == 5
    assert payload["totals"]["sessions"] == 2
    assert payload["corpus"]["match_rate"] == 1.0
    by_tool = {row["tool"]: row for row in payload["by_tool"]}
    assert by_tool["pm_grab"]["result_bytes"] == 5000
    assert by_tool["pm_update"]["calls"] == 3
    assert by_tool["pm_get"]["result_bytes"] == 6  # "héllo"
    assert payload["totals"]["response_bytes"] == 5000 + 2 + len(SOFT_NOTE_LIMIT) + 2 + 6


def test_cli_json_respects_transcript_boundaries_on_a_real_corpus(corpus, capsys):
    """sess-a ends with pm_update and sess-b starts with one: still 2 + 1."""
    assert rp.main(["--root", str(corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    update = next(r for r in payload["by_tool"] if r["tool"] == "pm_update")
    assert update["runs"]["longest"] == 2
    assert update["runs"]["histogram"] == {"1": 1, "2": 1}

    bigrams = {(b["from"], b["to"]): b["count"] for b in payload["bigrams"]}
    assert bigrams[("pm_update", "pm_update")] == 1
    assert ("pm_update", "pm_get") in bigrams  # inside sess-b only
    assert sum(bigrams.values()) == 3  # 2 pairs in sess-a + 1 in sess-b


def test_cli_bigram_total_is_calls_minus_transcripts_on_a_scanned_corpus(corpus, capsys):
    assert rp.main(["--root", str(corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    total = payload["totals"]["calls"] - payload["totals"]["sessions"]
    assert sum(b["count"] for b in payload["bigrams"]) == total == 3


def test_all_three_metrics_hold_together_on_a_scanned_corpus(tmp_path, capsys):
    """One end-to-end check of counts, bytes and runs through the real scan path.

    ``pm_update`` spans both transcripts and has a maximal run of 4 in the first
    and a run of 2 in the second -- never a run of 7.
    """
    root = tmp_path / "projects"
    records_a = []
    for i, tool in enumerate(["pm_update"] * 4 + ["pm_get"] + ["pm_update"]):
        uid = f"a{i}"
        body = "héllo" if tool == "pm_get" else "ok"
        records_a.append(_record([_tool_use(uid, f"mcp__projectman__{tool}")]))
        records_a.append(_record([_tool_result(uid, body)]))
    _write_transcript(root, "proj-1", "sess-1", records_a)

    records_b = []
    for i in range(2):
        uid = f"b{i}"
        records_b.append(_record([_tool_use(uid, "mcp__projectman__pm_update")], "s2"))
        records_b.append(_record([_tool_result(uid, "ok")], "s2"))
    _write_transcript(root, "proj-2", "sess-2", records_b)

    assert rp.main(["--root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_tool = {row["tool"]: row for row in payload["by_tool"]}

    # 1. per-tool call counts, aggregated across both transcripts, summing exactly
    assert payload["totals"]["calls"] == 8
    assert payload["totals"]["sessions"] == 2
    assert by_tool["pm_update"]["calls"] == 7  # 4 + 1 in sess-1, 2 in sess-2
    assert by_tool["pm_get"]["calls"] == 1
    assert sum(row["calls"] for row in payload["by_tool"]) == 8

    # 2. response bytes, UTF-8, summing exactly
    assert by_tool["pm_update"]["result_bytes"] == 14  # 7 x "ok"
    assert by_tool["pm_get"]["result_bytes"] == 6  # "héllo" is 5 chars, 6 bytes
    assert by_tool["pm_get"]["result_chars"] == 5
    assert payload["totals"]["response_bytes"] == 20
    assert sum(row["result_bytes"] for row in payload["by_tool"]) == 20

    # 3. consecutive runs: maximal, per transcript, with the right arithmetic
    runs = by_tool["pm_update"]["runs"]
    assert runs["longest"] == 4
    assert runs["histogram"] == {"1": 1, "2": 1, "4": 1}
    assert runs["runs"] == 3
    assert runs["removable_calls"] == 3 + 0 + 1 == 4
    assert payload["runs"]["histogram"] == {"1": 2, "2": 1, "4": 1}
    assert sum(int(n) * c for n, c in payload["runs"]["histogram"].items()) == 8

    # and the boundary invariant
    assert sum(b["count"] for b in payload["bigrams"]) == 8 - 2 == 6


def test_cli_out_flag_writes_the_full_json(corpus, tmp_path, capsys):
    out = tmp_path / "nested" / "baseline.json"
    assert rp.main(["--root", str(corpus), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["totals"]["calls"] == 5
    assert "wrote JSON report" in capsys.readouterr().err


def test_cli_errors_when_no_projectman_calls_are_found(tmp_path, capsys):
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [_record([_tool_use("t1", "Bash", {"command": "ls"})])],
    )
    assert rp.main(["--root", str(root)]) == 2
    assert "no mcp__projectman__* calls" in capsys.readouterr().err


def test_cli_min_match_rate_guard_fires_before_reporting(tmp_path, capsys):
    """A bad join exits 1 (distinct from exit 2, an empty corpus) and reports nothing."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [_record([_tool_use("t1", "mcp__projectman__pm_update")])],  # no result
    )
    assert rp.main(["--root", str(root), "--min-match-rate", "0.99", "--json"]) == 1
    captured = capsys.readouterr()
    assert "match rate" in captured.err
    assert captured.out == ""  # no numbers built on a partial join


def test_cli_empty_prefix_reports_every_tool(corpus, capsys):
    assert rp.main(["--root", str(corpus), "--prefix", "", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["calls"] == 5  # this corpus is all ProjectMan


def test_module_entrypoint_runs_as_a_script(corpus):
    proc = subprocess.run(
        [sys.executable, "-m", "tools.usage_telemetry.report", "--root", str(corpus), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["totals"]["calls"] == 5


# --------------------------------------------------------------- packaging --


def test_package_exports_the_report_api_lazily():
    assert tx_pkg.build_report is rp.build_report
    assert tx_pkg.percentile is rp.percentile
    assert tx_pkg.UsageReport is rp.UsageReport
    # ``report`` resolves to the module, never to a function inside it.
    assert tx_pkg.report is rp
    assert "report" in dir(tx_pkg)
    with pytest.raises(AttributeError):
        tx_pkg.no_such_report_name


# ------------------------------------------- completion run-log coverage --
#
# US-PM-8 AC: "Measured share of completions lacking a run-log entry drops to
# zero." Before there was a metric there was only an assertion, so these pin
# the definition: what counts as a completion, and what counts as logged.


def _done(note=None, outcome=None, seq=0, session="sess-a"):
    """A ``pm_update(status="done")`` completion, bare unless given args."""
    args = {"id": "US-TST-1-1", "status": "done"}
    if note is not None:
        args["note"] = note
    if outcome is not None:
        args["outcome"] = outcome
    return make_call(tool="pm_update", session=session, seq=seq, tool_input=args)


def test_two_bare_done_writes_in_ten_completions_is_a_twenty_percent_gap():
    """The shape of the pre-fix corpus, shrunk: 2 of 10 carry nothing."""
    calls = [
        _done(seq=0),
        _done(seq=1),
        _done(note="finished the parser", outcome="success", seq=2),
        _done(outcome="success", seq=3),
        _done(note="tests green", seq=4),
        make_call(tool="pm_done_next", seq=5, tool_input={"task_id": "US-TST-1-2"}),
        make_call(
            tool="pm_done_next", seq=6, tool_input={"task_id": "US-TST-1-3", "note": "ok"}
        ),
        make_call(
            tool="pm_accept", seq=7, tool_input={"task_id": "US-TST-1-4", "note": "ok"}
        ),
        make_call(
            tool="pm_accept", seq=8, tool_input={"task_id": "US-TST-1-5", "note": "ok"}
        ),
        make_call(tool="pm_done_next", seq=9, tool_input={"task_id": "US-TST-1-6"}),
    ]
    summary = rp.completion_logging(calls)
    assert summary.completions == 10
    assert summary.without_run_log == 2
    assert summary.with_run_log == 8
    assert summary.without_run_log_rate == pytest.approx(0.20)
    assert 100 * summary.without_run_log_rate == pytest.approx(20.0)


def test_a_corpus_of_only_verbs_and_done_next_reports_zero():
    """The post-fix shape: the server logs regardless, so the share is 0."""
    calls = [
        make_call(tool="pm_accept", seq=0, tool_input={"task_id": "A", "note": "n"}),
        make_call(tool="pm_done_next", seq=1, tool_input={"task_id": "B"}),
        make_call(tool="pm_done_next", seq=2, tool_input={"task_id": "C", "note": ""}),
        make_call(tool="pm_accept", seq=3, tool_input={"task_id": "D", "note": "n"}),
    ]
    summary = rp.completion_logging(calls)
    assert summary.completions == 4
    assert summary.without_run_log == 0
    assert summary.without_run_log_rate == 0.0


def test_only_done_updates_count_as_completions():
    """A status edit that is not a completion must not dilute the denominator."""
    calls = [
        make_call(tool="pm_update", seq=0, tool_input={"id": "X", "status": "active"}),
        make_call(tool="pm_update", seq=1, tool_input={"id": "X", "points": 3}),
        make_call(tool="pm_get", seq=2, tool_input={"id": "X"}),
        _done(seq=3),
    ]
    summary = rp.completion_logging(calls)
    assert summary.completions == 1
    assert summary.without_run_log == 1
    assert summary.without_run_log_rate == 1.0


def test_a_blank_note_on_a_done_update_is_not_a_run_log_entry():
    """Whitespace is not a note; the server writes nothing for it either."""
    assert rp.completion_logging([_done(note="   ", seq=0)]).without_run_log == 1
    assert rp.completion_logging([_done(note="x", seq=0)]).without_run_log == 0


def test_an_unparsable_update_is_not_guessed_to_be_a_completion():
    """No readable ``status``, so its intent is unknown -- it is left out."""
    calls = [make_call(tool="pm_update", seq=0, tool_input={"__unparsedToolInput": "{"})]
    assert rp.completion_logging(calls).completions == 0


def test_an_empty_corpus_rates_zero_rather_than_dividing_by_zero():
    assert rp.completion_logging([]).without_run_log_rate == 0.0


def test_the_completion_metric_is_surfaced_in_the_json_report():
    report = rp.build_report([_done(seq=0), _done(note="n", seq=1)])
    section = report.as_dict()["completions"]
    assert section["completions"] == 2
    assert section["without_run_log"] == 1
    assert section["completions_without_run_log_rate"] == pytest.approx(0.5)
    assert section["by_tool"]["pm_update"] == {"completions": 2, "without_run_log": 1}


def test_the_completion_metric_is_surfaced_in_the_text_report():
    text = rp.format_usage_report(rp.build_report([_done(seq=0), _done(note="n", seq=1)]))
    assert "completions" in text
    assert "no run-log entry" in text
    assert "50.00%" in text


# ------------------------------------------------------- note length --
#
# US-PM-9 AC: "Median note length drops well below the cap." The metric has to
# be right on a hand-computable sample before any claim about the live corpus
# means anything, so these pin the sampling rule and the percentile arithmetic.


def _noted(chars=None, seq=0, tool="pm_update", session="sess-a", note=None):
    """A call carrying a ``note`` of ``chars`` characters (or none at all)."""
    args = {"id": "US-TST-1-1", "status": "done"}
    if chars is not None:
        args["note"] = "n" * chars
    if note is not None:
        args["note"] = note
    return make_call(tool=tool, session=session, seq=seq, tool_input=args)


def test_note_lengths_are_hand_computable_on_a_three_note_corpus():
    """100/200/900 -> median 200, and nearest-rank puts p90 and p95 at 900."""
    calls = [_noted(100, seq=0), _noted(200, seq=1), _noted(900, seq=2)]
    dist = rp.note_lengths(calls)
    assert dist.count == 3
    assert dist.total == 1200
    assert dist.median == 200
    assert dist.p90 == 900
    assert dist.p95 == 900
    assert dist.minimum == 100
    assert dist.maximum == 900


def test_calls_with_no_note_argument_are_not_sampled():
    """A `pm_get` is not a zero-length note; it is not a note at all."""
    calls = [
        _noted(200, seq=0),
        make_call(tool="pm_get", seq=1, tool_input={"id": "US-TST-1-1"}),
        make_call(tool="pm_update", seq=2, tool_input={"id": "X", "status": "active"}),
        _noted(200, seq=3),
    ]
    assert rp.note_lengths(calls).count == 2


def test_a_non_string_note_is_skipped_rather_than_guessed_at():
    calls = [
        make_call(tool="pm_update", seq=0, tool_input={"id": "X", "note": None}),
        make_call(tool="pm_update", seq=1, tool_input={"__unparsedToolInput": "{"}),
        make_call(tool="pm_update", seq=2, tool_input={"id": "X", "note": 12}),
    ]
    assert rp.note_lengths(calls).count == 0


def test_an_empty_note_is_still_a_note_the_caller_wrote():
    assert rp.note_lengths([_noted(note="", seq=0)]).count == 1
    assert rp.note_lengths([_noted(note="", seq=0)]).total == 0


def test_notes_are_sampled_from_every_tool_not_only_completions():
    """The metric is about the prose habit, so a verdict verb counts too."""
    calls = [
        make_call(tool="pm_accept", seq=0, tool_input={"task_id": "A", "note": "x" * 50}),
        make_call(tool="pm_review", seq=1, tool_input={"task_id": "B", "note": "x" * 50}),
        make_call(tool="pm_park", seq=2, tool_input={"task_id": "C", "note": "x" * 50}),
    ]
    assert rp.note_lengths(calls).count == 3
    assert rp.note_lengths(calls).median == 50


def test_an_empty_note_corpus_is_zeros_rather_than_a_crash():
    """Count and total are zero; the percentiles are ``None`` per Distribution.

    ``Distribution`` documents an empty sample as ``None`` quantiles rather than
    a misleading zero median, and the note metric must not invent a different
    convention for itself.
    """
    dist = rp.note_lengths([])
    assert dist.count == 0
    assert dist.total == 0
    assert dist.median is None and dist.p90 is None and dist.p95 is None
    assert dist.as_dict()["median"] is None


def test_the_note_length_metric_is_surfaced_in_the_json_report():
    report = rp.build_report([_noted(100, seq=0), _noted(200, seq=1), _noted(900, seq=2)])
    section = report.as_dict()["note_lengths"]
    assert section["count"] == 3
    assert section["median"] == 200
    assert section["p90"] == 900
    assert section["p95"] == 900
    assert json.loads(json.dumps(section)) == section


def test_the_note_length_metric_is_surfaced_in_the_text_report():
    text = rp.format_usage_report(rp.build_report([_noted(100, seq=0), _noted(300, seq=1)]))
    assert "note lengths" in text
    assert "median 100" in text
    assert str(rp.NOTE_LENGTH_CAP) in text.replace(",", "")


# ------------------------------------------------------ guidance-tool usage --
#
# US-PM-13 AC: "Usage of both tools is visible in the next telemetry baseline."
# `pm_context` and `pm_estimate` sat at 1 call each in the pre-fix capture while
# `pm_scope` -- the same shape of tool -- took 40. The metric that makes the
# movement visible has to print a zero as a zero: an absent row is
# indistinguishable from a tool nobody thought to measure.


def _guidance_corpus():
    """Three sessions; `pm_estimate` called in one of them, `pm_context` in none."""
    return (
        sequence("s1", ["pm_grab", "pm_estimate", "pm_update"])
        + sequence("s2", ["pm_grab", "pm_update"])
        + sequence("s3", ["pm_get"])
    )


def test_guidance_usage_counts_calls_and_the_sessions_that_made_them():
    usage = rp.guidance_tool_usage(_guidance_corpus())
    assert usage.sessions == 3
    assert usage.calls["pm_estimate"] == 1
    assert usage.tool_sessions["pm_estimate"] == 1


def test_an_uncalled_guidance_tool_reports_a_visible_zero_not_an_absent_row():
    """The whole point of the metric: the "before" number is a printed zero."""
    usage = rp.guidance_tool_usage(_guidance_corpus())
    assert "pm_context" in usage.as_dict()["by_tool"]
    assert usage.calls["pm_context"] == 0
    assert usage.session_rate("pm_context") == 0.0
    assert usage.calls_per_100_sessions("pm_context") == 0.0


def test_repeat_calls_in_one_session_count_once_towards_reach():
    """Eight calls from one agent is not eight sessions consulting the guidance."""
    calls = sequence("s1", ["pm_context"] * 8) + sequence("s2", ["pm_get"])
    usage = rp.guidance_tool_usage(calls)
    assert usage.calls["pm_context"] == 8
    assert usage.tool_sessions["pm_context"] == 1
    assert usage.session_rate("pm_context") == pytest.approx(0.5)


def test_sessions_that_never_touch_a_guidance_tool_stay_in_the_denominator():
    """"What share of working sessions consulted the guidance" needs all of them."""
    usage = rp.guidance_tool_usage(_guidance_corpus())
    assert usage.sessions == 3
    assert usage.session_rate("pm_estimate") == pytest.approx(1 / 3)


def test_calls_per_100_sessions_normalises_across_corpus_sizes():
    """2 calls in 4 sessions is heavier usage than 40 in 484 -- the raw counts lie."""
    small = rp.guidance_tool_usage(
        sequence("s1", ["pm_scope", "pm_scope"])
        + sequence("s2", ["pm_get"])
        + sequence("s3", ["pm_get"])
        + sequence("s4", ["pm_get"])
    )
    assert small.calls_per_100_sessions("pm_scope") == 50.0


def test_the_guidance_metric_is_surfaced_in_the_json_report():
    section = rp.build_report(_guidance_corpus()).as_dict()["guidance_tools"]
    assert section["sessions"] == 3
    assert set(section["by_tool"]) == set(rp.GUIDANCE_TOOLS)
    assert section["by_tool"]["pm_estimate"] == {
        "calls": 1,
        "sessions": 1,
        "session_rate": pytest.approx(1 / 3),
        "calls_per_100_sessions": 33.3333,
    }
    assert section["by_tool"]["pm_context"]["calls"] == 0


def test_the_guidance_metric_is_surfaced_in_the_text_report():
    text = rp.format_usage_report(rp.build_report(_guidance_corpus()))
    assert "pm_context" in text
    assert "pm_estimate" in text
    assert text.count("guidance tool") == len(rp.GUIDANCE_TOOLS)


def test_an_empty_corpus_reports_zeros_rather_than_dividing_by_zero():
    usage = rp.guidance_tool_usage([])
    assert usage.sessions == 0
    assert usage.session_rate("pm_context") == 0.0
    assert usage.calls_per_100_sessions("pm_context") == 0.0
    payload = rp.build_report([]).as_dict()["guidance_tools"]
    assert set(payload["by_tool"]) == set(rp.GUIDANCE_TOOLS)
    assert json.dumps(payload)


def test_the_telemetry_guidance_set_matches_the_set_the_skills_pin():
    """The metric must not measure a different set from the one the skills name.

    ``tests/test_skill_guidance_tools.py`` derives its tuple from the live
    server's read-only advisory tools and asserts every skill step names them;
    this metric is what proves the steps moved the number. If the two sets ever
    diverge, the telemetry silently measures something the sprint did not wire.
    """
    from tests.test_skill_guidance_tools import GUIDANCE_TOOLS as SKILL_GUIDANCE_TOOLS

    assert set(rp.GUIDANCE_TOOLS) == set(SKILL_GUIDANCE_TOOLS)
