"""Capture, describe and compare usage-telemetry baselines (US-PM-6-9).

A *baseline* is the JSON report from :mod:`tools.usage_telemetry.report` wrapped
in a ``provenance`` block that records **when** it was taken, **which corpus** it
was taken from and **which commit the analysis code was at**. Without that block
a stored report is just numbers: a later run could differ because the fixes
worked, because the corpus grew, or because the analysis changed, and nothing in
the file would tell you which.

Nothing here changes ``extract``/``classify``/``report`` behaviour -- this module
only consumes their public API and adds the wrapper, the markdown rendering and
the comparison.

Usage::

    python -m tools.usage_telemetry.baseline capture \\
        --out-dir docs/telemetry --name baseline-pre-fix --label pre-fix
    python -m tools.usage_telemetry.baseline capture \\
        --since auto --name baseline-windowed-post-fix --label windowed-post-fix
    python -m tools.usage_telemetry.baseline compare docs/telemetry/baseline-pre-fix.json

``compare`` takes a live capture by default, so the second command answers "what
has moved since the baseline" with no extra bookkeeping. Pass a second path to
diff two stored files instead.

The corpus is **live**: it is the local Claude transcript tree, and it keeps
growing while work proceeds -- including the calls made by the session that runs
this command. Two captures therefore never share a denominator. Every comparison
prints the corpus delta alongside the metric delta for exactly that reason, and
:func:`format_summary` says so in the artifact itself.

It is also **long**: it mixes sessions run against months of different server
code. ``--since`` (US-PM-32) windows a capture to sessions that started at or
after a stated moment, so a defect that was fixed part-way through the corpus
stops dominating the whole-corpus rates. ``--since auto`` derives that moment
from the corpus itself -- the start of the earliest session whose response
carries the post-US-PM-1 ``note_truncated`` field -- rather than from a guessed
date. The window is recorded in provenance (``window_since``,
``sessions_excluded``), because a windowed capture is not comparable to an
unwindowed one and nothing else in the file would say so.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from tools.usage_telemetry.extract import (
    Extraction,
    MatchRateError,
    ScanStats,
    TOOL_PREFIX,
    ToolCall,
    scan,
)
from tools.usage_telemetry import report as report_mod
from tools.usage_telemetry.report import UsageReport, report_from_extraction

#: Bumped only when the artifact layout changes incompatibly.
SCHEMA = "projectman.usage-telemetry.baseline/1"

#: Default label. "pre-fix" marks the capture taken before the epic's fixes land.
DEFAULT_LABEL = "pre-fix"

DEFAULT_OUT_DIR = "docs/telemetry"


# ------------------------------------------------------------------ window --

#: ``--since`` value asking for the cutoff to be derived from the corpus.
SINCE_AUTO = "auto"

#: Tools whose response can carry the ``note_truncated`` field. ``server.py``
#: merges ``_note_truncation_fields`` into every tool that accepts a run-log
#: note, so the signature is not unique to ``pm_update`` -- but it *is* limited
#: to this family, and restricting to it keeps a task body that merely mentions
#: the flag (this repo has several) from being read as evidence.
NOTE_TRUNCATION_TOOLS: tuple[str, ...] = (
    "pm_update",
    "pm_update_many",
    "pm_done_next",
    "pm_release",
    "pm_accept",
    "pm_retry",
)

#: The post-US-PM-1 signature, matched as a *field* rather than as prose. A
#: response says ``note_truncated: true`` (YAML) or ``"note_truncated": true``
#: (JSON); a story body says "returns a note_truncated flag", and that must not
#: date the window.
_NOTE_TRUNCATED_FIELD = re.compile(r'"?note_truncated"?\s*[:=]\s*true', re.IGNORECASE)


class WindowError(ValueError):
    """The requested capture window could not be resolved.

    Raised rather than falling back to a full capture: a ``--since`` that cannot
    be honoured must not quietly produce the whole-corpus numbers under a name
    that claims to be windowed.
    """


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a transcript timestamp to an aware UTC datetime; ``None`` if unusable.

    Transcript records carry RFC-3339 with a ``Z`` suffix, which
    ``datetime.fromisoformat`` only accepts from 3.11 -- the project supports
    3.10, so the suffix is normalised here. A naive value is read as UTC, which
    is what the transcripts mean and what a human typing ``--since 2026-08-21``
    means too.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_since(value: str) -> datetime:
    """``--since`` as an explicit moment. Raises :class:`WindowError` on junk."""
    moment = parse_timestamp(value)
    if moment is None:
        raise WindowError(
            f"--since {value!r} is not an ISO-8601 moment. Give a date "
            "(2026-08-21), a full timestamp (2026-08-21T14:03:00Z), or 'auto' "
            "to derive the cutoff from the corpus."
        )
    return moment


def session_start_times(extraction: Extraction) -> dict[str, datetime | None]:
    """Earliest usable timestamp per session, keyed by transcript stem.

    The session unit is ``ToolCall.session`` -- one transcript file -- for the
    same reason run analysis uses it: a ``session_id`` can span several files,
    and merging those would give a resumed session the start time of its first
    incarnation.

    The value is the *minimum* over the session's calls rather than the first in
    sequence order, so a transcript with one out-of-order record cannot report a
    start later than a call it actually contains. ``None`` means the session has
    no parseable timestamp at all -- unknown, which is not the same as old.
    """
    starts: dict[str, datetime | None] = {}
    for call in extraction.calls:
        known = starts.setdefault(call.session, None)
        moment = parse_timestamp(call.timestamp)
        if moment is None:
            continue
        if known is None or moment < known:
            starts[call.session] = moment
    return starts


def _carries_note_truncated(call: ToolCall) -> bool:
    """Whether ``call``'s result is a post-US-PM-1 truncation response."""
    if call.tool not in NOTE_TRUNCATION_TOOLS:
        return False
    if call.result is None:
        return False
    return bool(_NOTE_TRUNCATED_FIELD.search(call.result.text))


