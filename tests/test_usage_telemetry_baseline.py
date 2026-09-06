"""Tests for the baseline capture/compare artifact (US-PM-6-9).

The baseline is the file every later "the fixes worked" claim is measured
against, so the properties that matter are not the numbers themselves -- those
come from ``report``, which is already tested -- but the things that make a
stored number *interpretable a year later*:

* provenance is present and complete (when, which corpus, which commit);
* rates are stored as percentages, once, so a comparison cannot silently read
  6.26% as 0.0626;
* the artifact says out loud that the corpus is live and growing;
* a comparison across a *grown* corpus still reports the rate movement, and
  labels a rising failure rate as worse rather than shrugging at it.

``baseline`` must also stay purely additive: it consumes ``extract``/``classify``
/``report`` and changes nothing about them.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.usage_telemetry import baseline as bl
from tools.usage_telemetry import report as rp_mod
from tools.usage_telemetry.report import build_report
from tools.usage_telemetry.extract import MatchRateError, ToolCall, ToolResult

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
):
    call = ToolCall(
        tool_use_id=f"{session}-{seq}",
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
    call.result = ToolResult(
        tool_use_id=call.tool_use_id, is_error=is_error, text=text
    )
    return call


def _record(content, session="sess-a", timestamp="2026-07-29T00:00:00Z"):
    return {
        "type": "assistant",
        "sessionId": session,
        "timestamp": timestamp,
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
def corpus_root(tmp_path):
    """Ten calls: 1 hard error, 1 soft error, 1 malformed -- 3 distinct failures."""
    root = tmp_path / "projects"
    records = [
        _record([_tool_use("c1", "mcp__projectman__pm_grab", {"task_id": "US-X-1"})]),
        _record([_tool_result("c1", "x" * 500)]),
        _record([_tool_use("c2", "mcp__projectman__pm_update", {"id": "US-X-1"})]),
        _record([_tool_result("c2", "boom", is_error=True)]),
        _record([_tool_use("c3", "mcp__projectman__pm_update", {"id": "US-X-1"})]),
        _record([_tool_result("c3", SOFT_NOTE_LIMIT)]),
        _record(
            [_tool_use("c4", "mcp__projectman__pm_update", {"__unparsedToolInput": "{"})]
        ),
        _record([_tool_result("c4", "ok")]),
    ]
    for i in range(5, 11):
        records.append(
            _record([_tool_use(f"c{i}", "mcp__projectman__pm_get", {"id": "US-X-1"})])
        )
        records.append(_record([_tool_result(f"c{i}", "ok")]))
    _write_transcript(root, "-home-ryan-Repo-ProjectMan", "sess-a", records)
    return root


def sample_baseline(label="pre-fix", repo=None, calls=None, captured_at=None):
    call_list = calls if calls is not None else [
        make_call(tool="pm_update", seq=0),
        make_call(tool="pm_update", seq=1, text="boom", is_error=True),
        make_call(tool="pm_get", seq=2),
        make_call(tool="pm_get", seq=3),
    ]
    report = build_report(call_list, extraction_summary={
        "root": "/corpus",
        "tool_prefix": "mcp__projectman__",
        "files_scanned": 1,
        "match_rate": 1.0,
    })
    return bl.build_baseline(
        report,
        repo=repo or REPO_ROOT,
        label=label,
        captured_at=captured_at or datetime(2026, 7, 29, tzinfo=timezone.utc),
    )


# ------------------------------------------------------------- provenance --


def test_baseline_records_every_provenance_field_a_later_reader_needs():
    art = sample_baseline()
    prov = art["provenance"]

    assert art["schema"] == bl.SCHEMA
    assert prov["label"] == "pre-fix"
    assert prov["captured_at"] == "2026-07-29T00:00:00+00:00"
    assert prov["corpus_root"] == "/corpus"
    assert prov["tool_prefix"] == "mcp__projectman__"
    assert prov["transcript_files"] == 1
    assert prov["calls"] == 4
    assert prov["match_rate"] == 1.0
    assert prov["corpus_is_live"] is True
    # The commit the analysis code was at -- a 40-char sha from the real repo.
    assert len(prov["git"]["commit"]) == 40


def test_git_provenance_reports_unknown_rather_than_clean_outside_a_repo(tmp_path):
    """A non-repo must not be reported as a clean tree.

    ``dirty: false`` is a claim that the capture is reproducible from ``commit``.
    Emitting it when git could not be read at all would be a lie of the exact
    kind provenance exists to prevent.
    """
    git = bl.git_provenance(tmp_path)
    assert git["commit"] is None
    assert git["dirty"] is None


def test_git_provenance_reads_a_real_repo_without_mutating_it():
    before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    git = bl.git_provenance(REPO_ROOT)
    after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout

    assert git["commit"] and len(git["commit"]) == 40
    assert git["branch"]
    assert isinstance(git["dirty"], bool)
    # The repo is recorded relative to the git root, so the value is the same in
    # every clone; "." is the root itself.
    assert git["repo"] == "."
    assert before == after, "capturing a baseline must never touch git state"


def test_git_provenance_records_a_subdirectory_relative_to_the_repo_root():
    """A capture taken from inside the tree still records a portable path."""
    git = bl.git_provenance(REPO_ROOT / "tools" / "usage_telemetry")
    assert git["repo"] == "tools/usage_telemetry"
    assert not Path(git["repo"]).is_absolute()


def test_the_raw_report_is_stored_verbatim_under_report():
    """The baseline wraps the report; it must not reshape or trim it."""
    call_list = [make_call(tool="pm_update", seq=0), make_call(tool="pm_get", seq=1)]
    report = build_report(call_list)
    art = bl.build_baseline(report, repo=REPO_ROOT)
    assert art["report"] == report.as_dict()


# ----------------------------------------------------------------- metrics --


def test_rates_are_stored_as_percentages_not_fractions():
    """``report`` emits 0.25; the baseline publishes 25.0. Convert exactly once."""
    art = sample_baseline()
    m = bl.headline_metrics(art)
    assert m["calls"] == 4
    assert m["hard_errors"] == 1
    assert m["hard_error_rate_pct"] == 25.0
    assert m["failure_rate_pct"] == 25.0
    assert m["match_rate_pct"] == 100.0


def test_headline_metrics_are_all_scalars_so_a_diff_stays_readable():
    m = bl.headline_metrics(sample_baseline())
    for key, value in m.items():
        assert not isinstance(value, (dict, list)), f"{key} is not scalar"


def test_headline_metrics_survive_a_report_without_a_classification():
    """``build_report`` can be handed no classification; metrics must not crash."""
    art = bl.build_baseline(build_report([], extraction_summary=None), repo=REPO_ROOT)
    m = bl.headline_metrics(art)
    assert m["calls"] == 0
    assert m["failure_rate_pct"] in (None, 0.0)


def test_longest_run_is_carried_into_the_headline():
    calls = [make_call(tool="pm_update", seq=i) for i in range(6)]
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["longest_run"] == 6
    assert m["longest_run_tool"] == "pm_update"


# ------------------------------------------- per-tool runs (US-PM-12-5) --
#
# US-PM-12's acceptance criterion is "longest consecutive-run length drops
# sharply in the next telemetry baseline", and it is about pm_update and
# pm_archive specifically. The corpus-wide ``longest_run`` cannot answer that:
# it names whichever tool tops the corpus, so the moment pm_get (or anything
# else) holds the record, a pm_update run collapsing from 45 to 3 leaves it
# unchanged and a reader would conclude nothing moved. Hence a per-tool number.


def test_the_headline_carries_a_longest_run_for_each_bulk_verb_tool():
    """A run per tool, measured independently of every other tool's runs."""
    calls = (
        [make_call(tool="pm_update", seq=i) for i in range(5)]
        + [make_call(tool="pm_archive", seq=5 + i) for i in range(3)]
    )
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["pm_update_longest_run"] == 5
    assert m["pm_archive_longest_run"] == 3


def test_a_per_tool_run_is_visible_even_when_another_tool_tops_the_corpus():
    """The failure mode the per-tool metric exists to prevent.

    pm_get holds the corpus record here, so ``longest_run`` says nothing about
    the bulk verbs; the per-tool keys still report their real, shorter runs.
    """
    calls = (
        [make_call(tool="pm_update", seq=i) for i in range(2)]
        + [make_call(tool="pm_get", seq=2 + i) for i in range(9)]
        + [make_call(tool="pm_archive", seq=11)]
    )
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["longest_run"] == 9 and m["longest_run_tool"] == "pm_get"
    assert m["pm_update_longest_run"] == 2
    assert m["pm_archive_longest_run"] == 1


def test_another_tool_in_the_middle_breaks_the_run_rather_than_bridging_it():
    """Three pm_update calls split by a pm_get are two runs, not one of three."""
    calls = [
        make_call(tool="pm_update", seq=0),
        make_call(tool="pm_update", seq=1),
        make_call(tool="pm_get", seq=2),
        make_call(tool="pm_update", seq=3),
    ]
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["pm_update_longest_run"] == 2


def test_runs_do_not_span_two_transcripts():
    """Six pm_update calls across two sessions are two runs of three.

    A cross-session merge would inflate exactly the number this criterion is
    argued from, in the direction that flatters the "before" measurement.
    """
    calls = [make_call(tool="pm_update", session="sess-a", seq=i) for i in range(3)] + [
        make_call(tool="pm_update", session="sess-b", seq=i) for i in range(3)
    ]
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["pm_update_longest_run"] == 3


def test_a_bulk_verb_tool_the_corpus_never_saw_reports_a_measured_zero():
    """0, not None: nobody called pm_archive, and that is a real observation."""
    m = bl.headline_metrics(
        sample_baseline(calls=[make_call(tool="pm_update", seq=0)])
    )
    assert m["pm_archive_longest_run"] == 0


def test_a_report_without_a_by_tool_section_reports_unknown_not_zero():
    """Only a *missing* section is unknown -- an absent section is not a zero."""
    m = bl.headline_metrics({"schema": bl.SCHEMA, "provenance": {}, "report": {}})
    assert m["pm_update_longest_run"] is None
    assert m["pm_archive_longest_run"] is None


def test_every_bulk_verb_run_metric_reads_shorter_as_better():
    """Direction has to be declared, or the comparison prints a bare delta."""
    for tool in bl.BULK_RUN_TOOLS:
        assert f"{tool}_longest_run" in bl.LOWER_IS_BETTER, tool


def test_a_shortening_pm_update_run_compares_as_better():
    """The criterion, end to end: long single-item burst -> short bulk-era run."""
    before = sample_baseline(
        calls=[make_call(tool="pm_update", seq=i) for i in range(20)]
    )
    after = sample_baseline(
        calls=[make_call(tool="pm_update", seq=i) for i in range(2)]
    )
    row = bl.compare(before, after)["metrics"]["pm_update_longest_run"]
    assert row["before"] == 20
    assert row["after"] == 2
    assert row["delta"] == -18
    assert row["direction"] == "better"


