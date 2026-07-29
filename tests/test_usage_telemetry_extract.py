"""Tests for the usage-telemetry extraction pass (US-PM-6-6).

Covers story ACs 1 (walk transcripts, join calls to results by tool_use_id) and
4 (match rate is asserted and the run fails loudly below 99%).
"""

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.usage_telemetry as tx_pkg
from tools.usage_telemetry import extract as tx


def _record(content, session="sess-a", timestamp="2026-07-29T00:00:00Z", **extra):
    rec = {
        "type": "assistant",
        "sessionId": session,
        "timestamp": timestamp,
        "message": {"content": content},
    }
    rec.update(extra)
    return rec


def _tool_use(tool_use_id, name="mcp__projectman__pm_update", tool_input=None):
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
    """A small transcript corpus with a 100% joinable ProjectMan call set."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "-home-ryan-Repo-ProjectMan",
        "sess-a",
        [
            _record([_tool_use("t1", "mcp__projectman__pm_grab", {"task_id": "US-X-1"})]),
            _record([_tool_result("t1", "grabbed: ...")]),
            # A non-ProjectMan call: must not appear in calls, but its result
            # still gets collected (the collector is unfiltered by design).
            _record([_tool_use("t2", "Bash", {"command": "ls"})]),
            _record([_tool_result("t2", "file listing")]),
            _record(
                [_tool_use("t3", "mcp__projectman__pm_update", {"id": "US-X-1", "status": "done"})]
            ),
            _record([_tool_result("t3", "error: boom", is_error=True)]),
        ],
    )
    _write_transcript(
        root,
        "-home-ryan-Repo-Other",
        "sess-b",
        [
            _record(
                [_tool_use("t4", "mcp__projectman__pm_get", {"id": "US-Y-1"})],
                session="sess-b",
            ),
            # List-shaped result body.
            _record(
                [_tool_result("t4", [{"type": "text", "text": "part1 "}, {"type": "text", "text": "part2"}])],
                session="sess-b",
            ),
        ],
    )
    return root


def test_walks_transcripts_and_joins_by_tool_use_id(corpus):
    ex = tx.scan(root=corpus)

    assert ex.stats.files_scanned == 2
    # Files are walked in sorted path order: "-home-ryan-Repo-Other" first.
    assert [c.tool_use_id for c in ex.calls] == ["t4", "t1", "t3"]
    assert [c.tool for c in ex.calls] == ["pm_get", "pm_grab", "pm_update"]
    assert ex.match_rate == 1.0
    assert ex.unmatched_calls == []

    by_id = {c.tool_use_id: c for c in ex.calls}
    assert by_id["t1"].result.text == "grabbed: ..."
    assert by_id["t3"].result.is_error is True
    # List-shaped bodies are concatenated.
    assert by_id["t4"].result.text == "part1 part2"


def test_result_collector_is_not_prefiltered_by_tool_name(corpus):
    """The documented trap: results never contain the string 'projectman'."""
    ex = tx.scan(root=corpus)

    # Every tool_result in the corpus is collected, including the Bash one.
    assert set(ex.results) == {"t1", "t2", "t3", "t4"}
    assert ex.stats.tool_result_blocks_total == 4
    assert ex.stats.tool_use_blocks_total == 4  # all tools counted
    # ...and none of the result payloads mention the tool name at all.
    for res in ex.results.values():
        assert "projectman" not in res.text


def test_preserves_fields_needed_by_later_passes(corpus):
    ex = tx.scan(root=corpus)
    by_id = {c.tool_use_id: c for c in ex.calls}

    assert by_id["t3"].input == {"id": "US-X-1", "status": "done"}
    assert by_id["t1"].project == "-home-ryan-Repo-ProjectMan"
    assert by_id["t1"].session == "sess-a"
    assert by_id["t1"].session_id == "sess-a"
    assert by_id["t1"].timestamp == "2026-07-29T00:00:00Z"
    assert by_id["t1"].result.bytes == len(b"grabbed: ...")

    grouped = ex.calls_by_session()
    assert [c.tool for c in grouped["sess-a"]] == ["pm_grab", "pm_update"]
    assert [c.seq for c in grouped["sess-a"]] == [0, 1]
    assert [c.tool for c in grouped["sess-b"]] == ["pm_get"]


def test_sequence_is_per_transcript_not_per_session_id(tmp_path):
    """One sessionId can span several transcript files (resume, subagents).

    Ordering must follow the file, otherwise unrelated files get interleaved
    and consecutive-run analysis invents adjacencies that never happened.
    """
    root = tmp_path / "projects"
    shared = "shared-session-id"
    for stem in ("a-transcript", "b-transcript"):
        _write_transcript(
            root,
            "proj",
            stem,
            [
                _record([_tool_use("x-" + stem), _tool_use("y-" + stem)], session=shared),
                _record(
                    [_tool_result("x-" + stem), _tool_result("y-" + stem)], session=shared
                ),
            ],
        )
    ex = tx.scan(root=root)

    assert ex.session_ids == {shared}
    assert ex.sessions == {"a-transcript", "b-transcript"}
    grouped = ex.calls_by_session()
    assert sorted(grouped) == ["a-transcript", "b-transcript"]
    for stem, calls in grouped.items():
        assert [c.seq for c in calls] == [0, 1]
        assert all(c.session_id == shared for c in calls)


def test_malformed_input_key_survives_extraction(tmp_path):
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record(
                [
                    _tool_use(
                        "m1",
                        "mcp__projectman__pm_update",
                        {"__unparsedToolInput": '{"id": "US-X-1", "assignee": }'},
                    )
                ]
            ),
            _record([_tool_result("m1", "error: bad input", is_error=True)]),
        ],
    )
    ex = tx.scan(root=root)
    assert "__unparsedToolInput" in ex.calls[0].input


def test_bad_json_and_odd_shapes_are_counted_not_fatal(tmp_path):
    root = tmp_path / "projects"
    path = root / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "{not json",
                "",
                json.dumps({"type": "summary", "message": {"content": "plain string"}}),
                json.dumps(_record([_tool_use("t1"), "not-a-dict"])),
                json.dumps(_record([_tool_result("t1")])),
            ]
        )
        + "\n"
    )
    ex = tx.scan(root=root)
    assert ex.stats.json_parse_failures == 1
    assert ex.stats.blank_lines == 1
    assert ex.total_calls == 1
    assert ex.match_rate == 1.0


def test_missing_root_yields_empty_extraction(tmp_path):
    ex = tx.scan(root=tmp_path / "nope")
    assert ex.stats.files_scanned == 0
    assert ex.total_calls == 0
    assert ex.match_rate == 1.0  # vacuous


def test_match_rate_below_threshold_raises(tmp_path):
    root = tmp_path / "projects"
    # 3 calls, 2 results -> 66.7%
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("a"), _tool_use("b"), _tool_use("c")]),
            _record([_tool_result("a"), _tool_result("b")]),
        ],
    )
    ex = tx.scan(root=root)
    assert ex.match_rate == pytest.approx(2 / 3)
    assert [c.tool_use_id for c in ex.unmatched_calls] == ["c"]

    with pytest.raises(tx.MatchRateError) as exc:
        ex.assert_match_rate(0.99)
    assert "match rate" in str(exc.value)

    # scan() can enforce the threshold inline too.
    with pytest.raises(tx.MatchRateError):
        tx.scan(root=root, min_match_rate=0.99)

    # A lower bar passes and returns the rate.
    assert ex.assert_match_rate(0.5) == pytest.approx(2 / 3)


def test_match_rate_just_below_99_percent_fails(tmp_path):
    """198 of 200 matched = 99.0% passes; 197 of 200 = 98.5% fails."""
    root = tmp_path / "projects"
    calls = [_tool_use(f"x{i}") for i in range(200)]
    results = [_tool_result(f"x{i}") for i in range(198)]
    _write_transcript(root, "proj", "sess", [_record(calls), _record(results)])
    ex = tx.scan(root=root)
    assert ex.match_rate == pytest.approx(0.99)
    assert ex.assert_match_rate(tx.DEFAULT_MIN_MATCH_RATE) == pytest.approx(0.99)

    _write_transcript(root, "proj", "sess", [_record(calls), _record(results[:197])])
    ex2 = tx.scan(root=root)
    with pytest.raises(tx.MatchRateError):
        ex2.assert_match_rate(tx.DEFAULT_MIN_MATCH_RATE)


def test_cli_exits_nonzero_on_low_match_rate(tmp_path, capsys):
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [_record([_tool_use("a"), _tool_use("b")]), _record([_tool_result("a")])],
    )
    rc = tx.main(["--root", str(root)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "match rate" in err
    assert "unmatched b" in err


def test_cli_success_writes_jsonl(corpus, tmp_path, capsys):
    out = tmp_path / "nested" / "pm_calls.jsonl"
    rc = tx.main(["--root", str(corpus), "--out", str(out), "--preview-chars", "4"])
    assert rc == 0

    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["tool_use_id"] for r in records] == ["t4", "t1", "t3"]
    first = records[1]
    assert first["tool"] == "pm_grab"
    assert first["matched"] is True
    assert first["result_text"] == "grab"  # truncated to preview
    assert first["result_chars"] == len("grabbed: ...")  # counted on full body
    assert first["result_truncated"] is True
    assert records[2]["is_error"] is True

    out_text = capsys.readouterr().out
    assert "100.00%" in out_text


def test_cli_json_summary(corpus, capsys):
    rc = tx.main(["--root", str(corpus), "--json"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["calls"] == 3
    assert summary["matched"] == 3
    assert summary["match_rate"] == 1.0
    assert summary["tool_result_blocks_total"] == 4
    assert summary["files_scanned"] == 2


def test_cli_errors_when_corpus_is_empty(tmp_path, capsys):
    assert tx.main(["--root", str(tmp_path / "missing")]) == 2
    assert "no transcripts found" in capsys.readouterr().err


def test_empty_prefix_extracts_every_tool(corpus):
    ex = tx.scan(root=corpus, tool_prefix="")
    assert [c.tool for c in ex.calls] == ["pm_get", "pm_grab", "Bash", "pm_update"]
    assert ex.match_rate == 1.0


def test_default_root_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(tmp_path))
    assert tx.default_transcript_root() == tmp_path
    monkeypatch.delenv("CLAUDE_PROJECTS_DIR")
    assert tx.default_transcript_root().name == "projects"


# ---------------------------------------------------------------------------
# AC 1, part one: "walks Claude Code transcripts"
#
# The walk itself is a correctness surface, not plumbing: a walk that misses
# nested subagent transcripts, or that swallows a *.json sidecar as if it were
# a transcript, changes every downstream number without failing anything.
# ---------------------------------------------------------------------------


def test_walk_recurses_into_nested_transcript_directories(tmp_path):
    """Transcripts are not all one level down (subagents, resumed sessions)."""
    root = tmp_path / "projects"
    _write_transcript(root, "proj", "top", [_record([_tool_use("a")]), _record([_tool_result("a")])])
    _write_transcript(
        root, "proj/sub", "mid", [_record([_tool_use("b")]), _record([_tool_result("b")])]
    )
    _write_transcript(
        root,
        "proj/sub/deeper",
        "leaf",
        [_record([_tool_use("c")]), _record([_tool_result("c")])],
    )

    ex = tx.scan(root=root)

    assert ex.stats.files_scanned == 3
    assert sorted(c.tool_use_id for c in ex.calls) == ["a", "b", "c"]
    assert ex.match_rate == 1.0
    # The project is the first component under the root at every depth, so
    # nested transcripts are still attributed to the project they belong to.
    assert ex.projects == {"proj"}
    # ...while the transcript file stem remains the ordering unit.
    assert ex.sessions == {"top", "mid", "leaf"}


def test_walk_ignores_non_jsonl_files_and_jsonl_named_directories(tmp_path):
    """Only ``*.jsonl`` *files* are transcripts."""
    root = tmp_path / "projects"
    _write_transcript(root, "proj", "real", [_record([_tool_use("a")]), _record([_tool_result("a")])])

    decoy = _record([_tool_use("decoy"), _tool_result("decoy")])
    for name in ("notes.json", "sess.jsonl.bak", "sess.txt", "README.md"):
        (root / "proj" / name).write_text(json.dumps(decoy) + "\n")
    # A directory whose name ends in .jsonl matches rglob but is not a file.
    (root / "proj" / "archive.jsonl").mkdir()

    ex = tx.scan(root=root)

    assert ex.stats.files_scanned == 1
    assert [c.tool_use_id for c in ex.calls] == ["a"]
    assert "decoy" not in ex.results


def test_walk_order_is_sorted_and_stable_across_scans(tmp_path):
    """Sequence numbers are assigned in read order, so the walk must be stable."""
    root = tmp_path / "projects"
    for project, stem in (("z-proj", "s1"), ("a-proj", "s2"), ("m-proj", "s3")):
        _write_transcript(
            root,
            project,
            stem,
            [_record([_tool_use(f"{project}-1")]), _record([_tool_result(f"{project}-1")])],
        )

    walked = tx.iter_transcript_files(root)
    assert walked == sorted(walked)
    assert [p.parent.name for p in walked] == ["a-proj", "m-proj", "z-proj"]

    first = [c.tool_use_id for c in tx.scan(root=root).calls]
    second = [c.tool_use_id for c in tx.scan(root=root).calls]
    assert first == second == ["a-proj-1", "m-proj-1", "z-proj-1"]


def test_walk_survives_an_unreadable_transcript(tmp_path):
    """One bad file must not abort the corpus scan."""
    root = tmp_path / "projects"
    good = _write_transcript(
        root, "proj", "good", [_record([_tool_use("a")]), _record([_tool_result("a")])]
    )
    bad = _write_transcript(root, "proj", "bad", [_record([_tool_use("b")])])
    bad.chmod(0o000)
    if os.access(bad, os.R_OK):  # pragma: no cover - running as root
        pytest.skip("cannot make a file unreadable as this user")
    try:
        ex = tx.scan(root=root)
    finally:
        bad.chmod(0o644)

    assert ex.stats.files_scanned == 2
    assert ex.stats.files_unreadable == 1
    assert [c.tool_use_id for c in ex.calls] == ["a"]
    assert [c.source_file for c in ex.calls] == [str(good)]
    assert ex.match_rate == 1.0


def test_malformed_lines_are_skipped_without_losing_neighbours(tmp_path):
    """A truncated/garbage line loses only itself, not the rest of the file."""
    root = tmp_path / "projects"
    path = root / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(_record([_tool_use("a")])),
                '{"type": "assistant", "message": {"content": [{"type": "tool_u',  # truncated
                "   ",  # whitespace-only
                "[1, 2, 3]",  # valid JSON, wrong shape (not a dict)
                json.dumps({"type": "assistant"}),  # no message
                json.dumps({"type": "assistant", "message": "a string"}),  # message not a dict
                json.dumps(_record([_tool_use("b")])),
                json.dumps(_record([_tool_result("a"), _tool_result("b")])),
            ]
        )
        + "\n"
    )

    ex = tx.scan(root=root)

    assert ex.stats.json_parse_failures == 1
    assert ex.stats.blank_lines == 1
    assert [c.tool_use_id for c in ex.calls] == ["a", "b"]
    assert ex.match_rate == 1.0


# ---------------------------------------------------------------------------
# AC 1, part two: "joins tool calls to results by tool_use_id"
#
# The join must be keyed strictly on tool_use_id -- never on position, record
# adjacency, or file identity. These tests break every one of those shortcuts.
# ---------------------------------------------------------------------------


def test_join_is_by_id_not_by_position_when_ids_interleave(tmp_path):
    """Results arrive out of order; positional pairing would mis-attribute all three."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("a"), _tool_use("b"), _tool_use("c")]),
            # Deliberately reversed relative to the calls.
            _record(
                [
                    _tool_result("c", "body-c", is_error=True),
                    _tool_result("a", "body-a"),
                    _tool_result("b", "body-b"),
                ]
            ),
        ],
    )

    ex = tx.scan(root=root)

    assert ex.match_rate == 1.0
    by_id = {c.tool_use_id: c for c in ex.calls}
    assert by_id["a"].result.text == "body-a"
    assert by_id["b"].result.text == "body-b"
    assert by_id["c"].result.text == "body-c"
    # Only the genuinely failing call is flagged.
    assert [c.tool_use_id for c in ex.calls if c.result.is_error] == ["c"]