def note_truncated_cutoff(extraction: Extraction) -> datetime:
    """Start of the earliest session whose response carries ``note_truncated``.

    US-PM-1 replaced "run-log note must be 1024 characters or fewer" (a soft
    error, and 906 of the 941 soft errors in the post-subtraction baseline) with
    server-side truncation plus a ``note_truncated`` flag. The first session that
    saw the flag is therefore the first session provably run against fixed code,
    which is a cutoff *read off the corpus* instead of guessed from a commit date
    that says nothing about when the installed server was refreshed.

    The cutoff is that session's **start**, so the session that supplies the
    evidence is itself inside the window.

    Raises:
        WindowError: when no session carries the signature. The corpus then
            cannot date the fix, and a silent full capture would be a lie.
    """
    starts = session_start_times(extraction)
    candidates = [
        start
        for call in extraction.calls
        if _carries_note_truncated(call)
        for start in (starts.get(call.session),)
        if start is not None
    ]
    if not candidates:
        raise WindowError(
            "--since auto could not derive a cutoff: no session in "
            f"{extraction.root} carries a `note_truncated: true` response from "
            f"{', '.join(NOTE_TRUNCATION_TOOLS)}, so the corpus cannot say when "
            "the US-PM-1 note-truncation fix reached the running server. Pass an "
            "explicit --since <ISO-8601> instead of capturing the whole corpus."
        )
    return min(candidates)


def resolve_since(value: str | datetime, extraction: Extraction) -> datetime:
    """Turn a ``--since`` argument into a concrete cutoff."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if str(value).strip().lower() == SINCE_AUTO:
        return note_truncated_cutoff(extraction)
    return parse_since(str(value))


def filter_extraction_since(
    extraction: Extraction, cutoff: datetime
) -> tuple[Extraction, dict[str, Any]]:
    """Drop whole sessions that started before ``cutoff``.

    Filtering is per *session*, not per call: half a session is not a sample of
    anything, and calls-per-session, run lengths and bigrams all become nonsense
    if a transcript is cut in the middle.

    A session with no parseable timestamp is excluded. It cannot be shown to be
    inside the window, and the window exists precisely to be able to say that
    everything counted is.

    ``files_scanned`` is reduced by the number of excluded sessions so the
    corpus block describes the window rather than the tree it was carved from --
    one session is one transcript file, so the two counts move together.

    Returns:
        The filtered extraction and a window record for provenance.
    """
    starts = session_start_times(extraction)
    kept = {
        session
        for session, start in starts.items()
        if start is not None and start >= cutoff
    }
    excluded = [session for session in starts if session not in kept]
    calls = [call for call in extraction.calls if call.session in kept]

    stats = ScanStats(**extraction.stats.as_dict())
    stats.files_scanned = max(0, stats.files_scanned - len(excluded))

    filtered = Extraction(
        calls=calls,
        results={
            call.tool_use_id: call.result for call in calls if call.result is not None
        },
        stats=stats,
        tool_prefix=extraction.tool_prefix,
        root=extraction.root,
    )
    window = {
        "since": cutoff.isoformat(),
        "sessions_excluded": len(excluded),
        "sessions_kept": len(kept),
    }
    return filtered, window


# ------------------------------------------------------------- provenance --


def _git(repo: Path, *args: str) -> str | None:
    """Read-only git query. ``None`` when git is absent or ``repo`` is not one.

    A *successful* query that simply had nothing to say returns ``""``, not
    ``None`` -- collapsing the two would make a clean tree indistinguishable from
    an unreadable one, and ``git_provenance`` reports that difference.

    This module never writes git state -- capturing a baseline must not commit,
    stage or otherwise mutate the tree it is describing.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _repo_relative_path(repo: Path) -> str | None:
    """``repo`` expressed relative to its own git root -- ``"."`` for the root.

    The commit SHA is what actually pins the code; the path only says *where in
    that tree* the capture was taken. Recording it absolutely pinned the baseline
    to one machine's directory layout, so any other checkout read a path that
    does not exist there. A relative path says the same thing and stays true in
    every clone.

    ``None`` when the git root cannot be read -- same "unknown" convention the
    other fields use.
    """
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top:
        return None
    try:
        return repo.resolve().relative_to(Path(top).resolve()).as_posix()
    except (OSError, ValueError):
        return None