def test_the_committed_baseline_already_answers_the_per_tool_question(committed):
    """The metric is retroactive: the stored "before" needs no re-capture.

    Every baseline ever written carries per-tool run profiles, so these are the
    pre-bulk-verb numbers the next capture is measured against.
    """
    m = bl.headline_metrics(committed)
    assert m["pm_update_longest_run"] == 45
    assert m["pm_archive_longest_run"] == 15


# ----------------------------------------------------------------- compare --


def test_compare_reports_rate_movement_when_the_corpus_grew():
    """The load-bearing case: more calls *and* more failures, but a better rate.

    Before: 1 failure in 4 (25%). After: 2 failures in 40 (5%). Absolute failures
    doubled; the rate fell 5x. A comparison that only looked at counts would
    report a regression on a real improvement.
    """
    before = sample_baseline(calls=[
        make_call(tool="pm_update", seq=0, text="boom", is_error=True),
        *[make_call(tool="pm_get", seq=i) for i in range(1, 4)],
    ])
    after = sample_baseline(label="post-fix", calls=[
        make_call(tool="pm_update", seq=0, text="boom", is_error=True),
        make_call(tool="pm_update", seq=1, text="boom", is_error=True),
        *[make_call(tool="pm_get", seq=i) for i in range(2, 40)],
    ])

    diff = bl.compare(before, after)
    assert diff["corpus_grew"] is True
    assert diff["metrics"]["calls"]["delta"] == 36
    assert diff["metrics"]["failures"]["delta"] == 1
    assert diff["metrics"]["failures"]["direction"] == "worse"
    assert diff["metrics"]["failure_rate_pct"]["before"] == 25.0
    assert diff["metrics"]["failure_rate_pct"]["after"] == 5.0
    assert diff["metrics"]["failure_rate_pct"]["direction"] == "better"


def test_compare_labels_a_rising_failure_rate_as_worse():
    before = sample_baseline(calls=[make_call(tool="pm_get", seq=i) for i in range(4)])
    after = sample_baseline(label="post-fix", calls=[
        make_call(tool="pm_get", seq=0, text="boom", is_error=True),
        *[make_call(tool="pm_get", seq=i) for i in range(1, 4)],
    ])
    diff = bl.compare(before, after)
    assert diff["metrics"]["failure_rate_pct"]["direction"] == "worse"


def test_compare_carries_both_captures_identities():
    diff = bl.compare(sample_baseline(), sample_baseline(label="post-fix"))
    assert diff["before"]["label"] == "pre-fix"
    assert diff["after"]["label"] == "post-fix"
    assert diff["before"]["captured_at"] == "2026-07-29T00:00:00+00:00"
    assert len(diff["after"]["commit"]) == 40


def test_compare_of_a_baseline_against_itself_is_all_zeroes():
    art = sample_baseline()
    diff = bl.compare(art, art)
    assert diff["corpus_grew"] is False
    numeric = [
        row["delta"] for row in diff["metrics"].values() if "delta" in row
    ]
    assert numeric and all(d == 0 for d in numeric)


def test_format_comparison_warns_that_the_corpus_is_live():
    text = bl.format_comparison(bl.compare(sample_baseline(), sample_baseline()))
    assert "live" in text
    assert "rate_pct" in text
    assert "failure_rate_pct" in text


# ---------------------------------------------------------------- markdown --


def test_summary_states_it_is_the_pre_fix_baseline():
    md = bl.format_summary(sample_baseline())
    assert "PRE-FIX baseline" in md


def test_summary_discloses_that_the_corpus_is_live_and_self_inclusive():
    """AC: the artifact must not present a growing corpus as a static dataset."""
    md = bl.format_summary(sample_baseline())
    assert "still being written to" in md
    assert "session that captured this baseline" in md
    assert "not a static dataset" in md
    # And the exact capture moment, not just the date.
    assert "2026-07-29T00:00:00+00:00" in md


def test_summary_carries_the_provenance_and_headline_tables():
    md = bl.format_summary(sample_baseline())
    for needle in (
        "captured at (UTC)",
        "code at commit",
        "corpus root",
        "transcript files",
        "call->result match rate",
        "hard errors",
        "malformed inputs",
        "longest consecutive run",
    ):
        assert needle in md, needle


def test_summary_flags_a_dirty_tree_as_not_reproducible_from_the_commit():
    art = sample_baseline()
    art["provenance"]["git"]["dirty"] = True
    assert "dirty" in bl.format_summary(art)

    art["provenance"]["git"]["dirty"] = False
    assert "dirty" not in bl.format_summary(art)

    art["provenance"]["git"]["dirty"] = None
    assert "working tree state unknown" in bl.format_summary(art)


# ---------------------------------------------------------------- round trip --


def test_write_then_load_round_trips(tmp_path):
    art = sample_baseline()
    json_path, md_path = bl.write_baseline(art, tmp_path / "nested", "baseline-pre-fix")
    assert json_path.name == "baseline-pre-fix.json"
    assert md_path.name == "baseline-pre-fix.md"
    assert bl.load_baseline(json_path) == art
    assert md_path.read_text(encoding="utf-8").startswith("# Usage-telemetry baseline")


def test_load_rejects_a_file_that_is_not_a_baseline(tmp_path):
    """A bare report JSON has no provenance -- comparing against it is meaningless."""
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"totals": {"calls": 1}}), encoding="utf-8")
    with pytest.raises(ValueError):
        bl.load_baseline(path)


# --------------------------------------------------------------------- cli --


def _cli(*argv):
    return bl.main(list(argv))


def test_cli_capture_writes_both_artifacts(corpus_root, tmp_path, capsys):
    out = tmp_path / "telemetry"
    rc = _cli("capture", "--root", str(corpus_root), "--out-dir", str(out),
              "--name", "baseline-pre-fix", "--label", "pre-fix",
              "--note", "captured before the fixes landed")
    assert rc == 0
    art = bl.load_baseline(out / "baseline-pre-fix.json")
    assert art["provenance"]["label"] == "pre-fix"
    assert art["provenance"]["note"] == "captured before the fixes landed"
    assert art["report"]["totals"]["calls"] == 10
    m = bl.headline_metrics(art)
    assert m["hard_errors"] == 1
    assert m["soft_errors"] == 1
    assert m["malformed_inputs"] == 1
    assert m["failures"] == 3
    assert m["failure_rate_pct"] == 30.0

    md = (out / "baseline-pre-fix.md").read_text(encoding="utf-8")
    assert "captured before the fixes landed" in md
    out_text = capsys.readouterr().out
    assert "baseline-pre-fix.json" in out_text


def test_cli_capture_exits_2_on_an_empty_corpus(tmp_path, capsys):
    root = tmp_path / "projects"
    root.mkdir()
    rc = _cli("capture", "--root", str(root), "--out-dir", str(tmp_path / "o"))
    assert rc == 2
    assert "no mcp__projectman__* calls" in capsys.readouterr().err
    assert not (tmp_path / "o").exists(), "an empty corpus must not write an artifact"


def test_cli_capture_honours_the_match_rate_guard(tmp_path, capsys):
    """A bad join must fail loudly rather than freeze a wrong baseline."""
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-a", [
        _record([_tool_use("x1", "mcp__projectman__pm_update", {})]),
    ])
    rc = _cli("capture", "--root", str(root), "--min-match-rate", "0.99",
              "--out-dir", str(tmp_path / "o"))
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_compare_two_stored_baselines(corpus_root, tmp_path, capsys):
    out = tmp_path / "t"
    _cli("capture", "--root", str(corpus_root), "--out-dir", str(out), "--name", "a")
    capsys.readouterr()
    _cli("capture", "--root", str(corpus_root), "--out-dir", str(out), "--name", "b",
         "--label", "post-fix")
    capsys.readouterr()

    rc = _cli("compare", str(out / "a.json"), str(out / "b.json"), "--json")
    assert rc == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["after"]["label"] == "post-fix"
    assert diff["metrics"]["calls"]["delta"] == 0
    assert diff["metrics"]["failure_rate_pct"]["before"] == 30.0


def test_cli_compare_captures_live_when_no_second_file_is_given(corpus_root, tmp_path, capsys):
    out = tmp_path / "t"
    _cli("capture", "--root", str(corpus_root), "--out-dir", str(out), "--name", "a")
    capsys.readouterr()
    rc = _cli("compare", str(out / "a.json"), "--root", str(corpus_root))
    assert rc == 0
    text = capsys.readouterr().out
    assert "failure_rate_pct" in text
    assert "live" in text


def test_cli_capture_stdout_writes_no_files(corpus_root, tmp_path, capsys):
    rc = _cli("capture", "--root", str(corpus_root), "--stdout",
              "--out-dir", str(tmp_path / "never"))
    assert rc == 0
    assert not (tmp_path / "never").exists()
    art = json.loads(capsys.readouterr().out)
    assert art["schema"] == bl.SCHEMA


def test_module_is_runnable_as_a_script(corpus_root, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "tools.usage_telemetry.baseline", "capture",
         "--root", str(corpus_root), "--out-dir", str(tmp_path / "o"), "--name", "x"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "o" / "x.json").exists()


# ------------------------------------------------------- additive-only check --


def test_baseline_adds_no_behaviour_to_the_modules_it_consumes(corpus_root):
    """The same corpus through ``report`` and through ``baseline`` must agree.

    US-PM-6-9 is allowed to add a module, not to change the analysis. If these
    two ever diverge, the baseline is measuring something the report does not.
    """
    from tools.usage_telemetry.extract import scan
    from tools.usage_telemetry.report import report_from_extraction

    direct = report_from_extraction(scan(root=str(corpus_root))).as_dict()
    art = bl.capture(root=str(corpus_root), repo=REPO_ROOT)
    assert art["report"] == direct


# ------------------------------------------------- the committed artifact --
#
# US-PM-6 AC: "A baseline is captured and committed before other fixes land."
#
# These tests guard the *deliverable*, not the code that produced it. Note what
# they deliberately do NOT assert: that git already tracks the file. The commit
# itself is a human action taken at the end of the epic, so asserting
# ``git ls-files`` would fail for a reason that is not a defect, and "fixing" it
# by committing would be the tail wagging the dog. What is verifiable now, and
# stays verifiable forever after the commit lands, is that the artifact is
# *committable*: a real file at its documented path inside the repo, not
# gitignored, not in a scratch directory -- plus that it parses, carries full
# provenance, records the pre-fix numbers, and works as a comparison base.

TELEMETRY_DIR = REPO_ROOT / "docs" / "telemetry"
COMMITTED = TELEMETRY_DIR / "baseline-pre-fix.json"
COMMITTED_MD = TELEMETRY_DIR / "baseline-pre-fix.md"
COMMITTED_README = TELEMETRY_DIR / "README.md"