def test_join_works_when_the_result_precedes_the_call_in_the_file(tmp_path):
    """The join runs after the whole corpus is read, so order cannot matter."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_result("late", "answer")]),
            _record([_tool_use("late")]),
        ],
    )

    ex = tx.scan(root=root)

    assert ex.match_rate == 1.0
    assert ex.calls[0].result.text == "answer"


def test_join_crosses_transcript_files(tmp_path):
    """A session can be resumed into a new file with the result landing there."""
    root = tmp_path / "projects"
    # "b-calls" sorts after "a-results", so the result is read before the call.
    _write_transcript(root, "proj", "a-results", [_record([_tool_result("split", "carried over")])])
    _write_transcript(root, "proj", "b-calls", [_record([_tool_use("split")])])

    ex = tx.scan(root=root)

    assert ex.stats.files_scanned == 2
    assert ex.total_calls == 1
    assert ex.calls[0].session == "b-calls"
    assert ex.calls[0].result.text == "carried over"
    assert ex.match_rate == 1.0


def test_join_ignores_orphan_results_and_flags_orphan_calls(tmp_path):
    """Extra results do not inflate the match rate; missing ones deflate it."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("has-result"), _tool_use("no-result")]),
            _record([_tool_result("has-result"), _tool_result("never-called", "orphan")]),
        ],
    )

    ex = tx.scan(root=root)

    assert set(ex.results) == {"has-result", "never-called"}
    assert [c.tool_use_id for c in ex.matched_calls] == ["has-result"]
    assert [c.tool_use_id for c in ex.unmatched_calls] == ["no-result"]
    assert ex.match_rate == pytest.approx(0.5)  # 1 of 2 calls, not 1 of 2 results
    assert ex.calls[1].result is None