def git_provenance(repo: Path) -> dict[str, Any]:
    """Commit, branch and dirty flag for ``repo``.

    ``dirty`` matters: a baseline captured from a tree with uncommitted analysis
    changes is not reproducible from ``commit`` alone, and the reader deserves to
    know that before trusting a comparison against it.
    """
    commit = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(repo, "status", "--porcelain")
    return {
        # Relative to the git root ("." for the root itself): an absolute path
        # here would be true only on the machine that captured the baseline.
        "repo": _repo_relative_path(repo),
        # An empty answer to either of these means no usable value: keep the
        # long-standing ``None`` for "unknown" rather than an empty string.
        "commit": commit or None,
        "branch": branch or None,
        # None (not False) when git could not be read: unknown != clean.  An
        # empty porcelain listing is a read that succeeded and found nothing,
        # which is exactly what "clean" means.
        "dirty": None if status is None else bool(status),
    }


def build_provenance(
    report: UsageReport,
    *,
    repo: Path,
    label: str = DEFAULT_LABEL,
    note: str | None = None,
    captured_at: datetime | None = None,
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The self-describing header stored alongside the raw report.

    ``window`` is :func:`filter_extraction_since`'s record, or ``None`` for a
    whole-corpus capture. Both keys are always emitted -- ``None`` meaning "no
    window", a number meaning "this many sessions were deliberately left out" --
    so a comparison against an older file lines up and a reader can never mistake
    a windowed capture for an unwindowed one.
    """
    moment = captured_at or datetime.now(timezone.utc)
    corpus = report.extraction_summary or {}
    win = window or {}
    return {
        "label": label,
        "note": note,
        "captured_at": moment.isoformat(),
        "corpus_root": corpus.get("root"),
        "tool_prefix": corpus.get("tool_prefix"),
        "transcript_files": corpus.get("files_scanned"),
        "calls": report.total_calls,
        "matched_calls": report.matched_calls,
        "unmatched_calls": report.unmatched_calls,
        "match_rate": corpus.get("match_rate"),
        "sessions": report.sessions,
        # US-PM-32: the capture window. ``None`` when the whole corpus was taken.
        "window_since": win.get("since"),
        "sessions_excluded": win.get("sessions_excluded"),
        "git": git_provenance(repo),
        "generator": "python -m tools.usage_telemetry.baseline capture",
        "corpus_is_live": True,
    }


def measure_tool_list() -> dict[str, Any] | None:
    """The ``tools/list`` payload sizes, or ``None`` if they cannot be taken.

    US-PM-15 gates three tool families, and US-PM-15-7 records the saving as a
    number. That number is a property of the *code*, not of the transcript
    corpus, so it is measured here at capture time rather than derived from the
    report.

    Imported lazily and never allowed to fail the capture: telemetry analysis
    must still run in a checkout where ``projectman`` and the ``mcp`` package
    are not importable, and a missing block reads as ``None`` in the headline
    exactly like any other metric added after a baseline was taken.
    """
    try:
        from tools.usage_telemetry.tool_list_size import measure

        return measure()
    except Exception:
        return None


def build_baseline(
    report: UsageReport,
    *,
    repo: Path,
    label: str = DEFAULT_LABEL,
    note: str | None = None,
    captured_at: datetime | None = None,
    tool_list: dict[str, Any] | None = None,
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap ``report.as_dict()`` with provenance. The committed artifact.

    ``tool_list`` is the optional US-PM-15-7 measurement. It is a *parameter*
    rather than something this function goes and measures, so building a
    baseline out of a report stays pure and cheap; :func:`capture` is what
    fills it in for a real artifact. Omitted entirely when absent, so the
    committed pre-fix baseline's key set is what it always was.
    """
    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "provenance": build_provenance(
            report,
            repo=repo,
            label=label,
            note=note,
            captured_at=captured_at,
            window=window,
        ),
        "report": report.as_dict(),
    }
    if tool_list is not None:
        artifact["tool_list"] = tool_list
    return artifact


# ---------------------------------------------------------------- metrics --


def _rate(part: float | int | None, whole: float | int | None) -> float | None:
    if not whole:
        return None
    return round(100.0 * float(part or 0) / float(whole), 4)


def _pct(fraction: float | int | None) -> float | None:
    """Report rates are fractions (0-1); baselines publish percentages.

    Keeping both units in one artifact is how a comparison silently reads 6.26%
    as 0.0626 later, so the conversion happens once, here.
    """
    if fraction is None:
        return None
    return round(100.0 * float(fraction), 4)


#: US-PM-9's note-length gate, from ``docs/reference/evidence-contract.md`` section 8,
#: read against the server's 4096-character run-log cap. "Well below the cap" is
#: made falsifiable here rather than in a unit assertion about live data: the live
#: number cannot move until the rewritten ``pm-orchestrate`` skill accumulates
#: traffic, so this is a *report* check over whatever corpus is captured.
NOTE_LENGTH_GATE_MEDIAN = 300
NOTE_LENGTH_GATE_P90 = 800


def _note_length_gate_passed(notes: dict[str, Any]) -> bool | None:
    """Whether a captured note-length distribution clears the gate.

    ``None``, never ``False``, when there is nothing to judge -- a baseline
    captured before the metric existed, or one whose corpus carries no notes at
    all. A missing measurement is not a failed one, and a ``False`` here would
    read as "the notes are too long" in every comparison against an old file.
    """
    median, p90 = notes.get("median"), notes.get("p90")
    if median is None or p90 is None:
        return None
    return median <= NOTE_LENGTH_GATE_MEDIAN and p90 <= NOTE_LENGTH_GATE_P90