# US-PM-30 added a second committed baseline, captured after the Sprint 1-8
# subtraction. It is not a replacement: the pre-fix corpus has since aged out of
# the transcript tree, so each file is now the only surviving record of its own
# corpus. Every check below that is about the *artifact* rather than about the
# pre-fix numbers runs over both, so the newer file cannot drift into being a
# second-class deliverable that nobody validates.
COMMITTED_POST = TELEMETRY_DIR / "baseline-post-subtraction.json"
COMMITTED_POST_MD = TELEMETRY_DIR / "baseline-post-subtraction.md"

# US-PM-32 added a third: the same corpus re-measured with every session that
# predates the note-length fix windowed out. It is a deliverable on the same
# terms as the other two -- same extractor, same schema, never overwritten --
# so it joins ``COMMITTED_BASELINES`` and is covered by every artifact-level
# guard rather than being validated only by its own two tests.
COMMITTED_WINDOWED = TELEMETRY_DIR / "baseline-windowed-post-fix.json"
COMMITTED_WINDOWED_MD = TELEMETRY_DIR / "baseline-windowed-post-fix.md"

#: label -> (json, markdown). The label is also the pytest param id.
COMMITTED_BASELINES: dict[str, tuple[Path, Path]] = {
    "pre-fix": (COMMITTED, COMMITTED_MD),
    "post-subtraction": (COMMITTED_POST, COMMITTED_POST_MD),
    "windowed-post-fix": (COMMITTED_WINDOWED, COMMITTED_WINDOWED_MD),
}

#: Frozen pre-fix ground truth. The pre-fix baseline is a historical
#: measurement: it is captured once and never re-captured, so these are exact,
#: not ranges. A test failure here means the artifact was overwritten or
#: regenerated -- which destroys the only "before" the epic has.
PRE_FIX = {
    "calls": 3416,
    "match_rate_pct": 100.0,
    "failures": 214,
    "hard_errors": 47,
    "soft_errors": 167,
    "malformed_inputs": 27,
    "longest_run": 45,
    "longest_run_tool": "pm_update",
}


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def committed():
    """The real pre-fix artifact, parsed. Fails (never skips) when it is missing."""
    assert COMMITTED.exists(), (
        f"the pre-fix baseline must exist at {COMMITTED.relative_to(REPO_ROOT)}"
    )
    return bl.load_baseline(COMMITTED)


class CommittedBaseline:
    """One committed baseline: its label, its two files and the parsed JSON.

    The artifact-level tests take this instead of a bare dict so a failure names
    *which* baseline broke, and so a test can reach the markdown companion
    without hard-coding a filename.
    """

    def __init__(self, label: str, json_path: Path, md_path: Path):
        self.label = label
        self.json_path = json_path
        self.md_path = md_path
        assert json_path.exists(), (
            f"the {label} baseline must exist at {json_path.relative_to(REPO_ROOT)}"
        )
        self.data = bl.load_baseline(json_path)

    @property
    def provenance(self) -> dict:
        return self.data["provenance"]

    def markdown(self) -> str:
        return self.md_path.read_text(encoding="utf-8")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CommittedBaseline {self.label}>"


@pytest.fixture(scope="module", params=list(COMMITTED_BASELINES), ids=list(COMMITTED_BASELINES))
def any_committed(request):
    """Every committed baseline in turn.

    Used by the checks that are true of *any* baseline the repo ships --
    provenance completeness, schema conformance, rate format, committability.
    The pre-fix-specific ground-truth tests keep the single ``committed``
    fixture, because those numbers are frozen history and are true of exactly
    one file.
    """
    json_path, md_path = COMMITTED_BASELINES[request.param]
    return CommittedBaseline(request.param, json_path, md_path)


@pytest.fixture(scope="module")
def post_subtraction():
    """The US-PM-30 baseline specifically."""
    json_path, md_path = COMMITTED_BASELINES["post-subtraction"]
    return CommittedBaseline("post-subtraction", json_path, md_path)


# -- (1) it exists at its documented path and is committable ----------------


def test_every_baseline_artifact_exists_at_its_documented_path(any_committed):
    """The AC is about a captured artifact, so absence is a failure, not a skip."""
    for path in (any_committed.json_path, any_committed.md_path, COMMITTED_README):
        assert path.is_file(), f"missing baseline artifact: {path}"
        assert path.stat().st_size > 0, f"empty baseline artifact: {path}"
    # A truncated or stub JSON would still be a file; the real capture is large.
    assert any_committed.json_path.stat().st_size > 10_000


def test_the_readme_documents_every_committed_baseline_pair():
    """The README is the documentation the path claims rest on."""
    readme = COMMITTED_README.read_text(encoding="utf-8")
    for json_path, md_path in COMMITTED_BASELINES.values():
        assert json_path.name in readme, json_path.name
        assert md_path.name in readme, md_path.name


def test_the_baseline_lives_inside_the_repo_not_a_temp_or_scratch_directory(any_committed):
    """A baseline in /tmp is not a baseline; it is a number someone once saw."""
    resolved = any_committed.json_path.resolve()
    rel = resolved.relative_to(REPO_ROOT.resolve())  # raises if outside the repo
    assert rel == Path("docs/telemetry") / any_committed.json_path.name
    lowered = str(resolved).lower()
    for scratch in ("/tmp/", "/var/tmp/", "scratchpad", "/.venv/", "node_modules"):
        assert scratch not in lowered, f"baseline sits under a scratch path: {scratch}"


def test_the_baseline_artifacts_are_not_gitignored_so_they_can_be_committed(any_committed):
    """``git check-ignore`` exits 1 when a path is *not* ignored.

    This is the committable half of "captured and committed": a file the repo
    would silently refuse to track could never satisfy the AC, and that failure
    mode is invisible until someone tries to commit.
    """
    for path in (any_committed.json_path, any_committed.md_path, COMMITTED_README):
        proc = _git("check-ignore", "-v", "--no-index", str(path))
        assert proc.returncode == 1, (
            f"{path.relative_to(REPO_ROOT)} is gitignored: {proc.stdout.strip()}"
        )


def test_git_sees_the_baseline_as_content_to_track(any_committed):
    """Either already tracked, or untracked-and-addable -- never ignored.

    Passes both before the human commits (``??``) and forever after (empty
    porcelain status, i.e. tracked and clean).
    """
    path = any_committed.json_path
    proc = _git("status", "--porcelain", "--ignored", "--", str(path))
    assert proc.returncode == 0, proc.stderr
    status = proc.stdout.strip()
    assert not status.startswith("!!"), f"git reports the baseline ignored: {status}"
    if status:
        assert status.split()[0] in {"??", "A", "M", "AM"}, status
    else:  # tracked and clean
        assert _git("ls-files", "--error-unmatch", str(path)).returncode == 0


# -- (2) it parses and conforms to its schema -------------------------------


def test_the_committed_baseline_parses_as_json_and_declares_its_schema(any_committed):
    committed = any_committed.data
    assert committed["schema"] == bl.SCHEMA == "projectman.usage-telemetry.baseline/1"
    # ``tool_list`` (US-PM-15) is the one optional top-level section: it measures
    # the schema surface the server offers rather than the transcript corpus, and
    # baselines captured before the metric existed simply do not carry it.
    assert set(committed) - {"tool_list"} == {"schema", "provenance", "report"}
    assert "tool_list" in committed or committed["provenance"]["label"] == "pre-fix"


def test_every_committed_baseline_came_from_the_same_extractor():
    """US-PM-30 AC 1: the post-subtraction file must not be a hand-rolled lookalike.

    Same schema string and same ``generator`` means the same ``capture`` entry
    point produced both, which is what makes the two comparable at all.
    """
    generators = set()
    for label, (json_path, _) in COMMITTED_BASELINES.items():
        data = bl.load_baseline(json_path)
        assert data["schema"] == bl.SCHEMA, label
        generators.add(data["provenance"]["generator"])
    assert len(generators) == 1, f"baselines came from different generators: {generators}"


def test_the_committed_baseline_conforms_to_the_artifact_schema(any_committed):
    """Every field a reader dereferences, with the type they will assume."""
    committed = any_committed.data
    prov = committed["provenance"]
    expected = {
        "label": str,
        "note": str,
        "captured_at": str,
        "corpus_root": str,
        "tool_prefix": str,
        "transcript_files": int,
        "calls": int,
        "matched_calls": int,
        "unmatched_calls": int,
        "match_rate": float,
        "sessions": int,
        "git": dict,
        "generator": str,
        "corpus_is_live": bool,
    }
    # US-PM-32's capture window. Optional here and nowhere else: the two files
    # committed before it existed do not carry the keys, and a reader who
    # dereferences them must treat "absent" and "null" alike as "whole corpus".
    optional = {"window_since": str, "sessions_excluded": int}
    assert set(prov) - set(optional) == set(expected)
    for key, kind in expected.items():
        assert isinstance(prov[key], kind), f"{key}: {type(prov[key])} != {kind}"
    for key, kind in optional.items():
        if prov.get(key) is not None:
            assert isinstance(prov[key], kind), f"{key}: {type(prov[key])} != {kind}"
    for key in ("repo", "commit", "branch", "dirty"):
        assert key in prov["git"], key

    report = committed["report"]
    for section in ("corpus", "totals", "failures", "runs", "by_tool", "bigrams"):
        assert section in report, section
    assert report["failures"]["inclusive"].keys() >= {
        "hard_error", "soft_error", "malformed_input"
    }
    assert report["failures"]["rates"].keys() >= {
        "hard_error", "soft_error", "malformed_input", "combined_failure_rate"
    }


def test_the_committed_baseline_survives_a_load_write_load_round_trip(tmp_path, any_committed):
    """Re-emitting it byte-for-byte proves nothing was hand-edited into the JSON."""
    committed = any_committed.data
    stem = any_committed.json_path.stem
    json_path, md_path = bl.write_baseline(committed, tmp_path, stem)
    assert bl.load_baseline(json_path) == committed
    assert json_path.read_text(encoding="utf-8") == any_committed.json_path.read_text(
        encoding="utf-8"
    )


def test_the_committed_markdown_still_publishes_the_numbers_its_json_holds(any_committed):
    """A stale ``.md`` beside a re-captured ``.json`` is the failure mode here.

    The generated summary is a pure function of the JSON. ``baseline-pre-fix.md``
    is exactly that function's output, so it is compared byte-for-byte.
    ``baseline-post-subtraction.md`` carries the generated summary *plus* the
    hand-written comparison US-PM-30 asks for, so the invariant there is
    containment: every generated table row must still appear verbatim, which is
    what would break if the JSON were re-captured and the prose left behind.
    """
    generated = bl.format_summary(any_committed.data)
    published = any_committed.markdown()
    if published == generated:
        return
    rows = [line for line in generated.splitlines() if line.startswith("| ")]
    assert rows, "the generated summary should contain table rows"
    missing = [row for row in rows if row not in published]
    assert not missing, (
        f"{any_committed.md_path.name} is stale -- generated rows absent: {missing[:3]}"
    )