def test_join_ignores_the_record_type_carrying_the_result(tmp_path):
    """Real transcripts put tool_result blocks in ``user`` records."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("t1")], type="assistant"),
            _record([_tool_result("t1", "from a user record")], type="user"),
        ],
    )

    ex = tx.scan(root=root)

    assert ex.match_rate == 1.0
    assert ex.calls[0].result.text == "from a user record"


def test_join_skips_blocks_with_no_usable_id(tmp_path):
    """Blocks missing an id cannot be joined and must not become phantom rows."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record(
                [
                    {"type": "tool_use", "name": "mcp__projectman__pm_get", "input": {}},  # no id
                    {"type": "tool_use", "id": "", "name": "mcp__projectman__pm_get"},  # empty id
                    _tool_use("real"),
                ]
            ),
            _record(
                [
                    {"type": "tool_result", "content": "no id"},
                    _tool_result("real", "ok"),
                ]
            ),
        ],
    )

    ex = tx.scan(root=root)

    # Blocks are still *counted* -- they just cannot be joined.
    assert ex.stats.tool_use_blocks_total == 3
    assert ex.stats.tool_result_blocks_total == 2
    assert [c.tool_use_id for c in ex.calls] == ["real"]
    assert list(ex.results) == ["real"]
    assert ex.match_rate == 1.0