#: US-PM-13's guidance tools, as :data:`tools.usage_telemetry.report.GUIDANCE_TOOLS`
#: names them. Imported rather than restated so the headline cannot publish a
#: different set from the one the report measured.
GUIDANCE_TOOLS = report_mod.GUIDANCE_TOOLS


def _guidance_calls(by_tool: dict[str, Any], tool: str) -> int | None:
    """Call count for ``tool``; ``None`` only when the section is missing.

    A baseline captured before the metric existed has nothing to say, so the
    key reads ``None`` and no comparison row pretends to a delta. A baseline
    that *has* the section but never saw the tool reports ``0`` -- a measured
    zero, which is the number US-PM-13 exists to move.
    """
    if not by_tool:
        return None
    return (by_tool.get(tool) or {}).get("calls") or 0


def _guidance_sessions_pct(by_tool: dict[str, Any], tool: str) -> float | None:
    """Percentage of sessions that called ``tool`` at least once."""
    if not by_tool:
        return None
    return _pct((by_tool.get(tool) or {}).get("session_rate") or 0.0)


#: Tools whose longest consecutive run the bulk verbs (US-PM-12) exist to
#: shorten. They get a *per-tool* headline number because the corpus-wide
#: ``longest_run`` answers a different question: it reports whichever tool
#: happens to top the corpus, so a ``pm_update`` run collapsing from 45 to 3 is
#: invisible in it the moment any other tool holds the record.
BULK_RUN_TOOLS: tuple[str, ...] = ("pm_update", "pm_archive")


def _tool_longest_run(rows: Sequence[dict[str, Any]], tool: str) -> int | None:
    """Longest consecutive run of ``tool``; ``None`` only when ``by_tool`` is absent.

    Unlike the guidance-tool metrics this one is *retroactive*: every baseline
    ever captured already carries a per-tool run profile, so an old file answers
    the question without being re-captured. A tool the corpus never saw reports
    a measured ``0``, not ``None``.
    """
    if not rows:
        return None
    for row in rows:
        if row.get("tool") == tool:
            return (row.get("runs") or {}).get("longest") or 0
    return 0


def headline_metrics(baseline: dict[str, Any]) -> dict[str, Any]:
    """The small set of numbers a comparison is actually argued from.

    Flat and scalar on purpose: a diff over this dict is readable, whereas a diff
    over the full report is dominated by per-tool churn.
    """
    report = baseline.get("report") or {}
    totals = report.get("totals") or {}
    corpus = report.get("corpus") or {}
    failures = report.get("failures") or {}
    inclusive = failures.get("inclusive") or {}
    rates = failures.get("rates") or {}
    runs = report.get("runs") or {}
    longest = runs.get("longest") or []
    # Absent from baselines captured before US-PM-8 added the metric; the keys
    # stay in the dict as ``None`` so a diff against an older file still lines up.
    completions = report.get("completions") or {}
    # Likewise absent before US-PM-9 added the note-length metric.
    notes = report.get("note_lengths") or {}
    # Likewise absent before US-PM-13 added the guidance-tool metric. Note the
    # two-level default: a *missing section* leaves the keys ``None`` so a diff
    # against an older file lines up, but a *present section* reports a real 0
    # for a tool nobody called. US-PM-13's "before" is a zero, and the whole
    # criterion is that the zero is visible.
    guidance = (report.get("guidance_tools") or {}).get("by_tool") or {}
    by_tool = report.get("by_tool") or []
    # Likewise absent before US-PM-15 added the tool-list measurement. This one
    # sits beside ``report`` rather than inside it: it measures the *schema
    # surface the server offers*, which is a property of the code, not of the
    # transcript corpus every other metric here is computed from.
    tool_list = baseline.get("tool_list") or {}

    calls = totals.get("calls")
    metrics: dict[str, Any] = {
        "transcript_files": corpus.get("files_scanned"),
        "sessions": totals.get("sessions"),
        "calls": calls,
        "match_rate_pct": _rate(totals.get("matched"), calls),
        "response_bytes": totals.get("response_bytes"),
        "estimated_tokens": totals.get("estimated_tokens"),
        "median_bytes_per_call": (totals.get("bytes_per_call") or {}).get("median"),
        "failures": failures.get("failures"),
        "failure_rate_pct": _pct(rates.get("combined_failure_rate")),
        "hard_errors": inclusive.get("hard_error"),
        "hard_error_rate_pct": _pct(rates.get("hard_error")),
        "soft_errors": inclusive.get("soft_error"),
        "soft_error_rate_pct": _pct(rates.get("soft_error")),
        "malformed_inputs": inclusive.get("malformed_input"),
        "malformed_input_rate_pct": _pct(rates.get("malformed_input")),
        "completions": completions.get("completions"),
        "completions_without_run_log": completions.get("without_run_log"),
        "completions_without_run_log_rate_pct": _pct(
            completions.get("completions_without_run_log_rate")
        ),
        "note_length_median": notes.get("median"),
        "note_length_p90": notes.get("p90"),
        "note_length_p95": notes.get("p95"),
        "note_length_gate_passed": _note_length_gate_passed(notes),
        "pm_context_calls": _guidance_calls(guidance, "pm_context"),
        "pm_estimate_calls": _guidance_calls(guidance, "pm_estimate"),
        "pm_context_sessions_pct": _guidance_sessions_pct(guidance, "pm_context"),
        "pm_estimate_sessions_pct": _guidance_sessions_pct(guidance, "pm_estimate"),
        "runs_total": runs.get("total"),
        "longest_run": longest[0].get("length") if longest else None,
        "longest_run_tool": longest[0].get("tool") if longest else None,
        "tool_list_bytes_all": (tool_list.get("all_families") or {}).get("bytes"),
        "tool_list_bytes_default": (tool_list.get("default") or {}).get("bytes"),
        "tool_list_tools_default": (tool_list.get("default") or {}).get("tools"),
    }
    # Per-tool run lengths, keyed by tool so the comparison table names the tool
    # the criterion is about instead of leaving the reader to infer it.
    for tool in BULK_RUN_TOOLS:
        metrics[f"{tool}_longest_run"] = _tool_longest_run(by_tool, tool)
    return metrics