def test_an_empty_or_corrupt_artifact_would_be_rejected_rather_than_compared(tmp_path):
    """The schema guard has to bite, or every test above tests nothing."""
    for payload in ("", "   ", "[]", "null", '{"totals": {"calls": 1}}'):
        path = tmp_path / "bad.json"
        path.write_text(payload, encoding="utf-8")
        with pytest.raises((ValueError, json.JSONDecodeError)):
            bl.load_baseline(path)


# -- (3) it carries the provenance a "before" measurement needs -------------


def test_the_committed_baseline_records_when_and_against_what_it_was_captured(any_committed):
    prov = any_committed.provenance

    captured = datetime.fromisoformat(prov["captured_at"])
    assert captured.tzinfo is not None, "a capture instant without a timezone is ambiguous"
    assert captured <= datetime.now(timezone.utc), "captured in the future"
    assert captured.microsecond or captured.second, "an instant, not just a date"

    assert Path(prov["corpus_root"]).is_absolute()
    assert prov["tool_prefix"] == "mcp__projectman__"
    assert prov["transcript_files"] > 0
    assert prov["sessions"] > 0
    assert prov["calls"] == prov["matched_calls"] > 0
    assert prov["unmatched_calls"] == 0
    assert prov["match_rate"] == 1.0, "AC of US-PM-6: verify ~100% join before trusting"
    assert prov["corpus_is_live"] is True
    assert "baseline" in prov["generator"] and "capture" in prov["generator"]


def test_the_committed_baseline_pins_the_code_that_produced_it(any_committed):
    git = any_committed.provenance["git"]
    commit = git["commit"]
    assert isinstance(commit, str) and len(commit) == 40
    assert all(c in "0123456789abcdef" for c in commit), commit
    assert git["branch"]
    assert isinstance(git["dirty"], bool), "dirty must never be unknown for the deliverable"

    # Repo-relative, so this holds in a fresh clone at any path -- an absolute
    # path would pin the artifact to the machine that captured it.
    recorded = Path(git["repo"])
    assert not recorded.is_absolute(), f"provenance records an absolute path: {git['repo']}"
    resolved = (REPO_ROOT / recorded).resolve()
    assert resolved.is_relative_to(REPO_ROOT.resolve()), git["repo"]
    assert resolved == REPO_ROOT.resolve(), "the baseline was captured from the repo root"

    kind = _git("cat-file", "-t", commit)
    if kind.returncode != 0:  # shallow clone / object pruned
        pytest.skip("recorded commit not present in this clone")
    assert kind.stdout.strip() == "commit"


def test_provenance_counts_agree_with_the_report_they_summarise(any_committed):
    """Provenance is a copy of report numbers; a drift would mislead a reader."""
    prov, report = any_committed.provenance, any_committed.data["report"]
    assert prov["calls"] == report["totals"]["calls"]
    assert prov["sessions"] == report["totals"]["sessions"]
    assert prov["matched_calls"] == report["totals"]["matched"]
    assert prov["unmatched_calls"] == report["totals"]["unmatched"]
    assert prov["transcript_files"] == report["corpus"]["files_scanned"]
    assert prov["corpus_root"] == report["corpus"]["root"]
    assert prov["match_rate"] == report["corpus"]["match_rate"]


def test_committed_rates_are_fractions_in_the_report_and_percentages_in_the_headline(
    any_committed,
):
    """The unit confusion this module exists to prevent, checked on the real files.

    ``report`` stores 0.0626; the baseline headline and the markdown publish
    6.26%. A file that stored the percentage twice, or published the fraction,
    would make every later comparison off by 100x in one direction or the other.
    """
    rates = any_committed.data["report"]["failures"]["rates"]
    for key, value in rates.items():
        assert isinstance(value, float), f"{key} is {type(value)}"
        assert 0.0 <= value <= 1.0, f"{key} looks like a percentage, not a fraction: {value}"

    m = bl.headline_metrics(any_committed.data)
    for headline_key, rate_key in (
        ("failure_rate_pct", "combined_failure_rate"),
        ("hard_error_rate_pct", "hard_error"),
        ("soft_error_rate_pct", "soft_error"),
        ("malformed_input_rate_pct", "malformed_input"),
    ):
        assert m[headline_key] == pytest.approx(rates[rate_key] * 100, abs=1e-3), headline_key
        assert m[headline_key] > 1.0 or rates[rate_key] < 0.01, headline_key
    assert m["match_rate_pct"] == 100.0

    # Published once, in percent, in the human artifact too.
    assert f"{m['failure_rate_pct']:.2f}%" in any_committed.markdown()


# -- (4) it records a PRE-FIX state -----------------------------------------


def test_the_committed_baseline_declares_itself_the_pre_fix_capture(committed):
    """"Before other fixes land" has to be recorded, not just remembered."""
    prov = committed["provenance"]
    assert prov["label"] == "pre-fix"
    note = prov["note"]
    assert "PRE-FIX" in note.upper()
    assert "before" in note.lower()
    md = COMMITTED_MD.read_text(encoding="utf-8")
    assert "PRE-FIX baseline" in md
    assert "before" in md
    assert "do not overwrite it" in md.lower()
    assert "Do not overwrite it." in COMMITTED_README.read_text(encoding="utf-8")


def test_the_committed_numbers_are_the_known_pre_fix_ground_truth(committed):
    """Exact, not ranged: this artifact is frozen history.

    Cross-checked against the four study appendices -- 6.26% combined failure
    rate, 47 hard errors, 27 malformed inputs, longest run 45x ``pm_update``.
    """
    m = bl.headline_metrics(committed)
    for key, expected in PRE_FIX.items():
        assert m[key] == expected, f"{key}: {m[key]} != {expected}"

    assert m["calls"] >= 3_400
    assert 6.2 <= m["failure_rate_pct"] <= 6.3
    assert m["hard_errors"] + m["soft_errors"] >= m["failures"] - m["malformed_inputs"]
    assert 3_500_000 < m["response_bytes"] < 6_000_000
    assert 1.0 < m["hard_error_rate_pct"] < 2.0
    assert 4.0 < m["soft_error_rate_pct"] < 6.0
    assert 0.5 < m["malformed_input_rate_pct"] < 1.2


def test_the_pre_fix_state_still_shows_the_defects_the_epic_exists_to_fix(committed):
    """A "before" that already looks fixed would make the epic unfalsifiable."""
    m = bl.headline_metrics(committed)
    assert m["failure_rate_pct"] > 1.0, (
        "a ~1% rate means the is_error-only mistake US-PM-6 exists to correct"
    )
    assert m["malformed_inputs"] > 0, "__unparsedToolInput must be counted, not dropped"
    assert m["soft_errors"] > m["hard_errors"], (
        "soft errors dominate; a baseline that missed them is the wrong methodology"
    )
    by_tool = {row["tool"]: row for row in committed["report"]["failures"]["by_tool"]}
    assert by_tool["pm_update"]["malformed"] == 27, (
        "every malformed input in the corpus is a pm_update note -- US-PM-1's target"
    )
    assert by_tool["pm_update"]["failure_rate"] > 0.1, "pm_update is the epic's hot spot"


def test_the_markdown_summary_publishes_the_same_pre_fix_numbers(committed):
    md = COMMITTED_MD.read_text(encoding="utf-8")
    assert "3,416" in md
    assert "6.26%" in md
    assert "47" in md and "27" in md
    assert "45" in md and "pm_update" in md
    assert committed["provenance"]["captured_at"] in md
    assert committed["provenance"]["git"]["commit"] in md


# -- (4b) the POST-SUBTRACTION capture (US-PM-30) ---------------------------
#
# AC 1: the artifacts exist and were produced by the same extractor as pre-fix
#       (the "same extractor" half is
#       ``test_every_committed_baseline_came_from_the_same_extractor``; the
#       provenance/schema/rate checks above now run over this file too).
# AC 3: the markdown compares calls per task and context per worker against the
#       pre-fix numbers.


def _mean_calls_per_session(baseline: dict) -> float:
    return baseline["report"]["totals"]["calls_per_session"]["mean"]


def _bytes_per_session(baseline: dict) -> float:
    totals = baseline["report"]["totals"]
    return totals["response_bytes"] / totals["sessions"]


def test_the_post_subtraction_baseline_declares_itself_and_names_its_commit(post_subtraction):
    prov = post_subtraction.provenance
    assert prov["label"] == "post-subtraction"
    note = prov["note"]
    # The note has to name the commit the capture follows, or "after the
    # subtraction" is an unverifiable claim.
    assert "1061084" in note, note
    assert "subtraction" in note.lower()
    md = post_subtraction.markdown()
    assert "POST-SUBTRACTION baseline" in md
    assert "do not overwrite" in md.lower()


def test_the_post_subtraction_capture_is_later_than_the_pre_fix_one(committed, post_subtraction):
    before = datetime.fromisoformat(committed["provenance"]["captured_at"])
    after = datetime.fromisoformat(post_subtraction.provenance["captured_at"])
    assert after > before, "the post-subtraction baseline must postdate the pre-fix one"


def test_the_post_subtraction_markdown_compares_calls_per_task(committed, post_subtraction):
    """AC 3, first half. Both sides of the comparison must be on the page."""
    md = post_subtraction.markdown()
    assert "Calls per task" in md
    for baseline in (committed, post_subtraction.data):
        mean = _mean_calls_per_session(baseline)
        assert f"{mean:.2f}" in md, f"calls-per-session mean {mean:.2f} missing from the markdown"
        median = baseline["report"]["totals"]["calls_per_session"]["median"]
        assert str(median) in md
    # Session counts are the denominator the means are read against.
    assert f"{committed['report']['totals']['sessions']:,}" in md
    assert f"{post_subtraction.data['report']['totals']['sessions']:,}" in md


def test_the_post_subtraction_markdown_compares_context_per_worker(committed, post_subtraction):
    """AC 3, second half: response bytes landing in one worker's context."""
    md = post_subtraction.markdown()
    assert "Context per worker" in md
    for baseline in (committed, post_subtraction.data):
        per_session = _bytes_per_session(baseline)
        assert f"{round(per_session):,}" in md, (
            f"bytes-per-session {round(per_session):,} missing from the markdown"
        )
        median_call = baseline["report"]["totals"]["bytes_per_call"]["median"]
        assert f"{median_call:,}" in md


def test_the_post_subtraction_markdown_reports_both_bulk_verb_longest_runs(
    committed, post_subtraction
):
    """The metrics US-PM-12-5 reads, with a before and an after for each."""
    md = post_subtraction.markdown()
    before = bl.headline_metrics(committed)
    after = bl.headline_metrics(post_subtraction.data)
    for tool in bl.BULK_RUN_TOOLS:
        key = f"{tool}_longest_run"
        assert key in md, f"{key} is not named in the comparison"
        assert str(before[key]) in md, f"{key} before value {before[key]} missing"
        assert str(after[key]) in md, f"{key} after value {after[key]} missing"