def test_duplicate_result_ids_are_counted_and_last_one_wins(tmp_path):
    """Replayed/compacted transcripts can repeat a tool_use_id."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("dup")]),
            _record([_tool_result("dup", "first")]),
            _record([_tool_result("dup", "second", is_error=True)]),
        ],
    )

    ex = tx.scan(root=root)

    assert ex.stats.duplicate_result_ids == 1
    assert ex.stats.tool_result_blocks_total == 2
    assert len(ex.results) == 1
    assert ex.calls[0].result.text == "second"
    assert ex.calls[0].result.is_error is True
    assert ex.match_rate == 1.0


def test_join_is_idempotent_and_reflects_late_result_additions(tmp_path):
    """``join`` is the single point of truth and can be re-run safely."""
    root = tmp_path / "projects"
    _write_transcript(root, "proj", "sess", [_record([_tool_use("a"), _tool_use("b")])])

    ex = tx.scan(root=root)
    assert ex.match_rate == 0.0

    tx.join(ex)
    assert ex.match_rate == 0.0  # idempotent: no result invented

    ex.results["b"] = tx.ToolResult(tool_use_id="b", is_error=False, text="late")
    tx.join(ex)
    assert ex.match_rate == pytest.approx(0.5)
    assert ex.calls[1].result.text == "late"
    assert ex.calls[0].result is None


def test_sidechain_subagent_calls_are_walked_and_joined(tmp_path):
    """Subagent (sidechain) transcripts are part of the corpus, and flagged."""
    root = tmp_path / "projects"
    _write_transcript(
        root,
        "proj",
        "sess",
        [
            _record([_tool_use("main")]),
            _record([_tool_result("main")]),
            _record([_tool_use("sub")], isSidechain=True),
            _record([_tool_result("sub")], isSidechain=True),
        ],
    )

    ex = tx.scan(root=root)

    assert ex.match_rate == 1.0
    assert [c.is_sidechain for c in ex.calls] == [False, True]


# ---------------------------------------------------------------------------
# AC 4: "match rate is asserted and the run fails loudly if it drops below 99%"
#
# Three separate things have to hold, and the tests below are split along them:
#
#   1. the boundary is exactly 0.99 and the comparison is inclusive at it;
#   2. the failure is LOUD at the CLI layer -- non-zero exit, message on
#      stderr, naming the rate, the unmatched count and the likely cause --
#      and a bad join (exit 1) is distinguishable from an empty corpus
#      (exit 2). A silent exit 0 on a bad join is the failure this AC exists
#      to prevent, so it is asserted against from every angle;
#   3. the assertion is reachable in normal use: scan() raises instead of
#      returning partial data, and the default really is 0.99.
# ---------------------------------------------------------------------------


def _join_corpus(root, calls, results, project="proj", session="sess"):
    """Write a corpus with ``calls`` ProjectMan calls of which ``results`` join."""
    _write_transcript(
        root,
        project,
        session,
        [
            _record([_tool_use(f"c{i}") for i in range(calls)]),
            _record([_tool_result(f"c{i}") for i in range(results)]),
        ],
    )
    return root


# --- 1. the boundary --------------------------------------------------------


def test_default_minimum_is_ninety_nine_percent():
    """The number 0.99 must live in exactly one place and be the default everywhere."""
    assert tx.DEFAULT_MIN_MATCH_RATE == 0.99

    sig_default = inspect.signature(tx.Extraction.assert_match_rate).parameters["minimum"].default
    assert sig_default == tx.DEFAULT_MIN_MATCH_RATE
    assert tx.build_parser().get_default("min_match_rate") == tx.DEFAULT_MIN_MATCH_RATE


@pytest.mark.parametrize(
    "calls, results, rate, should_raise",
    [
        (1000, 989, 0.989, True),  # just below   -> fails
        (1000, 990, 0.990, False),  # exactly at   -> passes (inclusive)
        (1000, 991, 0.991, False),  # just above   -> passes
        (1000, 1000, 1.0, False),  # perfect      -> passes
        (1000, 0, 0.0, True),  # total collapse (the filtered-results trap)
        (2, 1, 0.5, True),  # tiny corpus, still enforced
    ],
)
def test_boundary_is_at_ninety_nine_percent_inclusive(tmp_path, calls, results, rate, should_raise):
    ex = tx.scan(root=_join_corpus(tmp_path / "projects", calls, results))

    assert ex.match_rate == pytest.approx(rate)
    assert len(ex.unmatched_calls) == calls - results

    if should_raise:
        with pytest.raises(tx.MatchRateError):
            ex.assert_match_rate()
    else:
        # Returns the rate (not None/True) so callers can log what they verified.
        assert ex.assert_match_rate() == pytest.approx(rate)


def test_a_non_finite_minimum_cannot_silently_disable_the_check(tmp_path):
    """NaN loses every comparison, which would turn the guard into a no-op.

    Regression: ``--min-match-rate nan`` used to make a 50%-joined corpus exit 0.
    """
    root = _join_corpus(tmp_path / "projects", 2, 1)
    ex = tx.scan(root=root)

    for bad in (float("nan"), float("inf"), -1.0, 99):  # 99 = the "percent" typo
        with pytest.raises(ValueError) as exc:
            ex.assert_match_rate(bad)
        assert not isinstance(exc.value, tx.MatchRateError)  # not mistaken for a pass/fail
        with pytest.raises(ValueError):
            tx.scan(root=root, min_match_rate=bad)

    # The CLI rejects it at parse time rather than running with no guard.
    with pytest.raises(SystemExit) as sysexit:
        tx.main(["--root", str(root), "--min-match-rate", "nan"])
    assert sysexit.value.code != 0


# --- 2. loudness at the CLI layer ------------------------------------------


def test_cli_failure_names_the_rate_the_count_and_the_likely_cause(tmp_path, capsys):
    """"Loudly" means diagnosable: what the rate was, how many, and why."""
    root = _join_corpus(tmp_path / "projects", 200, 150)  # 75%

    rc = tx.main(["--root", str(root)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "75.0000%" in captured.err  # the actual rate
    assert "99.0000%" in captured.err  # the bar it missed
    assert "50 of 200" in captured.err  # unmatched count / total
    assert "mcp__projectman__* calls have no tool_result" in captured.err
    assert "Do NOT trust any downstream number" in captured.err
    assert "filtered before the join" in captured.err  # the likely cause
    # The diagnosis goes to stderr, not buried in the stdout summary.
    assert "error:" not in captured.out


def test_cli_lists_unmatched_calls_capped_at_ten(tmp_path, capsys):
    """Enough evidence to debug the join, without a 10k-line wall of text."""
    root = _join_corpus(tmp_path / "projects", 60, 20)  # 40 unmatched

    assert tx.main(["--root", str(root)]) == 1
    err_lines = [ln for ln in capsys.readouterr().err.splitlines() if "unmatched " in ln]

    assert len(err_lines) == 10
    for line in err_lines:
        assert "mcp__projectman__pm_update" in line  # tool name
        assert "sess.jsonl:" in line  # file:line, so it can be looked up


def test_cli_exit_1_bad_join_is_distinct_from_exit_2_empty_corpus(tmp_path, capsys):
    """A bad join and "nothing to measure" are different failures.

    Collapsing them would let a 0%-join corpus masquerade as an empty one.
    """
    bad_join = _join_corpus(tmp_path / "bad", 10, 1)
    no_transcripts = tmp_path / "absent"
    no_pm_calls = tmp_path / "nopm"
    _write_transcript(
        no_pm_calls,
        "proj",
        "sess",
        [_record([_tool_use("b1", "Bash", {"command": "ls"})]), _record([_tool_result("b1")])],
    )

    assert tx.main(["--root", str(bad_join)]) == 1
    assert "match rate" in capsys.readouterr().err

    assert tx.main(["--root", str(no_transcripts)]) == 2
    assert "no transcripts found" in capsys.readouterr().err

    assert tx.main(["--root", str(no_pm_calls)]) == 2
    err = capsys.readouterr().err
    assert "no mcp__projectman__* tool calls found" in err
    # Vacuously 1.0 -- so the empty case must NOT be reported as a match-rate pass.
    assert "match rate" not in err


def test_cli_never_exits_zero_on_a_bad_join_whatever_the_output_mode(tmp_path, capsys):
    """The guard runs last, so no output flag can short-circuit past it."""
    root = _join_corpus(tmp_path / "projects", 100, 50)
    out = tmp_path / "out" / "pm_calls.jsonl"

    for argv in (
        ["--root", str(root)],
        ["--root", str(root), "--json"],
        ["--root", str(root), "--out", str(out)],
        ["--root", str(root), "--json", "--out", str(out), "--preview-chars", "0"],
    ):
        assert tx.main(argv) == 1, argv
        assert "match rate" in capsys.readouterr().err, argv

    # Data may be written for debugging, but the exit code still condemns it.
    assert out.exists()


def test_cli_reports_the_rate_on_stdout_even_when_it_passes(tmp_path, capsys):
    """The rate is always stated, so a slow drift toward the bar is visible."""
    root = _join_corpus(tmp_path / "projects", 1000, 995)

    assert tx.main(["--root", str(root)]) == 0
    assert "match rate            995/1000 (99.50%)" in capsys.readouterr().out

    assert tx.main(["--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["match_rate"] == pytest.approx(0.995)


def test_cli_min_match_rate_flag_overrides_the_default(tmp_path, capsys):
    """Lowering the bar is possible but must be explicit and deliberate."""
    root = _join_corpus(tmp_path / "projects", 100, 60)  # 60%

    assert tx.main(["--root", str(root)]) == 1  # default 0.99
    capsys.readouterr()
    assert tx.main(["--root", str(root), "--min-match-rate", "0.5"]) == 0
    assert tx.main(["--root", str(root), "--min-match-rate", "0.6"]) == 0  # inclusive
    capsys.readouterr()
    assert tx.main(["--root", str(root), "--min-match-rate", "0.61"]) == 1
    assert tx.main(["--root", str(root), "--min-match-rate", "1.0"]) == 1
    assert "100.0000%" in capsys.readouterr().err


def test_cli_fails_loudly_via_the_env_var_with_no_root_flag(tmp_path, capsys, monkeypatch):
    """The real invocation takes its root from the environment, not --root."""
    root = _join_corpus(tmp_path / "projects", 10, 2)
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(root))

    assert tx.main([]) == 1
    err = capsys.readouterr().err
    assert "20.0000%" in err
    assert "8 of 10" in err


def test_module_entrypoint_propagates_the_failing_exit_code(tmp_path):
    """``python -m tools.usage_telemetry`` is the actual run; it must exit 1."""
    root = _join_corpus(tmp_path / "projects", 10, 1)
    proc = subprocess.run(
        [sys.executable, "-m", "tools.usage_telemetry", "--root", str(root)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "match rate" in proc.stderr
    assert "10.0000%" in proc.stderr


# --- 3. the assertion is reachable in normal use ----------------------------


def test_scan_raises_instead_of_returning_partial_data(tmp_path):
    """The failure mode this AC guards is *quietly returning* a partial join."""
    root = _join_corpus(tmp_path / "projects", 100, 50)

    with pytest.raises(tx.MatchRateError) as exc:
        tx.scan(root=root, min_match_rate=tx.DEFAULT_MIN_MATCH_RATE)
    assert "50.0000%" in str(exc.value)

    # Same corpus without the threshold: data comes back, so the raise above is
    # the assertion firing -- not the scan failing for some unrelated reason.
    ex = tx.scan(root=root)
    assert ex.total_calls == 100 and ex.match_rate == pytest.approx(0.5)

    # min_match_rate=None (the default) means "do not assert", not "assert 0.99".
    assert tx.scan(root=root, min_match_rate=None).match_rate == pytest.approx(0.5)


def test_scan_returns_normally_when_the_join_is_good(tmp_path):
    root = _join_corpus(tmp_path / "projects", 1000, 992)
    ex = tx.scan(root=root, min_match_rate=tx.DEFAULT_MIN_MATCH_RATE)
    assert ex.match_rate == pytest.approx(0.992)
    assert len(ex.matched_calls) == 992


def test_match_rate_error_is_a_distinguishable_exception_type():
    """Callers must be able to catch this specifically, not by string matching."""
    assert issubclass(tx.MatchRateError, RuntimeError)
    assert tx.MatchRateError is tx_pkg.MatchRateError  # exported from the package


def test_summary_exposes_the_rate_for_downstream_baselines(tmp_path):
    """US-PM-6-9 records the rate alongside the numbers it qualifies."""
    ex = tx.scan(root=_join_corpus(tmp_path / "projects", 200, 199))
    summary = ex.summary()

    assert summary["match_rate"] == pytest.approx(0.995)
    assert summary["matched"] == 199
    assert summary["unmatched"] == 1
    assert summary["calls"] == 200