def top_tools_by_calls(baseline: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    rows = sorted(
        (baseline.get("report") or {}).get("by_tool") or [],
        key=lambda r: (-(r.get("calls") or 0), r.get("tool") or ""),
    )
    return rows[:limit]


# ---------------------------------------------------------------- compare --

#: Metrics where a *smaller* number is the improvement the epic is chasing.
LOWER_IS_BETTER = frozenset(
    {
        "response_bytes",
        "estimated_tokens",
        "median_bytes_per_call",
        "failures",
        "failure_rate_pct",
        "hard_errors",
        "hard_error_rate_pct",
        "soft_errors",
        "soft_error_rate_pct",
        "malformed_inputs",
        "malformed_input_rate_pct",
        "completions_without_run_log",
        "completions_without_run_log_rate_pct",
        "note_length_median",
        "note_length_p90",
        "note_length_p95",
        "longest_run",
        # Per-tool run lengths: the whole point of a bulk verb is that the run
        # it replaces gets shorter.
        *(f"{tool}_longest_run" for tool in BULK_RUN_TOOLS),
        # US-PM-15: schema bytes served on every request. Only the *default*
        # payload is a target -- ``tool_list_bytes_all`` is the unabridged
        # surface the saving is measured against, and it moving is a change in
        # how many tools exist, not a win or a loss, so it stays unlabelled.
        # ``tool_list_tools_default`` is a plain count for the same reason.
        "tool_list_bytes_default",
    }
)

#: Metrics where a *larger* number is the improvement. ``compare`` used to leave
#: every non-``LOWER_IS_BETTER`` key unlabelled rather than assuming a
#: direction, which is right for a raw count like ``calls`` (the corpus grows;
#: bigger is neither good nor bad). US-PM-13's guidance-tool numbers are the
#: first metrics here with a genuine "up is the win" reading -- the story exists
#: because they sit at 1 call each -- so they get their own set rather than an
#: inverted reading of the lower-is-better one.
HIGHER_IS_BETTER = frozenset(
    {
        "pm_context_calls",
        "pm_estimate_calls",
        "pm_context_sessions_pct",
        "pm_estimate_sessions_pct",
    }
)


def compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Headline deltas between two baselines, oldest first.

    Rate metrics are the honest comparison and absolute counts are not: the
    corpus grows between captures, so a raised absolute failure count with a
    falling failure rate is an improvement. ``corpus_grew`` flags that case so a
    reader cannot miss it.
    """
    before = headline_metrics(old)
    after = headline_metrics(new)

    metrics: dict[str, Any] = {}
    for key in before:
        a, b = before.get(key), after.get(key)
        row: dict[str, Any] = {"before": a, "after": b}
        # ``bool`` is an ``int`` in Python, and a pass/fail gate has no delta or
        # percentage change worth printing -- it flips or it does not.
        numeric = (int, float)
        if (
            isinstance(a, numeric)
            and isinstance(b, numeric)
            and not isinstance(a, bool)
            and not isinstance(b, bool)
        ):
            delta = b - a
            row["delta"] = round(delta, 4) if isinstance(delta, float) else delta
            row["pct_change"] = _rate(delta, abs(a)) if a else None
            if delta != 0:
                if key in LOWER_IS_BETTER:
                    row["direction"] = "better" if delta < 0 else "worse"
                elif key in HIGHER_IS_BETTER:
                    row["direction"] = "better" if delta > 0 else "worse"
        metrics[key] = row

    return {
        "before": {
            "label": (old.get("provenance") or {}).get("label"),
            "captured_at": (old.get("provenance") or {}).get("captured_at"),
            "commit": ((old.get("provenance") or {}).get("git") or {}).get("commit"),
        },
        "after": {
            "label": (new.get("provenance") or {}).get("label"),
            "captured_at": (new.get("provenance") or {}).get("captured_at"),
            "commit": ((new.get("provenance") or {}).get("git") or {}).get("commit"),
        },
        "corpus_grew": ((metrics.get("calls") or {}).get("delta") or 0) > 0,
        "metrics": metrics,
    }


def format_comparison(diff: dict[str, Any]) -> str:
    before, after = diff["before"], diff["after"]
    lines = [
        f"baseline  {before.get('label')}  {before.get('captured_at')}  "
        f"commit {(before.get('commit') or '?')[:12]}",
        f"current   {after.get('label')}  {after.get('captured_at')}  "
        f"commit {(after.get('commit') or '?')[:12]}",
        "",
        f"  {'metric':<26}{'before':>14}{'after':>14}{'delta':>14}  ",
    ]
    for key, row in diff["metrics"].items():
        a, b, d = row.get("before"), row.get("after"), row.get("delta")
        mark = {"better": "  better", "worse": "  worse"}.get(row.get("direction", ""), "")
        lines.append(
            f"  {key:<26}{_fmt(a):>14}{_fmt(b):>14}{_fmt(d, signed=True):>14}{mark}"
        )
    lines += [
        "",
        "The corpus is live and grows between captures, so absolute counts are not",
        "comparable on their own -- read the *_rate_pct rows for the real movement.",
    ]
    return "\n".join(lines)


def _fmt(value: Any, signed: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:+,.2f}" if signed else f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:+,}" if signed else f"{value:,}"
    return str(value)


# ---------------------------------------------------------------- markdown --


def format_summary(baseline: dict[str, Any]) -> str:
    """Human-readable companion to the JSON artifact."""
    prov = baseline.get("provenance") or {}
    git = prov.get("git") or {}
    m = headline_metrics(baseline)
    label = prov.get("label") or DEFAULT_LABEL
    commit = git.get("commit") or "unknown"
    dirty = git.get("dirty")
    dirty_note = (
        " (working tree **dirty** at capture -- the analysis code was not fully "
        "committed, so re-running at this commit alone may not reproduce it)"
        if dirty
        else ""
        if dirty is False
        else " (working tree state unknown)"
    )

    lines = [
        f"# Usage-telemetry baseline -- {label}",
        "",
        f"**This is the {label.upper()} baseline for the ProjectMan tool-usage epic.** "
        "It is the measurement every later claim of improvement is compared against. "
        "It was captured *before* the epic's fixes landed; do not overwrite it.",
        "",
        "## Provenance",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| captured at (UTC) | `{prov.get('captured_at')}` |",
        f"| code at commit | `{commit}`{dirty_note} |",
        f"| branch | `{git.get('branch')}` |",
        f"| corpus root | `{prov.get('corpus_root')}` |",
        f"| tool prefix | `{prov.get('tool_prefix')}` |",
        f"| transcript files | {_fmt(m['transcript_files'])} |",
        f"| sessions | {_fmt(m['sessions'])} |",
        f"| calls | {_fmt(m['calls'])} |",
        f"| call->result match rate | {_fmt(m['match_rate_pct'])}% "
        f"({_fmt(prov.get('unmatched_calls'))} unmatched) |",
        f"| schema | `{baseline.get('schema')}` |",
    ]
    # Rendered only for a windowed capture (US-PM-32): an unwindowed baseline
    # must re-render byte-for-byte as it always did.
    if prov.get("window_since"):
        lines.append(
            f"| capture window | sessions starting at or after "
            f"`{prov['window_since']}` "
            f"({_fmt(prov.get('sessions_excluded'))} earlier sessions excluded) |"
        )
    lines.append("")
    if prov.get("note"):
        lines += [f"> {prov['note']}", ""]

    if prov.get("window_since"):
        lines += [
            "## This capture is windowed",
            "",
            f"Only sessions whose first transcript timestamp is at or after "
            f"`{prov['window_since']}` are counted; "
            f"{_fmt(prov.get('sessions_excluded'))} earlier sessions were excluded, "
            "whole. Filtering is per session rather than per call, because "
            "calls-per-session, run lengths and bigrams mean nothing across a "
            "transcript cut in half.",
            "",
            "**A windowed capture is not comparable to an unwindowed one on "
            "absolute counts.** It is a different, smaller corpus by "
            "construction. Compare the rates, and read the window as part of the "
            "claim: these numbers describe the sessions in it, not the whole "
            "transcript tree.",
            "",
        ]

    lines += [
        "## The corpus is live, not a fixed dataset",
        "",
        "The corpus is the local Claude transcript tree, and it is still being written to.",
        "**It includes the ProjectMan calls made by the orchestration session that captured "
        "this baseline**, and it grew while that session worked -- a capture taken minutes "
        f"later would already have more calls. The numbers below are a snapshot as of "
        f"`{prov.get('captured_at')}`, not a static dataset.",
        "",
        "Two consequences for anyone comparing against this file:",
        "",
        "1. Compare **rates**, not absolute counts. The denominator moves.",
        "2. A later capture includes these transcripts plus everything since, so it is a "
        "superset, not an independent sample. Improvements are diluted by the history "
        "still in the corpus; the true post-fix rate is better than a whole-corpus "
        "re-capture will show.",
        "",
        "## Headline numbers",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| calls | {_fmt(m['calls'])} |",
        f"| total response bytes | {_fmt(m['response_bytes'])} "
        f"({(m['response_bytes'] or 0) / 1_000_000:.2f} MB, "
        f"~{_fmt(m['estimated_tokens'])} tokens) |",
        f"| median bytes per call | {_fmt(m['median_bytes_per_call'])} |",
        f"| failing calls (distinct) | {_fmt(m['failures'])} "
        f"({_fmt(m['failure_rate_pct'])}%) |",
        f"| hard errors (`is_error`) | {_fmt(m['hard_errors'])} "
        f"({_fmt(m['hard_error_rate_pct'])}%) |",
        f"| soft errors (error body) | {_fmt(m['soft_errors'])} "
        f"({_fmt(m['soft_error_rate_pct'])}%) |",
        f"| malformed inputs (`__unparsedToolInput`) | {_fmt(m['malformed_inputs'])} "
        f"({_fmt(m['malformed_input_rate_pct'])}%) |",
        f"| longest consecutive run | {_fmt(m['longest_run'])}x "
        f"`{m['longest_run_tool']}` |",
        f"| consecutive runs total | {_fmt(m['runs_total'])} |",
    ]
    # Rendered only when the report carries the section: baselines captured
    # before US-PM-8 added it must still re-render byte-for-byte identically.
    if m["completions"] is not None:
        lines.append(
            f"| completions with no run-log entry | {_fmt(m['completions_without_run_log'])}"
            f" of {_fmt(m['completions'])} "
            f"({_fmt(m['completions_without_run_log_rate_pct'])}%) |"
        )
    # Same rule, same reason: a baseline captured before US-PM-9 added the
    # note-length metric has no median to print and must re-render unchanged.
    if m["note_length_median"] is not None:
        gate = "pass" if m["note_length_gate_passed"] else "FAIL"
        lines.append(
            f"| run-log note length | median {_fmt(m['note_length_median'])}, "
            f"p90 {_fmt(m['note_length_p90'])}, p95 {_fmt(m['note_length_p95'])} chars "
            f"(gate: median <= {NOTE_LENGTH_GATE_MEDIAN}, p90 <= {NOTE_LENGTH_GATE_P90} "
            f"-- {gate}) |"
        )
    # Same rule again for US-PM-13's guidance-tool usage. ``is not None`` and not
    # a truthiness test: the number this row exists to publish is a zero.
    if m["pm_context_calls"] is not None:
        lines.append(
            f"| guidance tool usage | `pm_context` {_fmt(m['pm_context_calls'])} calls "
            f"in {_fmt(m['pm_context_sessions_pct'])}% of sessions, "
            f"`pm_estimate` {_fmt(m['pm_estimate_calls'])} calls "
            f"in {_fmt(m['pm_estimate_sessions_pct'])}% of sessions |"
        )
    # Same rule again for US-PM-15's tool-list measurement. Unlike every row
    # above it this one is not computed from the corpus -- see
    # ``docs/telemetry/tool-list-size.md`` for the full per-family breakdown.
    if m["tool_list_bytes_default"] is not None:
        saved = (m["tool_list_bytes_all"] or 0) - m["tool_list_bytes_default"]
        pct = _rate(saved, m["tool_list_bytes_all"])
        lines.append(
            f"| `tools/list` schema bytes | {_fmt(m['tool_list_bytes_default'])} "
            f"for {_fmt(m['tool_list_tools_default'])} tools by default, "
            f"{_fmt(m['tool_list_bytes_all'])} with every gated family on "
            f"({_fmt(saved)} saved, {_fmt(pct)}%) |"
        )
    lines += [
        "",
        "The three failure classes overlap (one call can be both malformed and a hard "
        "error), so they do not sum to the distinct failure count.",
        "",
        "## Busiest tools by call count",
        "",
        "| tool | calls | % calls | response bytes | % bytes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in top_tools_by_calls(baseline):
        lines.append(
            f"| `{row.get('tool')}` | {_fmt(row.get('calls'))} | "
            f"{100 * (row.get('call_share') or 0.0):.1f}% | "
            f"{_fmt(row.get('result_bytes'))} | "
            f"{100 * (row.get('byte_share') or 0.0):.1f}% |"
        )

    lines += [
        "",
        "## Re-capture and compare",
        "",
        "```sh",
        "# take a fresh capture next to this one",
        "python -m tools.usage_telemetry.baseline capture \\",
        f"    --out-dir {DEFAULT_OUT_DIR} --name baseline-YYYY-MM-DD --label post-fix",
        "",
        "# compare this baseline against a live capture",
        "python -m tools.usage_telemetry.baseline compare \\",
        f"    {DEFAULT_OUT_DIR}/baseline-{label}.json",
        "```",
        "",
        f"See [README.md](README.md) for the full procedure. The full machine-readable "
        f"record is `baseline-{label}.json`; this file is only its summary.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- io --


def write_baseline(baseline: dict[str, Any], out_dir: Path, name: str) -> tuple[Path, Path]:
    """Write ``<name>.json`` and ``<name>.md``. Returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    md_path = out_dir / f"{name}.md"
    json_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(format_summary(baseline), encoding="utf-8")
    return json_path, md_path


def load_baseline(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "report" not in data:
        raise ValueError(f"{path} is not a usage-telemetry baseline artifact")
    return data


def capture(
    *,
    root: str | None = None,
    prefix: str = TOOL_PREFIX,
    min_match_rate: float | None = None,
    repo: Path | None = None,
    label: str = DEFAULT_LABEL,
    note: str | None = None,
    since: str | datetime | None = None,
) -> dict[str, Any]:
    """Scan the corpus and return a complete baseline artifact.

    ``since`` windows the capture to sessions that started at or after the given
    moment -- an ISO-8601 string, a ``datetime``, or ``"auto"`` to derive it from
    the corpus (:func:`note_truncated_cutoff`). ``None`` captures everything, as
    it always has.

    The match-rate guard runs against the **whole** scan, before the window is
    applied: a broken call->result join is a property of the corpus and the
    extractor, and letting a window hide it would defeat the guard.
    """
    extraction = scan(root=root, tool_prefix=prefix, min_match_rate=min_match_rate)
    window: dict[str, Any] | None = None
    if since is not None:
        cutoff = resolve_since(since, extraction)
        extraction, window = filter_extraction_since(extraction, cutoff)
    report = report_from_extraction(extraction)
    return build_baseline(
        report,
        repo=repo or Path.cwd(),
        label=label,
        note=note,
        tool_list=measure_tool_list(),
        window=window,
    )


# -------------------------------------------------------------------- cli --


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.usage_telemetry.baseline",
        description=(
            "Capture a provenance-stamped usage-telemetry baseline, or compare a "
            "stored baseline against a fresh one."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _corpus_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", default=None, help="Transcript root (default: $CLAUDE_PROJECTS_DIR or ~/.claude/projects)")
        p.add_argument("--prefix", default=TOOL_PREFIX, help=f"Tool-name prefix (default: {TOOL_PREFIX})")
        p.add_argument("--min-match-rate", type=float, default=None, help="Refuse to capture below this call->result join rate")
        p.add_argument("--repo", default=None, help="Repo whose git commit is recorded (default: cwd)")

    cap = sub.add_parser("capture", help="Write a baseline JSON + markdown summary")
    _corpus_args(cap)
    cap.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"Directory to write into (default: {DEFAULT_OUT_DIR})")
    cap.add_argument("--name", default=None, help="Artifact basename (default: baseline-<label>)")
    cap.add_argument("--label", default=DEFAULT_LABEL, help=f"Baseline label (default: {DEFAULT_LABEL})")
    cap.add_argument("--note", default=None, help="Free-text note stored in provenance")
    cap.add_argument(
        "--since",
        default=None,
        metavar="WHEN",
        help=(
            "Only count sessions whose first transcript timestamp is at or after "
            "WHEN (ISO-8601, e.g. 2026-08-21 or 2026-08-21T14:03:00Z). Pass "
            f"'{SINCE_AUTO}' to derive the cutoff from the corpus: the start of "
            "the earliest session carrying a `note_truncated: true` response, "
            "i.e. the first session provably run against the US-PM-1 fix. The "
            "window is recorded in provenance as window_since/sessions_excluded."
        ),
    )
    cap.add_argument("--stdout", action="store_true", help="Print the JSON instead of writing files")

    cmp_ = sub.add_parser("compare", help="Diff a stored baseline against a fresh or stored capture")
    _corpus_args(cmp_)
    cmp_.add_argument("baseline", help="Path to the stored baseline JSON")
    cmp_.add_argument("against", nargs="?", default=None, help="Second baseline JSON (default: capture live)")
    cmp_.add_argument("--label", default="current", help="Label for the live capture (default: current)")
    cmp_.add_argument("--json", action="store_true", help="Emit the comparison as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser() if args.repo else Path.cwd()

    if args.command == "capture":
        try:
            baseline = capture(
                root=args.root,
                prefix=args.prefix,
                min_match_rate=args.min_match_rate,
                repo=repo,
                label=args.label,
                note=args.note,
                since=args.since,
            )
        except MatchRateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except WindowError as exc:
            # Same exit code as the match-rate guard, for the same reason: the
            # capture was refused, and no artifact is written.
            print(f"error: {exc}", file=sys.stderr)
            return 1
        prov = baseline["provenance"]
        if baseline["report"]["totals"]["calls"] == 0:
            if prov.get("window_since"):
                print(
                    f"error: no {args.prefix}* calls remain after --since "
                    f"{prov['window_since']} excluded "
                    f"{prov.get('sessions_excluded')} sessions",
                    file=sys.stderr,
                )
            else:
                print(f"error: no {args.prefix}* calls found", file=sys.stderr)
            return 2
        if args.stdout:
            print(json.dumps(baseline, indent=2))
            return 0
        name = args.name or f"baseline-{args.label}"
        json_path, md_path = write_baseline(baseline, Path(args.out_dir).expanduser(), name)
        m = headline_metrics(baseline)
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
        print(
            f"{_fmt(m['calls'])} calls / {_fmt(m['transcript_files'])} transcripts / "
            f"{_fmt(m['failure_rate_pct'])}% failures / {_fmt(m['response_bytes'])} bytes"
        )
        if prov.get("window_since"):
            print(
                f"window: sessions at or after {prov['window_since']} "
                f"({prov.get('sessions_excluded')} earlier sessions excluded)"
            )
        return 0

    stored = load_baseline(Path(args.baseline).expanduser())
    if args.against:
        current = load_baseline(Path(args.against).expanduser())
    else:
        try:
            current = capture(
                root=args.root,
                prefix=args.prefix,
                min_match_rate=args.min_match_rate,
                repo=repo,
                label=args.label,
            )
        except MatchRateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    diff = compare(stored, current)
    print(json.dumps(diff, indent=2) if args.json else format_comparison(diff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