def test_the_post_subtraction_markdown_states_the_dirty_tree_caveat(post_subtraction):
    """A dirty capture that does not say so is the one unreadable outcome."""
    assert post_subtraction.provenance["git"]["dirty"] is True, (
        "if this capture is ever retaken from a clean tree, drop this test"
    )
    md = post_subtraction.markdown()
    assert "Provenance caveat" in md
    assert "dirty" in md
    assert "1061084" in md, "the caveat must name the commit the tree sat on"


def test_the_two_committed_baselines_compare_without_special_casing(
    committed, post_subtraction
):
    """The pair must work as a real before/after through ``compare`` itself."""
    diff = bl.compare(committed, post_subtraction.data)
    assert diff["before"]["label"] == "pre-fix"
    assert diff["after"]["label"] == "post-subtraction"
    metrics = diff["metrics"]
    for tool in bl.BULK_RUN_TOOLS:
        row = metrics[f"{tool}_longest_run"]
        assert isinstance(row["before"], int) and isinstance(row["after"], int)
        if row["delta"]:
            # Shorter runs are the win these verbs exist for; the label must
            # follow the number rather than flattering the newer capture.
            assert row["direction"] == ("better" if row["delta"] < 0 else "worse")
    assert metrics["pm_update_longest_run"]["before"] == PRE_FIX["longest_run"]
    text = bl.format_comparison(diff)
    assert "pm_update_longest_run" in text
    assert "pm_archive_longest_run" in text


# -- (5) it is usable as a comparison base ----------------------------------


def _grown_post_fix_capture(committed, *, calls_after, failures_after):
    """A synthetic later capture: bigger corpus, different failure rate."""
    import copy

    after = copy.deepcopy(committed)
    after["provenance"]["label"] = "post-fix"
    after["provenance"]["captured_at"] = "2026-09-01T00:00:00+00:00"
    totals = after["report"]["totals"]
    totals["calls"] = totals["matched"] = calls_after
    fail = after["report"]["failures"]
    fail["total_calls"] = calls_after
    fail["failures"] = failures_after
    fail["rates"]["combined_failure_rate"] = failures_after / calls_after
    return after


def test_a_later_capture_diffs_against_the_committed_baseline(committed):
    """The whole point of the AC: the epic's other stories become falsifiable."""
    after = _grown_post_fix_capture(committed, calls_after=6_000, failures_after=240)

    diff = bl.compare(committed, after)
    assert diff["before"]["label"] == "pre-fix"
    assert diff["before"]["captured_at"] == committed["provenance"]["captured_at"]
    assert diff["before"]["commit"] == committed["provenance"]["git"]["commit"]
    assert diff["after"]["label"] == "post-fix"

    # The corpus grew and absolute failures ROSE (214 -> 240), yet the rate FELL
    # (6.26% -> 4.0%). Only the rate row tells the truth about the fixes.
    assert diff["corpus_grew"] is True
    assert diff["metrics"]["calls"]["delta"] == 6_000 - PRE_FIX["calls"]
    assert diff["metrics"]["failures"]["delta"] == 26
    assert diff["metrics"]["failures"]["direction"] == "worse"
    rate = diff["metrics"]["failure_rate_pct"]
    assert rate["before"] == 6.2646
    assert rate["after"] == 4.0
    assert rate["delta"] < 0
    assert rate["direction"] == "better"


def test_a_regression_against_the_committed_baseline_is_reported_as_worse(committed):
    after = _grown_post_fix_capture(committed, calls_after=6_000, failures_after=600)
    diff = bl.compare(committed, after)
    assert diff["metrics"]["failure_rate_pct"]["after"] == 10.0
    assert diff["metrics"]["failure_rate_pct"]["direction"] == "worse"


def test_comparing_the_committed_baseline_with_itself_shows_no_movement(committed):
    diff = bl.compare(committed, committed)
    assert diff["corpus_grew"] is False
    deltas = [row["delta"] for row in diff["metrics"].values() if "delta" in row]
    assert deltas and all(d == 0 for d in deltas)
    assert all("direction" not in row for row in diff["metrics"].values())


def test_the_rendered_comparison_names_the_baseline_and_its_rate_movement(committed):
    after = _grown_post_fix_capture(committed, calls_after=6_000, failures_after=240)
    text = bl.format_comparison(bl.compare(committed, after))
    assert "pre-fix" in text and "post-fix" in text
    assert committed["provenance"]["git"]["commit"][:12] in text
    assert "failure_rate_pct" in text
    assert "better" in text
    assert "live" in text  # the growing-corpus caveat travels with the diff


def test_the_cli_compares_the_committed_baseline_against_a_stored_capture(
    committed, tmp_path, capsys
):
    """End to end over the real file, through the documented command."""
    after = _grown_post_fix_capture(committed, calls_after=6_000, failures_after=240)
    later = tmp_path / "baseline-later.json"
    later.write_text(json.dumps(after), encoding="utf-8")

    rc = bl.main(["compare", str(COMMITTED), str(later), "--json"])
    assert rc == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["before"]["label"] == "pre-fix"
    assert diff["metrics"]["failure_rate_pct"]["before"] == 6.2646
    assert diff["metrics"]["failure_rate_pct"]["direction"] == "better"
    assert diff["corpus_grew"] is True


# ------------------------------------------- completion run-log coverage --
#
# US-PM-8 AC: "Measured share of completions lacking a run-log entry drops to
# zero." The report emits a fraction; the headline publishes the percentage.


def _done_call(seq, note=None, session="sess-a"):
    args = {"id": "US-TST-1-1", "status": "done"}
    if note is not None:
        args["note"] = note
    return make_call(tool="pm_update", session=session, seq=seq, tool_input=args)


def test_two_bare_done_writes_in_ten_completions_reach_the_headline_as_20_pct():
    calls = [_done_call(0), _done_call(1)]
    calls += [_done_call(i, note="logged") for i in range(2, 5)]
    calls += [
        make_call(tool="pm_done_next", seq=i, tool_input={"task_id": f"T{i}"})
        for i in range(5, 8)
    ]
    calls += [
        make_call(tool="pm_accept", seq=i, tool_input={"task_id": f"T{i}", "note": "n"})
        for i in range(8, 10)
    ]
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["completions"] == 10
    assert m["completions_without_run_log"] == 2
    assert m["completions_without_run_log_rate_pct"] == 20.0


def test_a_verbs_only_corpus_publishes_a_zero_percent_gap():
    calls = [
        make_call(tool="pm_accept", seq=0, tool_input={"task_id": "A", "note": "n"}),
        make_call(tool="pm_done_next", seq=1, tool_input={"task_id": "B"}),
    ]
    m = bl.headline_metrics(sample_baseline(calls=calls))
    assert m["completions"] == 2
    assert m["completions_without_run_log_rate_pct"] == 0.0


def test_a_rising_completion_gap_is_labelled_worse():
    """Lower is better, so the direction flag has to point the right way."""
    before = sample_baseline(calls=[_done_call(0, note="logged")])
    after = sample_baseline(calls=[_done_call(0)])
    row = bl.compare(before, after)["metrics"]["completions_without_run_log_rate_pct"]
    assert row["before"] == 0.0
    assert row["after"] == 100.0
    assert row["direction"] == "worse"


def test_a_pre_metric_baseline_still_compares_without_the_completion_keys(committed):
    """The committed pre-fix artifact predates the metric; keys read ``None``."""
    m = bl.headline_metrics(committed)
    assert "completions_without_run_log_rate_pct" in m
    assert m["completions_without_run_log_rate_pct"] is None
    assert "completions with no run-log entry" not in bl.format_summary(committed)


def test_the_summary_publishes_the_completion_gap_when_the_report_has_one():
    md = bl.format_summary(sample_baseline(calls=[_done_call(0), _done_call(1, note="n")]))
    assert "completions with no run-log entry" in md
    assert "50.0" in md


# ------------------------------------------------------------ note length --
#
# US-PM-9 AC: "Median note length drops well below the cap." The gate lives here
# rather than in a unit assertion about live data -- the corpus number cannot
# move until the rewritten pm-orchestrate skill accumulates traffic -- so what
# is pinned is that a captured baseline reports the distribution and judges it.


def _note_call(chars, seq=0, session="sess-a"):
    """A `pm_update` completion whose note is ``chars`` characters long."""
    return make_call(
        tool="pm_update",
        session=session,
        seq=seq,
        tool_input={"id": "US-TST-1-1", "status": "done", "note": "n" * chars},
    )


def _notes_baseline(*sizes):
    return sample_baseline(calls=[_note_call(n, seq=i) for i, n in enumerate(sizes)])


def test_the_note_length_distribution_reaches_the_headline():
    m = bl.headline_metrics(_notes_baseline(100, 200, 900))
    assert m["note_length_median"] == 200
    assert m["note_length_p90"] == 900
    assert m["note_length_p95"] == 900


def test_the_gate_passes_when_the_median_and_p90_are_well_below_the_cap():
    m = bl.headline_metrics(_notes_baseline(150, 200, 250, 300))
    assert m["note_length_median"] <= bl.NOTE_LENGTH_GATE_MEDIAN
    assert m["note_length_p90"] <= bl.NOTE_LENGTH_GATE_P90
    assert m["note_length_gate_passed"] is True


def test_the_gate_fails_when_the_median_is_over_the_threshold():
    """The pre-fix shape: prose packed to the cap, so the median blows the gate."""
    m = bl.headline_metrics(_notes_baseline(900, 950, 1000))
    assert m["note_length_median"] == 950
    assert m["note_length_gate_passed"] is False


def test_the_gate_fails_on_p90_alone_even_with_a_fine_median():
    """A tail of packed notes is still the habit this story exists to end."""
    m = bl.headline_metrics(_notes_baseline(*([100] * 8 + [1500, 1500])))
    assert m["note_length_median"] == 100
    assert m["note_length_p90"] == 1500
    assert m["note_length_gate_passed"] is False


def test_the_gate_thresholds_are_the_documented_ones():
    assert (bl.NOTE_LENGTH_GATE_MEDIAN, bl.NOTE_LENGTH_GATE_P90) == (300, 800)


def test_a_corpus_with_no_notes_reports_no_gate_rather_than_a_failed_one():
    """A missing measurement is not a failed one."""
    m = bl.headline_metrics(sample_baseline())
    assert m["note_length_median"] is None
    assert m["note_length_gate_passed"] is None


def test_a_falling_median_note_length_is_labelled_better():
    row = bl.compare(_notes_baseline(900, 950, 1000), _notes_baseline(100, 150, 200))[
        "metrics"
    ]["note_length_median"]
    assert row["before"] == 950 and row["after"] == 150
    assert row["direction"] == "better"


def test_the_gate_flag_compares_without_pretending_to_have_a_delta():
    """``bool`` is an ``int``; a pass/fail flip is not a numeric movement."""
    row = bl.compare(_notes_baseline(900, 950, 1000), _notes_baseline(100, 150, 200))[
        "metrics"
    ]["note_length_gate_passed"]
    assert row["before"] is False and row["after"] is True
    assert "delta" not in row


