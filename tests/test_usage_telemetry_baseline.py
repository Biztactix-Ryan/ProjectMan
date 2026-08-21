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
from tools.usage_telemetry.extract import ToolCall, ToolResult

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
    assert before == after, "capturing a baseline must never touch git state"


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
    """The real artifact, parsed. Fails (never skips) when it is missing."""
    assert COMMITTED.exists(), (
        f"the pre-fix baseline must exist at {COMMITTED.relative_to(REPO_ROOT)}"
    )
    return bl.load_baseline(COMMITTED)


# -- (1) it exists at its documented path and is committable ----------------


def test_all_three_baseline_artifacts_exist_at_their_documented_paths():
    """The AC is about a captured artifact, so absence is a failure, not a skip."""
    for path in (COMMITTED, COMMITTED_MD, COMMITTED_README):
        assert path.is_file(), f"missing baseline artifact: {path}"
        assert path.stat().st_size > 0, f"empty baseline artifact: {path}"
    # A truncated or stub JSON would still be a file; the real capture is large.
    assert COMMITTED.stat().st_size > 10_000
    # The README is the documentation the path claim rests on.
    readme = COMMITTED_README.read_text(encoding="utf-8")
    assert "baseline-pre-fix.json" in readme
    assert "baseline-pre-fix.md" in readme


def test_the_baseline_lives_inside_the_repo_not_a_temp_or_scratch_directory():
    """A baseline in /tmp is not a baseline; it is a number someone once saw."""
    resolved = COMMITTED.resolve()
    rel = resolved.relative_to(REPO_ROOT.resolve())  # raises if outside the repo
    assert rel == Path("docs/telemetry/baseline-pre-fix.json")
    lowered = str(resolved).lower()
    for scratch in ("/tmp/", "/var/tmp/", "scratchpad", "/.venv/", "node_modules"):
        assert scratch not in lowered, f"baseline sits under a scratch path: {scratch}"


def test_the_baseline_artifacts_are_not_gitignored_so_they_can_be_committed():
    """``git check-ignore`` exits 1 when a path is *not* ignored.

    This is the committable half of "captured and committed": a file the repo
    would silently refuse to track could never satisfy the AC, and that failure
    mode is invisible until someone tries to commit.
    """
    for path in (COMMITTED, COMMITTED_MD, COMMITTED_README):
        proc = _git("check-ignore", "-v", "--no-index", str(path))
        assert proc.returncode == 1, (
            f"{path.relative_to(REPO_ROOT)} is gitignored: {proc.stdout.strip()}"
        )


def test_git_sees_the_baseline_as_content_to_track():
    """Either already tracked, or untracked-and-addable -- never ignored.

    Passes both before the human commits (``??``) and forever after (empty
    porcelain status, i.e. tracked and clean).
    """
    proc = _git("status", "--porcelain", "--ignored", "--", str(COMMITTED))
    assert proc.returncode == 0, proc.stderr
    status = proc.stdout.strip()
    assert not status.startswith("!!"), f"git reports the baseline ignored: {status}"
    if status:
        assert status.split()[0] in {"??", "A", "M", "AM", "??"}, status
    else:  # tracked and clean
        assert _git("ls-files", "--error-unmatch", str(COMMITTED)).returncode == 0


# -- (2) it parses and conforms to its schema -------------------------------


def test_the_committed_baseline_parses_as_json_and_declares_its_schema(committed):
    assert committed["schema"] == bl.SCHEMA == "projectman.usage-telemetry.baseline/1"
    assert set(committed) == {"schema", "provenance", "report"}


def test_the_committed_baseline_conforms_to_the_artifact_schema(committed):
    """Every field a reader dereferences, with the type they will assume."""
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
    assert set(prov) == set(expected)
    for key, kind in expected.items():
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


def test_the_committed_baseline_survives_a_load_write_load_round_trip(tmp_path, committed):
    """Re-emitting it byte-for-byte proves nothing was hand-edited into it."""
    json_path, md_path = bl.write_baseline(committed, tmp_path, "baseline-pre-fix")
    assert bl.load_baseline(json_path) == committed
    assert json_path.read_text(encoding="utf-8") == COMMITTED.read_text(encoding="utf-8")
    # The markdown is a pure function of the JSON, so a stale .md is detectable.
    assert md_path.read_text(encoding="utf-8") == COMMITTED_MD.read_text(encoding="utf-8")


def test_an_empty_or_corrupt_artifact_would_be_rejected_rather_than_compared(tmp_path):
    """The schema guard has to bite, or every test above tests nothing."""
    for payload in ("", "   ", "[]", "null", '{"totals": {"calls": 1}}'):
        path = tmp_path / "bad.json"
        path.write_text(payload, encoding="utf-8")
        with pytest.raises((ValueError, json.JSONDecodeError)):
            bl.load_baseline(path)


# -- (3) it carries the provenance a "before" measurement needs -------------


def test_the_committed_baseline_records_when_and_against_what_it_was_captured(committed):
    prov = committed["provenance"]

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


def test_the_committed_baseline_pins_the_code_that_produced_it(committed):
    git = committed["provenance"]["git"]
    commit = git["commit"]
    assert isinstance(commit, str) and len(commit) == 40
    assert all(c in "0123456789abcdef" for c in commit), commit
    assert git["branch"]
    assert isinstance(git["dirty"], bool), "dirty must never be unknown for the deliverable"
    assert Path(git["repo"]).resolve() == REPO_ROOT.resolve()

    kind = _git("cat-file", "-t", commit)
    if kind.returncode != 0:  # shallow clone / object pruned
        pytest.skip("recorded commit not present in this clone")
    assert kind.stdout.strip() == "commit"


def test_provenance_counts_agree_with_the_report_they_summarise(committed):
    """Provenance is a copy of report numbers; a drift would mislead a reader."""
    prov, report = committed["provenance"], committed["report"]
    assert prov["calls"] == report["totals"]["calls"]
    assert prov["sessions"] == report["totals"]["sessions"]
    assert prov["matched_calls"] == report["totals"]["matched"]
    assert prov["unmatched_calls"] == report["totals"]["unmatched"]
    assert prov["transcript_files"] == report["corpus"]["files_scanned"]
    assert prov["corpus_root"] == report["corpus"]["root"]
    assert prov["match_rate"] == report["corpus"]["match_rate"]


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

    Cross-checked against the four Study/ appendices -- 6.26% combined failure
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