def test_a_pre_metric_baseline_still_compares_without_the_note_length_keys(committed):
    """The committed pre-fix capture predates the metric and must still render."""
    m = bl.headline_metrics(committed)
    assert "note_length_median" in m
    assert m["note_length_median"] is None
    assert m["note_length_gate_passed"] is None
    assert "run-log note length" not in bl.format_summary(committed)


def test_the_summary_publishes_the_note_lengths_when_the_report_has_them():
    md = bl.format_summary(_notes_baseline(100, 200, 900))
    assert "run-log note length" in md
    assert "median 200" in md
    assert "FAIL" in md


def test_the_summary_marks_a_passing_gate_as_a_pass():
    md = bl.format_summary(_notes_baseline(150, 200, 250))
    assert "run-log note length" in md
    assert "FAIL" not in md
    assert "pass" in md


# ------------------------------------------------------ guidance-tool usage --
#
# US-PM-13 AC: "Usage of both tools is visible in the next telemetry baseline."
# Visible means a *headline* number, not a row buried in a 32-tool table -- and
# visible when it is zero, because zero is the "before" the next capture is
# argued against.


def _guidance_baseline(*tools_per_session):
    """One session per argument; each argument is that session's tool sequence."""
    calls = []
    for index, tools in enumerate(tools_per_session):
        session = f"sess-{index}"
        calls += [
            make_call(tool=tool, session=session, seq=seq)
            for seq, tool in enumerate(tools)
        ]
    return sample_baseline(calls=calls)


def test_guidance_calls_and_reach_reach_the_headline():
    """Three sessions, `pm_estimate` in one of them -> a third of the corpus."""
    m = bl.headline_metrics(
        _guidance_baseline(
            ["pm_grab", "pm_estimate", "pm_update"], ["pm_grab", "pm_update"], ["pm_get"]
        )
    )
    assert m["pm_estimate_calls"] == 1
    assert m["pm_estimate_sessions_pct"] == 33.3333


def test_an_unused_guidance_tool_publishes_a_visible_zero_not_a_missing_key():
    """A printed 0 is a measurement; an absent key is an unasked question."""
    m = bl.headline_metrics(
        _guidance_baseline(["pm_grab", "pm_estimate"], ["pm_update"], ["pm_get"])
    )
    assert m["pm_context_calls"] == 0
    assert m["pm_context_sessions_pct"] == 0.0


def test_repeat_calls_inside_one_session_raise_calls_but_not_reach():
    m = bl.headline_metrics(_guidance_baseline(["pm_context"] * 5, ["pm_get"]))
    assert m["pm_context_calls"] == 5
    assert m["pm_context_sessions_pct"] == 50.0


def test_more_guidance_calls_is_labelled_better_not_worse():
    """Higher is the win here -- the story exists because these sit near zero."""
    before = _guidance_baseline(["pm_grab", "pm_update"], ["pm_get"])
    after = _guidance_baseline(["pm_grab", "pm_estimate", "pm_update"], ["pm_estimate"])
    metrics = bl.compare(before, after)["metrics"]
    assert metrics["pm_estimate_calls"]["before"] == 0
    assert metrics["pm_estimate_calls"]["after"] == 2
    assert metrics["pm_estimate_calls"]["direction"] == "better"
    assert metrics["pm_estimate_sessions_pct"]["direction"] == "better"


def test_guidance_usage_falling_back_to_zero_is_labelled_worse():
    before = _guidance_baseline(["pm_context"], ["pm_context"])
    after = _guidance_baseline(["pm_get"], ["pm_get"])
    row = bl.compare(before, after)["metrics"]["pm_context_calls"]
    assert row["before"] == 2 and row["after"] == 0
    assert row["direction"] == "worse"


def test_the_higher_is_better_set_is_exactly_the_guidance_headline_keys():
    assert bl.HIGHER_IS_BETTER == {
        "pm_context_calls",
        "pm_estimate_calls",
        "pm_context_sessions_pct",
        "pm_estimate_sessions_pct",
    }
    assert not (bl.HIGHER_IS_BETTER & bl.LOWER_IS_BETTER)


def test_the_headline_measures_the_same_guidance_set_the_report_defines():
    assert bl.GUIDANCE_TOOLS == rp_mod.GUIDANCE_TOOLS


def test_a_pre_metric_baseline_still_compares_without_the_guidance_keys(committed):
    """The committed pre-fix capture predates the metric; keys read ``None``."""
    m = bl.headline_metrics(committed)
    assert "pm_context_calls" in m and "pm_estimate_calls" in m
    assert m["pm_context_calls"] is None
    assert m["pm_estimate_sessions_pct"] is None
    assert "guidance tool usage" not in bl.format_summary(committed)


def test_comparing_a_pre_metric_baseline_forward_does_not_invent_a_delta(committed):
    row = bl.compare(committed, _guidance_baseline(["pm_estimate"]))["metrics"][
        "pm_estimate_calls"
    ]
    assert row["before"] is None and row["after"] == 1
    assert "delta" not in row and "direction" not in row


def test_the_summary_publishes_the_guidance_usage_when_the_report_has_it():
    md = bl.format_summary(
        _guidance_baseline(["pm_estimate", "pm_context"], ["pm_get"], ["pm_get"])
    )
    assert "guidance tool usage" in md
    assert "`pm_context` 1 calls" in md
    assert "`pm_estimate` 1 calls" in md


def test_an_empty_corpus_publishes_zeros_rather_than_crashing():
    m = bl.headline_metrics(sample_baseline(calls=[]))
    assert m["pm_context_calls"] == 0
    assert m["pm_estimate_calls"] == 0
    assert m["pm_context_sessions_pct"] == 0.0
    assert m["pm_estimate_sessions_pct"] == 0.0


# ------------------------------------------------------ the capture window --
#
# US-PM-32: the corpus mixes months of sessions run against different server
# code, and the post-subtraction baseline found 906 of its 941 soft errors were
# one defect (pm_update rejecting a run-log note over 1024 characters) that
# US-PM-1 fixed in Sprint 3. A whole-corpus capture therefore reports a failure
# rate dominated by code that no longer exists.
#
# ``--since`` windows the capture to sessions that started at or after a stated
# moment. The properties that matter are the ones a reader has to be able to
# trust a year later:
#
# * the cutoff is applied to the session's *start*, and inclusively;
# * filtering is per session, never per call -- half a transcript is not a
#   sample of anything;
# * the window is in provenance, so a windowed file can never be mistaken for
#   an unwindowed one;
# * ``--since auto`` derives the cutoff from evidence in the corpus (the
#   post-US-PM-1 ``note_truncated`` response) rather than from a guessed date;
# * and when the corpus holds no such evidence the capture is *refused*, because
#   a silent full capture published under a windowed name is the failure this
#   whole mechanism exists to prevent.

#: The pre-US-PM-1 server's rejection, and the post-fix server's reply. The
#: second is the signature ``--since auto`` dates the window from.
NOTE_TRUNCATED_RESULT = (
    '{"result":"updated:\\n  task:\\n    id: US-X-1\\n    status: done\\n'
    'note_truncated: true\\nnote_original_length: 4600\\nnote_stored_length: 4096"}'
)

#: A *mention* of the flag in prose -- a task body read back by ``pm_get``. This
#: repo is full of them (US-PM-1-3 is literally titled after the flag), so the
#: signature has to be matched as a response field or the window dates itself to
#: whenever someone last read that task.
NOTE_TRUNCATED_PROSE = (
    '{"result":"task:\\n  id: US-PM-1-3\\n  title: Return a note_truncated flag '
    'on the update response\\n  body: surface a note_truncated boolean so an '
    'automated caller can react"}'
)

#: The field itself, but quoted inside a task body read back by ``pm_get`` --
#: evidence pasted into ProjectMan, which this repo does constantly. It looks
#: exactly like a truncation response and is not one; only the *tool* tells them
#: apart.
NOTE_TRUNCATED_QUOTED = (
    '{"result":"task:\\n  id: US-PM-1-5\\n  body: evidence --- the server '
    'replied note_truncated: true, note_original_length: 4600"}'
)

OLD_START = "2026-07-01T09:00:00Z"
CUT_START = "2026-08-21T10:00:00Z"
NEW_START = "2026-09-01T08:00:00Z"

#: What ``--since auto`` should derive from :func:`windowed_corpus`: the *start*
#: of the session that carries the signature, not the timestamp of the call that
#: carries it, so that session is itself inside the window.
CUT_CUTOFF = "2026-08-21T10:00:00+00:00"


def _pair(call_id, tool, timestamp, session, result="ok", is_error=False, tool_input=None):
    """A tool_use record and its tool_result record, both stamped ``timestamp``."""
    return [
        _record(
            [_tool_use(call_id, f"mcp__projectman__{tool}", tool_input)],
            session=session,
            timestamp=timestamp,
        ),
        _record(
            [_tool_result(call_id, result, is_error=is_error)],
            session=session,
            timestamp=timestamp,
        ),
    ]


@pytest.fixture
def windowed_corpus(tmp_path):
    """Three sessions straddling the note-truncation fix.

    * ``sess-old`` starts 2026-07-01, on the pre-fix server: its ``pm_update``
      is *rejected* for an over-long note (the soft error US-PM-1 removed). It
      also has a late call, well after the cutoff, so a filter that worked per
      call instead of per session would leak it into the window.
    * ``sess-cut`` starts 2026-08-21T10:00, and a later call in it carries the
      post-fix ``note_truncated`` response -- this is the session ``--since
      auto`` dates the window from.
    * ``sess-new`` starts 2026-09-01 and is unremarkable.
    """
    root = tmp_path / "projects"
    old = [
        *_pair("o1", "pm_grab", OLD_START, "sess-old"),
        *_pair("o2", "pm_update", "2026-07-01T09:05:00Z", "sess-old",
               result=SOFT_NOTE_LIMIT),
        # Long after the cutoff, but in a session that began before it.
        *_pair("o3", "pm_get", "2026-09-02T12:00:00Z", "sess-old"),
    ]
    cut = [
        *_pair("c1", "pm_grab", CUT_START, "sess-cut"),
        *_pair("c2", "pm_update", "2026-08-21T11:30:00Z", "sess-cut",
               result=NOTE_TRUNCATED_RESULT),
    ]
    new = [
        *_pair("n1", "pm_grab", NEW_START, "sess-new"),
        *_pair("n2", "pm_get", "2026-09-01T08:30:00Z", "sess-new"),
        *_pair("n3", "pm_update", "2026-09-01T08:40:00Z", "sess-new"),
    ]
    _write_transcript(root, "proj", "sess-old", old)
    _write_transcript(root, "proj", "sess-cut", cut)
    _write_transcript(root, "proj", "sess-new", new)
    return root


def _capture(corpus, **kwargs):
    return bl.capture(root=str(corpus), repo=REPO_ROOT, **kwargs)


# ---- the filter itself ----


def test_since_excludes_sessions_that_started_before_the_cutoff(windowed_corpus):
    art = _capture(windowed_corpus, since=CUT_START)
    assert art["report"]["totals"]["sessions"] == 2
    # sess-cut (2) + sess-new (3); sess-old's 3 calls are gone.
    assert art["report"]["totals"]["calls"] == 5
    tools = {row["tool"] for row in art["report"]["by_tool"]}
    assert tools == {"pm_grab", "pm_update", "pm_get"}


def test_since_keeps_a_session_whose_first_timestamp_is_exactly_the_cutoff(
    windowed_corpus,
):
    """"At or after" -- the boundary session is in, not out.

    ``--since auto`` derives the cutoff *from* a session's start, so an
    exclusive boundary would throw away the very session that supplied the
    evidence.
    """
    art = _capture(windowed_corpus, since=CUT_START)
    assert art["report"]["totals"]["sessions"] == 2
    assert art["provenance"]["sessions_excluded"] == 1
    # One second later and the boundary session drops out too.
    later = _capture(windowed_corpus, since="2026-08-21T10:00:01Z")
    assert later["report"]["totals"]["sessions"] == 1
    assert later["report"]["totals"]["calls"] == 3
    assert later["provenance"]["sessions_excluded"] == 2


def test_a_cutoff_before_the_whole_corpus_excludes_nothing(windowed_corpus):
    art = _capture(windowed_corpus, since=OLD_START)
    full = _capture(windowed_corpus)
    assert art["provenance"]["sessions_excluded"] == 0
    assert art["report"]["totals"] == full["report"]["totals"]


def test_the_window_drops_whole_sessions_not_individual_calls(windowed_corpus):
    """``sess-old`` has a call dated after the cutoff; it must still be excluded.

    Calls-per-session, run lengths and bigrams are all statements about a whole
    transcript. Keeping the tail of an excluded session would corrupt every one
    of them while looking, in the totals, like nothing had gone wrong.
    """
    art = _capture(windowed_corpus, since=CUT_START)
    by_tool = {row["tool"]: row["calls"] for row in art["report"]["by_tool"]}
    # sess-old's late ``pm_get`` (2026-09-02, after the cutoff) must not survive;
    # only sess-new's remains.
    assert by_tool["pm_get"] == 1, "a late call from an excluded session leaked in"
    assert bl.headline_metrics(art)["calls"] == 5
    # And the pre-fix rejection that lived only in sess-old is gone with it --
    # which is the entire point of the window.
    assert bl.headline_metrics(art)["soft_errors"] == 0
    assert bl.headline_metrics(_capture(windowed_corpus))["soft_errors"] == 1


def test_a_session_with_no_usable_timestamp_is_excluded(tmp_path):
    """Unknown is not the same as recent, and the window must be provable."""
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-dated", _pair("d1", "pm_get", NEW_START, "sess-dated"))
    _write_transcript(root, "p", "sess-undated", [
        _record([_tool_use("u1", "mcp__projectman__pm_get", {})],
                session="sess-undated", timestamp=None),
        _record([_tool_result("u1", "ok")], session="sess-undated", timestamp=None),
    ])
    art = bl.capture(root=str(root), repo=REPO_ROOT, since="2026-01-01")
    assert art["report"]["totals"]["sessions"] == 1
    assert art["provenance"]["sessions_excluded"] == 1


def test_session_start_times_takes_the_earliest_timestamp_not_the_first_record(tmp_path):
    """One out-of-order record must not make a session look younger than it is."""
    from tools.usage_telemetry.extract import scan

    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-a", [
        *_pair("a1", "pm_get", NEW_START, "sess-a"),
        *_pair("a2", "pm_get", OLD_START, "sess-a"),
    ])
    starts = bl.session_start_times(scan(root=str(root)))
    assert starts["sess-a"] == bl.parse_timestamp(OLD_START)


# ---- provenance ----


def test_provenance_records_the_window_and_the_number_of_excluded_sessions(
    windowed_corpus,
):
    prov = _capture(windowed_corpus, since=CUT_START)["provenance"]
    assert prov["window_since"] == CUT_CUTOFF
    assert prov["sessions_excluded"] == 1
    assert prov["sessions"] == 2


def test_provenance_says_null_rather_than_zero_when_no_window_was_applied(
    windowed_corpus,
):
    """``0 excluded`` would claim a window was applied and matched everything.

    A reader comparing a windowed capture against an unwindowed one has to be
    able to tell which is which from the file alone.
    """
    prov = _capture(windowed_corpus)["provenance"]
    assert "window_since" in prov and "sessions_excluded" in prov
    assert prov["window_since"] is None
    assert prov["sessions_excluded"] is None


def test_the_windowed_corpus_block_counts_only_the_windowed_transcripts(
    windowed_corpus,
):
    """One session is one transcript file, so the two counts move together."""
    art = _capture(windowed_corpus, since=CUT_START)
    assert art["provenance"]["transcript_files"] == 2
    assert art["report"]["corpus"]["files_scanned"] == 2
    assert bl.headline_metrics(art)["transcript_files"] == 2


def test_the_summary_publishes_the_window_only_when_there_is_one(windowed_corpus):
    windowed = bl.format_summary(_capture(windowed_corpus, since=CUT_START))
    assert "capture window" in windowed
    assert CUT_CUTOFF in windowed
    assert "1 earlier sessions excluded" in windowed
    assert "This capture is windowed" in windowed

    full = bl.format_summary(_capture(windowed_corpus))
    assert "capture window" not in full
    assert "This capture is windowed" not in full


def test_a_committed_baseline_taken_before_the_window_existed_still_renders(committed):
    """Every unwindowed artifact must render exactly as it always did."""
    assert "capture window" not in bl.format_summary(committed)
    assert bl.headline_metrics(committed)["calls"] == PRE_FIX["calls"]


# ---- --since auto ----


def test_since_auto_derives_the_cutoff_from_the_earliest_note_truncated_response(
    windowed_corpus,
):
    """The window starts where the corpus proves the fixed server was running.

    The evidence call is at 11:30, an hour into ``sess-cut``; the cutoff is the
    session's 10:00 start, so the session that supplies the evidence is inside
    its own window.
    """
    art = _capture(windowed_corpus, since="auto")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 1
    assert art["report"]["totals"]["sessions"] == 2
    explicit = _capture(windowed_corpus, since=CUT_START)
    assert art["report"]["totals"] == explicit["report"]["totals"]


def test_since_auto_is_case_insensitive(windowed_corpus):
    assert (
        _capture(windowed_corpus, since="AUTO")["provenance"]["window_since"]
        == CUT_CUTOFF
    )


def test_since_auto_picks_the_earliest_marked_session_not_the_last(tmp_path):
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-first", [
        *_pair("f1", "pm_update", CUT_START, "sess-first", result=NOTE_TRUNCATED_RESULT),
    ])
    _write_transcript(root, "p", "sess-later", [
        *_pair("l1", "pm_update", NEW_START, "sess-later", result=NOTE_TRUNCATED_RESULT),
    ])
    art = bl.capture(root=str(root), repo=REPO_ROOT, since="auto")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 0


def test_prose_mentioning_the_flag_is_not_read_as_the_signature(tmp_path):
    """The signature is a response *field*, not the word appearing somewhere.

    This is not hypothetical: the flag is named in several task bodies in this
    repo (US-PM-1-3 is titled after it), and those bodies come back through
    ``pm_update`` responses. A substring match would date the window to whenever
    someone last touched one of them -- an old session, which would silently
    widen the window back to almost the whole corpus.
    """
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-prose", [
        *_pair("p1", "pm_update", OLD_START, "sess-prose", result=NOTE_TRUNCATED_PROSE),
    ])
    _write_transcript(root, "p", "sess-real", [
        *_pair("r1", "pm_update", CUT_START, "sess-real", result=NOTE_TRUNCATED_RESULT),
    ])
    art = bl.capture(root=str(root), repo=REPO_ROOT, since="auto")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 1


def test_the_signature_is_only_read_from_a_tool_that_can_emit_it(tmp_path):
    """A task body quoting a truncation response is not a truncation response.

    ``pm_get`` returns whatever text a human pasted into the item. That text can
    carry the field verbatim -- evidence pasted into a task -- and reading it as
    the server's own reply would date the fix to whenever that task was last
    read. Only the note-writing tools in ``NOTE_TRUNCATION_TOOLS`` can actually
    emit the field.
    """
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-quoted", [
        *_pair("q1", "pm_get", OLD_START, "sess-quoted", result=NOTE_TRUNCATED_QUOTED),
    ])
    _write_transcript(root, "p", "sess-real", [
        *_pair("r1", "pm_update", CUT_START, "sess-real", result=NOTE_TRUNCATED_RESULT),
    ])
    art = bl.capture(root=str(root), repo=REPO_ROOT, since="auto")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 1
    assert "pm_get" not in bl.NOTE_TRUNCATION_TOOLS
    assert "pm_update" in bl.NOTE_TRUNCATION_TOOLS


def test_since_auto_errors_when_no_session_carries_the_signature(tmp_path):
    """The headline requirement: no evidence means no capture, not a full one.

    A whole-corpus capture published under a windowed name is exactly the claim
    US-PM-32 exists to stop being made by accident.
    """
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-old", [
        *_pair("x1", "pm_update", OLD_START, "sess-old", result=SOFT_NOTE_LIMIT),
    ])
    with pytest.raises(bl.WindowError) as exc:
        bl.capture(root=str(root), repo=REPO_ROOT, since="auto")
    message = str(exc.value)
    assert "note_truncated" in message
    assert "--since" in message


def test_since_rejects_a_value_that_is_not_a_timestamp(windowed_corpus):
    with pytest.raises(bl.WindowError) as exc:
        _capture(windowed_corpus, since="last tuesday")
    assert "ISO-8601" in str(exc.value)


def test_since_accepts_a_bare_date_and_reads_it_as_utc(windowed_corpus):
    art = _capture(windowed_corpus, since="2026-08-21")
    assert art["provenance"]["window_since"] == "2026-08-21T00:00:00+00:00"
    assert art["provenance"]["sessions_excluded"] == 1


def test_a_naive_timestamp_is_read_as_utc_not_local_time(windowed_corpus):
    assert bl.parse_timestamp("2026-08-21T10:00:00") == bl.parse_timestamp(CUT_START)


def test_the_match_rate_guard_runs_before_the_window(tmp_path, capsys):
    """A broken join must not be hidden by excluding the sessions it broke in.

    The join rate is a property of the extractor and the corpus. If a window
    could suppress it, the guard would be defeatable by narrowing the capture.
    """
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-old", [
        _record([_tool_use("u1", "mcp__projectman__pm_update", {})],
                session="sess-old", timestamp=OLD_START),
    ])
    _write_transcript(root, "p", "sess-new", _pair("n1", "pm_get", NEW_START, "sess-new"))
    with pytest.raises(MatchRateError):
        bl.capture(root=str(root), repo=REPO_ROOT, since=NEW_START, min_match_rate=0.99)


# ---- the cli ----


def test_cli_capture_since_writes_a_windowed_artifact(windowed_corpus, tmp_path, capsys):
    out = tmp_path / "t"
    rc = _cli("capture", "--root", str(windowed_corpus), "--out-dir", str(out),
              "--name", "windowed", "--label", "windowed-post-fix",
              "--since", CUT_START)
    assert rc == 0
    art = bl.load_baseline(out / "windowed.json")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 1
    assert art["report"]["totals"]["calls"] == 5
    text = capsys.readouterr().out
    assert "window: sessions at or after" in text
    assert "1 earlier sessions excluded" in text
    assert "capture window" in (out / "windowed.md").read_text(encoding="utf-8")


def test_cli_capture_since_auto_writes_a_windowed_artifact(windowed_corpus, tmp_path, capsys):
    out = tmp_path / "t"
    rc = _cli("capture", "--root", str(windowed_corpus), "--out-dir", str(out),
              "--name", "auto", "--since", "auto")
    assert rc == 0
    art = bl.load_baseline(out / "auto.json")
    assert art["provenance"]["window_since"] == CUT_CUTOFF
    assert art["provenance"]["sessions_excluded"] == 1


def test_cli_capture_since_auto_fails_loudly_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-old", [
        *_pair("x1", "pm_update", OLD_START, "sess-old", result=SOFT_NOTE_LIMIT),
    ])
    out = tmp_path / "never"
    rc = _cli("capture", "--root", str(root), "--out-dir", str(out), "--since", "auto")
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err and "note_truncated" in err
    assert not out.exists(), "a refused capture must not leave an artifact behind"


def test_cli_capture_rejects_an_unparseable_since_without_writing(tmp_path, capsys):
    root = tmp_path / "projects"
    _write_transcript(root, "p", "sess-a", _pair("a1", "pm_get", NEW_START, "sess-a"))
    out = tmp_path / "never"
    rc = _cli("capture", "--root", str(root), "--out-dir", str(out),
              "--since", "yesterday")
    assert rc == 1
    assert "ISO-8601" in capsys.readouterr().err
    assert not out.exists()


def test_cli_capture_says_the_window_emptied_the_corpus_rather_than_calls_found(
    windowed_corpus, tmp_path, capsys
):
    """Exit 2 still, but the message must name the real cause.

    "no mcp__projectman__* calls found" against a corpus full of them would send
    the reader looking for a broken extractor instead of a too-late cutoff.
    """
    out = tmp_path / "never"
    rc = _cli("capture", "--root", str(windowed_corpus), "--out-dir", str(out),
              "--since", "2030-01-01")
    assert rc == 2
    err = capsys.readouterr().err
    assert "--since" in err and "excluded 3 sessions" in err
    assert not out.exists()


def test_the_windowed_capture_is_still_the_report_of_its_own_corpus(windowed_corpus):
    """Windowing must filter the input, not reinterpret the analysis.

    Capturing with a window has to equal running ``report`` over exactly the
    sessions the window keeps -- otherwise ``--since`` is a second definition of
    the metrics rather than a narrower corpus.
    """
    from tools.usage_telemetry.extract import scan
    from tools.usage_telemetry.report import report_from_extraction

    scanned = scan(root=str(windowed_corpus))
    filtered, window = bl.filter_extraction_since(scanned, bl.parse_timestamp(CUT_START))
    direct = report_from_extraction(filtered).as_dict()
    art = _capture(windowed_corpus, since=CUT_START)
    assert art["report"] == direct
    assert window["sessions_kept"] == 2
    assert scanned.total_calls == 8, "filtering must not mutate the scan it read"


# -- (7) the US-PM-32 windowed baseline -------------------------------------
#
# Two guards, one per sibling verify criterion:
#   US-PM-32-2 -- the pair of artifacts exists, carries a real window, and the
#                 markdown actually compares against *both* committed baselines;
#   US-PM-32-3 -- the markdown states a verdict, from a closed vocabulary, for
#                 every Sprint 1-9 claim.
#
# They are deliberately about the *document*, not about the numbers in it. The
# numbers move whenever the window is re-taken; what must not move is that the
# comparison names what it compares and refuses to leave a claim unjudged.

#: The only words a verdict may use. A free-text verdict ("mostly", "probably
#: better") is unreadable as a result, and "improved" hides whether the window
#: had anything to measure -- ``inconclusive`` exists precisely so that an
#: absent tool cannot be written up as a win.
VERDICT_VOCABULARY = frozenset({"holds", "does not hold", "inconclusive"})

#: claim -> substrings that identify its row in the verdict table.
SPRINT_CLAIMS: dict[str, tuple[str, ...]] = {
    "fewer calls per task": ("calls per task",),
    "less context per worker": ("context per worker",),
    "shorter pm_update runs": ("pm_update", "run"),
    "shorter pm_archive runs": ("pm_archive", "run"),
    "fewer failures": ("failure",),
}


@pytest.fixture(scope="module")
def windowed():
    """The US-PM-32 windowed baseline specifically."""
    json_path, md_path = COMMITTED_BASELINES["windowed-post-fix"]
    return CommittedBaseline("windowed-post-fix", json_path, md_path)


def _table_rows(markdown: str) -> list[list[str]]:
    """Every markdown table row, as its stripped cells."""
    rows = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):  # the --- separator row
            continue
        rows.append(cells)
    return rows


def _verdict_section(markdown: str) -> str:
    """The verdict section only.

    Scoped deliberately: the three-way headline table elsewhere in the document
    also has rows naming ``pm_update_longest_run``, and a whole-file search would
    happily accept a delta cell as a verdict.
    """
    marker = "## Verdicts on the Sprint 1 to 9 claims"
    assert marker in markdown, f"the windowed markdown must contain {marker!r}"
    body = markdown.split(marker, 1)[1]
    for stop in ("\n### ", "\n## "):
        body = body.split(stop, 1)[0]
    return body


def test_the_windowed_baseline_exists_as_a_json_and_markdown_pair(windowed):
    """US-PM-32-2, first part."""
    for path in (windowed.json_path, windowed.md_path):
        assert path.is_file(), f"missing windowed artifact: {path}"
        assert path.stat().st_size > 0
    assert windowed.provenance["label"] == "windowed-post-fix"


def test_the_windowed_baseline_json_records_the_window_it_was_taken_through(windowed):
    """US-PM-32-2: a file named "windowed" that carries no window is a lie.

    ``window_since`` must be a real, parseable, aware moment and
    ``sessions_excluded`` a real count -- ``None`` in either means the capture
    was taken over the whole corpus and published under a windowed name, which
    is the exact failure ``--since`` exists to prevent.
    """
    prov = windowed.provenance
    since = prov.get("window_since")
    assert isinstance(since, str) and since, "window_since must be set"
    cutoff = datetime.fromisoformat(since)
    assert cutoff.tzinfo is not None, "an ambiguous cutoff windows nothing reproducibly"

    excluded = prov.get("sessions_excluded")
    assert isinstance(excluded, int) and not isinstance(excluded, bool)
    assert excluded >= 0, excluded

    # The window has to be inside the corpus it was carved from, and has to have
    # left something behind: a capture with 0 sessions is not a measurement.
    assert prov["sessions"] > 0
    assert cutoff <= datetime.fromisoformat(prov["captured_at"])


def test_the_windowed_markdown_compares_against_both_committed_baselines(windowed):
    """US-PM-32-2: it must name both baselines *and* both their commits.

    Naming the files alone would be satisfied by a "see also" line. The commit
    is what makes a comparison checkable a year later, so both sides' commits
    have to be on the page next to the claim they support.
    """
    md = windowed.markdown()
    for label in ("pre-fix", "post-subtraction"):
        json_path, md_path = COMMITTED_BASELINES[label]
        assert json_path.name in md, f"{json_path.name} is not named in the comparison"
        other = bl.load_baseline(json_path)
        commit = other["provenance"]["git"]["commit"]
        assert commit in md or commit[:12] in md, (
            f"the {label} baseline's commit {commit[:12]} is not on the page"
        )
        assert other["provenance"]["label"] in md, label
    # Both sides' headline numbers, not just their names.
    for label in ("pre-fix", "post-subtraction"):
        other = bl.load_baseline(COMMITTED_BASELINES[label][0])
        assert f"{other['report']['totals']['sessions']:,}" in md, label
        assert f"{bl.headline_metrics(other)['failure_rate_pct']:.2f}%" in md, label


def test_the_windowed_markdown_states_a_verdict_for_every_sprint_claim(windowed):
    """US-PM-32-3: no Sprint 1-9 claim may be left unjudged."""
    section = _verdict_section(windowed.markdown())
    rows = _table_rows(section)
    assert rows, "the verdict section must contain a table"

    unjudged = []
    for claim, needles in SPRINT_CLAIMS.items():
        matches = [
            row
            for row in rows
            if all(n.lower() in row[0].lower() for n in needles)
        ]
        if not matches:
            unjudged.append(claim)
            continue
        for row in matches:
            verdict = row[-1].replace("*", "").replace("`", "").strip().lower()
            assert verdict in VERDICT_VOCABULARY, (
                f"{claim!r} is judged {verdict!r}, which is not one of "
                f"{sorted(VERDICT_VOCABULARY)}"
            )
    assert not unjudged, f"claims with no verdict row: {unjudged}"


def test_every_verdict_uses_the_closed_vocabulary(windowed):
    """US-PM-32-3: and nothing in the table may invent a fourth verdict."""
    rows = _table_rows(_verdict_section(windowed.markdown()))
    header, body = rows[0], rows[1:]
    assert header[-1].strip().lower() == "verdict", header
    verdicts = {
        row[-1].replace("*", "").replace("`", "").strip().lower() for row in body
    }
    assert verdicts, "the verdict table has no rows"
    assert verdicts <= VERDICT_VOCABULARY, (
        f"verdicts outside the vocabulary: {sorted(verdicts - VERDICT_VOCABULARY)}"
    )


def test_the_windowed_markdown_does_not_read_an_absent_tool_as_a_win(windowed):
    """The one way this document could mislead while passing every other check.

    ``pm_archive`` was never called inside the window, so its longest run reads
    ``0`` and ``compare`` labels ``26 -> 0`` "better". That is arithmetic, not
    evidence, and the write-up has to say so rather than bank it as a win.
    """
    metrics = bl.headline_metrics(windowed.data)
    if metrics.get("pm_archive_longest_run"):
        pytest.skip("the window now contains pm_archive calls; re-read the verdict")
    calls = {t["tool"]: t["calls"] for t in windowed.data["report"]["by_tool"]}
    assert calls.get("pm_archive", 0) == 0

    rows = _table_rows(_verdict_section(windowed.markdown()))
    archive = [r for r in rows if "pm_archive" in r[0]]
    assert archive, "no pm_archive verdict row"
    for row in archive:
        verdict = row[-1].replace("*", "").replace("`", "").strip().lower()
        assert verdict == "inconclusive", (
            f"pm_archive was never called in the window but is judged {verdict!r}"
        )
