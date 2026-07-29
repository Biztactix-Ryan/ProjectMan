"""Usage metrics: call counts, response bytes, consecutive runs and adjacency.

These are the numbers the rest of the plan is measured against, so every one of
them is defined here once and computed the same way on every run.

What is reported
----------------
**Call counts** -- per tool, plus each tool's share of all calls.

**Response bytes** -- per tool: the total (the headline; it *is* the context
cost the other stories aim to reduce) and a per-call distribution. A mean alone
is useless here: the corpus is dominated by a few very large read payloads next
to thousands of ~100-byte acknowledgements, so median / p90 / p95 / p99 / max
are reported alongside it. Bytes always come from the **untruncated** result
body (:attr:`~tools.usage_telemetry.extract.ToolResult.bytes`); the studies that
counted a 3,000- or 4,000-char preview understated exactly the payloads that
matter most.

**Consecutive runs** -- how often a tool is called N times in a row. A run of
length N is N calls where one batch call would have done, so the run-length
histogram is the direct measure of the missing bulk-write path.

**Adjacency bigrams** -- tool A immediately followed by tool B, which is what
exposes two-call habits that a single tool already collapses
(``pm_grab -> pm_update`` where ``pm_done_next`` exists).

Boundaries
----------
Runs and bigrams are computed **within one transcript file** and never across
files. Grouping is by :attr:`~tools.usage_telemetry.extract.ToolCall.session`
(the transcript stem) rather than ``session_id``, because one ``session_id`` can
span several files: joining them would invent an adjacency between the last call
of one file and the first call of the next, which never happened. The corpus
walk is sorted, so an accidental cross-file pair would look plausible and be
completely fictional.

Quantiles
---------
All quantiles use the **nearest-rank** method (``ceil(q*n)`` on the sorted
sample), so every reported percentile is a value that actually occurred -- no
interpolated byte counts that no call ever returned. For even samples this makes
``median`` the lower of the two central values, which is deliberate.

Failure counts are not recomputed here; they come from
:mod:`tools.usage_telemetry.classify` so there is exactly one definition of
"failure" in the package. They are also *rendered* the way that module counts
them -- hard errors, soft errors and malformed inputs as three separate figures
next to the distinct-call total, never collapsed into one "errors" number.

Usage::

    python -m tools.usage_telemetry.report
    python -m tools.usage_telemetry.report --json > baseline.json
    python -m tools.usage_telemetry.report --root /path/to/projects --top 30
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.usage_telemetry.classify import (
    MALFORMED_INPUT_KEY,
    Classification,
    classify_all,
)
from tools.usage_telemetry.extract import (
    TOOL_PREFIX,
    Extraction,
    MatchRateError,
    ToolCall,
    scan,
)

#: Percentiles reported for every byte distribution, as fractions.
PERCENTILES: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99)

#: Rough chars-per-token divisor used by the studies for context estimates.
CHARS_PER_TOKEN = 4

#: Default number of bigrams / longest runs shown in the *text* report. The JSON
#: output is never truncated -- see :meth:`UsageReport.as_dict`.
DEFAULT_TOP = 20


def percentile(values: Sequence[int | float], q: float) -> int | float | None:
    """Nearest-rank percentile of ``values``; ``None`` for an empty sample.

    ``q`` is a fraction in ``[0, 1]``. The result is always an element of
    ``values``, which keeps byte counts honest (an interpolated 3,412.5-byte
    response never happened).
    """
    if not 0.0 <= q <= 1.0:  # rejects NaN too, which fails both comparisons
        raise ValueError(f"q must be a fraction between 0 and 1, got {q!r}")
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(q * len(ordered))
    index = min(len(ordered) - 1, max(0, rank - 1))
    return ordered[index]


@dataclass(frozen=True)
class Distribution:
    """Summary of a sample: total plus the quantiles that matter.

    Every field except :attr:`count` and :attr:`total` is ``None`` for an empty
    sample rather than a misleading zero.
    """

    count: int
    total: int
    mean: float | None
    minimum: int | float | None
    median: int | float | None
    p90: int | float | None
    p95: int | float | None
    p99: int | float | None
    maximum: int | float | None

    @classmethod
    def of(cls, values: Iterable[int | float]) -> Distribution:
        sample = sorted(values)
        if not sample:
            return cls(0, 0, None, None, None, None, None, None, None)
        total = sum(sample)
        return cls(
            count=len(sample),
            total=total,
            mean=total / len(sample),
            minimum=sample[0],
            median=percentile(sample, 0.5),
            p90=percentile(sample, 0.9),
            p95=percentile(sample, 0.95),
            p99=percentile(sample, 0.99),
            maximum=sample[-1],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "total": self.total,
            "mean": self.mean,
            "min": self.minimum,
            "median": self.median,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.maximum,
        }


@dataclass(frozen=True)
class Run:
    """``length`` consecutive calls to ``tool`` inside a single transcript."""

    tool: str
    session: str
    start_seq: int
    end_seq: int
    length: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "length": self.length,
            "session": self.session,
            "start_seq": self.start_seq,
            "end_seq": self.end_seq,
        }


def group_by_session(calls: Iterable[ToolCall]) -> dict[str, list[ToolCall]]:
    """Calls grouped by transcript file, each list in transcript (``seq``) order.

    Mirrors :meth:`~tools.usage_telemetry.extract.Extraction.calls_by_session` so
    a plain list of calls can be analysed without an :class:`Extraction`.
    """
    grouped: dict[str, list[ToolCall]] = {}
    for call in calls:
        grouped.setdefault(call.session, []).append(call)
    for session_calls in grouped.values():
        session_calls.sort(key=lambda c: c.seq)
    return grouped


def iter_runs(calls: Iterable[ToolCall]) -> Iterator[Run]:
    """Yield every maximal same-tool run, **never crossing a transcript file**.

    Runs of length 1 are yielded too: the histogram needs the denominator, and
    "how many calls stand alone" is what the run-length share is measured
    against.
    """
    grouped = group_by_session(calls)
    for session in sorted(grouped):
        session_calls = grouped[session]
        start = 0
        for index in range(1, len(session_calls) + 1):
            at_end = index == len(session_calls)
            if at_end or session_calls[index].tool != session_calls[start].tool:
                yield Run(
                    tool=session_calls[start].tool,
                    session=session,
                    start_seq=session_calls[start].seq,
                    end_seq=session_calls[index - 1].seq,
                    length=index - start,
                )
                start = index


def iter_bigrams(calls: Iterable[ToolCall]) -> Iterator[tuple[str, str]]:
    """Yield ``(tool_a, tool_b)`` for adjacent calls **within one transcript**.

    The last call of a transcript is never paired with the first call of the
    next one -- that adjacency does not exist.
    """
    grouped = group_by_session(calls)
    for session in sorted(grouped):
        session_calls = grouped[session]
        for first, second in zip(session_calls, session_calls[1:]):
            yield (first.tool, second.tool)


@dataclass
class RunProfile:
    """Consecutive-run statistics for one tool."""

    tool: str
    lengths: list[int] = field(default_factory=list)

    @property
    def runs(self) -> int:
        return len(self.lengths)

    @property
    def longest(self) -> int:
        return max(self.lengths) if self.lengths else 0

    @property
    def calls_in_runs(self) -> int:
        return sum(self.lengths)

    def runs_at_least(self, n: int) -> int:
        return sum(1 for length in self.lengths if length >= n)

    def calls_at_least(self, n: int) -> int:
        return sum(length for length in self.lengths if length >= n)

    @property
    def removable_calls(self) -> int:
        """Calls a batch variant would eliminate: ``sum(length - 1)``.

        One call per run has to happen regardless; everything above it is the
        cost of not having a bulk path.
        """
        return sum(length - 1 for length in self.lengths)

    @property
    def histogram(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for length in self.lengths:
            counts[length] = counts.get(length, 0) + 1
        return dict(sorted(counts.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "longest": self.longest,
            "calls_in_runs": self.calls_in_runs,
            "runs_ge2": self.runs_at_least(2),
            "calls_in_runs_ge2": self.calls_at_least(2),
            "runs_ge3": self.runs_at_least(3),
            "calls_in_runs_ge3": self.calls_at_least(3),
            "removable_calls": self.removable_calls,
            "histogram": {str(k): v for k, v in self.histogram.items()},
        }


@dataclass
class ToolUsage:
    """Per-tool call counts, response bytes and run profile."""

    tool: str
    calls: int = 0
    unmatched: int = 0
    failures: int = 0
    #: Per-call response byte counts, matched calls only.
    byte_samples: list[int] = field(default_factory=list)
    result_chars: int = 0
    runs: RunProfile = field(default_factory=lambda: RunProfile(tool=""))

    @property
    def result_bytes(self) -> int:
        """Total response bytes -- the headline per-tool number."""
        return sum(self.byte_samples)

    @property
    def bytes_per_call(self) -> Distribution:
        return Distribution.of(self.byte_samples)

    @property
    def mean_bytes(self) -> float:
        return self.result_bytes / self.calls if self.calls else 0.0

    def as_dict(self, total_calls: int, total_bytes: int) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "calls": self.calls,
            "call_share": self.calls / total_calls if total_calls else 0.0,
            "unmatched": self.unmatched,
            "failures": self.failures,
            "result_bytes": self.result_bytes,
            "byte_share": self.result_bytes / total_bytes if total_bytes else 0.0,
            "result_chars": self.result_chars,
            "bytes_per_call": self.bytes_per_call.as_dict(),
            "runs": self.runs.as_dict(),
        }


@dataclass
class UsageReport:
    """Call counts, response bytes, run lengths and bigrams for a corpus."""

    calls: list[ToolCall] = field(default_factory=list)
    tools: dict[str, ToolUsage] = field(default_factory=dict)
    runs: list[Run] = field(default_factory=list)
    bigrams: dict[tuple[str, str], int] = field(default_factory=dict)
    classification: Classification | None = None
    extraction_summary: dict[str, Any] | None = None

    # ---- totals -------------------------------------------------------
    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def matched_calls(self) -> int:
        return sum(1 for c in self.calls if c.result is not None)

    @property
    def unmatched_calls(self) -> int:
        return self.total_calls - self.matched_calls

    @property
    def sessions(self) -> int:
        return len({c.session for c in self.calls})

    @property
    def total_bytes(self) -> int:
        return sum(usage.result_bytes for usage in self.tools.values())

    @property
    def total_chars(self) -> int:
        return sum(usage.result_chars for usage in self.tools.values())

    @property
    def estimated_tokens(self) -> int:
        return self.total_chars // CHARS_PER_TOKEN

    @property
    def bytes_per_call(self) -> Distribution:
        return Distribution.of(
            c.result.bytes for c in self.calls if c.result is not None
        )

    @property
    def calls_per_session(self) -> Distribution:
        return Distribution.of(
            len(v) for v in group_by_session(self.calls).values()
        )

    # ---- views --------------------------------------------------------
    def by_bytes(self) -> list[ToolUsage]:
        """Tools ordered by total response bytes, descending. The headline order."""
        return sorted(
            self.tools.values(),
            key=lambda u: (-u.result_bytes, -u.calls, u.tool),
        )

    def by_calls(self) -> list[ToolUsage]:
        """Tools ordered by call count, descending."""
        return sorted(
            self.tools.values(),
            key=lambda u: (-u.calls, -u.result_bytes, u.tool),
        )

    def longest_runs(self, limit: int | None = None) -> list[Run]:
        """Runs ordered longest first; ties broken deterministically."""
        ranked = sorted(
            self.runs, key=lambda r: (-r.length, r.tool, r.session, r.start_seq)
        )
        return ranked[:limit] if limit is not None else ranked

    def top_bigrams(self, limit: int | None = None) -> list[tuple[str, str, int]]:
        """``(from_tool, to_tool, count)`` ordered by count, descending."""
        ranked = sorted(self.bigrams.items(), key=lambda kv: (-kv[1], kv[0]))
        pairs = [(a, b, n) for (a, b), n in ranked]
        return pairs[:limit] if limit is not None else pairs

    def run_histogram(self) -> dict[int, int]:
        """Run-length histogram across all tools."""
        counts: dict[int, int] = {}
        for run in self.runs:
            counts[run.length] = counts.get(run.length, 0) + 1
        return dict(sorted(counts.items()))

    # ---- serialisation ------------------------------------------------
    def as_dict(self, longest_runs: int = 25) -> dict[str, Any]:
        """Stable, complete machine-readable structure (US-PM-6-9 consumes this).

        Nothing is truncated except the ``runs.longest`` sample, whose full
        content is already recoverable from the per-tool histograms; the bigram
        list and every histogram are emitted in full so a baseline diff never
        depends on a display limit.
        """
        total_calls = self.total_calls
        total_bytes = self.total_bytes
        payload: dict[str, Any] = {
            "corpus": self.extraction_summary,
            "totals": {
                "calls": total_calls,
                "matched": self.matched_calls,
                "unmatched": self.unmatched_calls,
                "sessions": self.sessions,
                "tools": len(self.tools),
                "response_bytes": total_bytes,
                "response_chars": self.total_chars,
                "estimated_tokens": self.estimated_tokens,
                "bytes_per_call": self.bytes_per_call.as_dict(),
                "calls_per_session": self.calls_per_session.as_dict(),
            },
            "by_tool": [
                usage.as_dict(total_calls, total_bytes) for usage in self.by_bytes()
            ],
            "runs": {
                "total": len(self.runs),
                "histogram": {str(k): v for k, v in self.run_histogram().items()},
                "longest": [run.as_dict() for run in self.longest_runs(longest_runs)],
            },
            "bigrams": [
                {"from": a, "to": b, "count": n} for a, b, n in self.top_bigrams()
            ],
        }
        if self.classification is not None:
            payload["failures"] = self.classification.as_dict()
        return payload


def build_report(
    calls: Iterable[ToolCall],
    classification: Classification | None = None,
    extraction_summary: dict[str, Any] | None = None,
) -> UsageReport:
    """Compute the usage report for ``calls``.

    ``classification`` is computed with
    :func:`~tools.usage_telemetry.classify.classify_all` when not supplied, so
    failure counts always come from the one classifier rather than a second
    definition of "failure" living here.
    """
    call_list = list(calls)
    if classification is None:
        classification = classify_all(call_list)

    report = UsageReport(
        calls=call_list,
        classification=classification,
        extraction_summary=extraction_summary,
    )

    for call in call_list:
        usage = report.tools.get(call.tool)
        if usage is None:
            usage = report.tools[call.tool] = ToolUsage(
                tool=call.tool, runs=RunProfile(tool=call.tool)
            )
        usage.calls += 1
        if call.result is None:
            usage.unmatched += 1
        else:
            usage.byte_samples.append(call.result.bytes)
            usage.result_chars += call.result.chars

    for item in classification.classified:
        # ``.get`` rather than ``[]``: a caller-supplied classification may not
        # cover exactly these calls, and a mismatch should not raise here.
        usage = report.tools.get(item.tool)
        if item.failed and usage is not None:
            usage.failures += 1

    for run in iter_runs(call_list):
        report.runs.append(run)
        report.tools[run.tool].runs.lengths.append(run.length)

    for pair in iter_bigrams(call_list):
        report.bigrams[pair] = report.bigrams.get(pair, 0) + 1

    return report


# ------------------------------------------------------------------ output --


def _n(value: Any) -> str:
    """Format a number for the text report; ``-`` for a missing sample."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.0f}"
    return f"{value:,}"


def _mib(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f} MiB"


def format_usage_report(report: UsageReport, top: int = DEFAULT_TOP) -> str:
    """Human-readable rendering of a :class:`UsageReport`."""
    total_calls = report.total_calls
    total_bytes = report.total_bytes
    per_call = report.bytes_per_call
    per_session = report.calls_per_session

    lines = [
        f"calls                 {_n(total_calls)} across {_n(report.sessions)} transcripts",
        f"matched               {_n(report.matched_calls)} "
        f"({report.matched_calls / total_calls if total_calls else 0:.2%}), "
        f"{_n(report.unmatched_calls)} unmatched",
        f"response bytes        {_n(total_bytes)} ({_mib(total_bytes)}, "
        f"~{_n(report.estimated_tokens)} tokens)",
        f"bytes per call        median {_n(per_call.median)}  p90 {_n(per_call.p90)}  "
        f"p95 {_n(per_call.p95)}  p99 {_n(per_call.p99)}  max {_n(per_call.maximum)}  "
        f"(mean {_n(per_call.mean)})",
        f"calls per transcript  median {_n(per_session.median)}  "
        f"p90 {_n(per_session.p90)}  max {_n(per_session.maximum)}",
    ]

    if report.classification is not None:
        cls = report.classification
        # The three classes are rendered as three separate figures, never as a
        # single "errors" number: an is_error-only metric reports ~1.4% on a
        # corpus whose true failure rate is 6.2% (US-PM-6 AC 2).
        lines += [
            f"failures              {_n(cls.failures)} ({cls.failure_rate:.2%}) "
            "distinct calls -- the three classes below overlap, so they are "
            "not a sum",
            f"  hard errors         {_n(cls.hard)} ({cls.hard_rate:.2%})  (is_error)",
            f"  soft errors         {_n(cls.soft)} ({cls.soft_rate:.2%})  "
            "(error body, is_error false)",
            f"  malformed inputs    {_n(cls.malformed)} ({cls.malformed_rate:.2%})  "
            f"({MALFORMED_INPUT_KEY})",
            "  full breakdown      python -m tools.usage_telemetry.classify",
        ]

    lines += [
        "",
        "response bytes by tool (total bytes is the context cost)",
        f"  {'tool':<22}{'calls':>6}{'%calls':>8}{'bytes':>12}{'%bytes':>8}"
        f"{'B/call':>9}{'median':>9}{'p90':>9}{'p95':>9}{'max':>9}",
    ]
    for usage in report.by_bytes():
        dist = usage.bytes_per_call
        lines.append(
            f"  {usage.tool:<22}{_n(usage.calls):>6}"
            f"{usage.calls / total_calls if total_calls else 0:>8.1%}"
            f"{_n(usage.result_bytes):>12}"
            f"{usage.result_bytes / total_bytes if total_bytes else 0:>8.1%}"
            f"{_n(usage.mean_bytes):>9}{_n(dist.median):>9}{_n(dist.p90):>9}"
            f"{_n(dist.p95):>9}{_n(dist.maximum):>9}"
        )

    lines += [
        "",
        "consecutive runs within one transcript (a run of N is N-1 avoidable calls)",
        f"  {'tool':<22}{'runs':>6}{'>=2':>7}{'>=3':>7}{'longest':>9}"
        f"{'in runs>=2':>12}{'removable':>11}",
    ]
    ranked_runs = sorted(
        report.tools.values(),
        key=lambda u: (-u.runs.removable_calls, -u.runs.longest, u.tool),
    )
    for usage in ranked_runs:
        if not usage.runs.lengths:
            continue
        profile = usage.runs
        lines.append(
            f"  {usage.tool:<22}{_n(profile.runs):>6}{_n(profile.runs_at_least(2)):>7}"
            f"{_n(profile.runs_at_least(3)):>7}{_n(profile.longest):>9}"
            f"{_n(profile.calls_at_least(2)):>12}{_n(profile.removable_calls):>11}"
        )

    histogram = report.run_histogram()
    if histogram:
        lines += ["", "run-length histogram (all tools)"]
        for length, count in histogram.items():
            lines.append(f"  len {length:<4}{_n(count):>8} runs")

    longest = report.longest_runs(top)
    if longest:
        lines += ["", f"longest runs (top {len(longest)})"]
        for run in longest:
            lines.append(
                f"  {run.length:>5}  {run.tool:<22}{run.session} @ seq {run.start_seq}"
            )

    bigrams = report.top_bigrams(top)
    if bigrams:
        lines += ["", f"top adjacency bigrams within one transcript (top {len(bigrams)})"]
        for first, second, count in bigrams:
            lines.append(f"  {_n(count):>6}  {first:<22}-> {second}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.usage_telemetry.report",
        description=(
            "Per-tool call counts, response bytes, consecutive-run lengths and "
            "adjacency bigrams for ProjectMan MCP tool calls."
        ),
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Transcript root (default: $CLAUDE_PROJECTS_DIR or ~/.claude/projects)",
    )
    parser.add_argument(
        "--prefix",
        default=TOOL_PREFIX,
        help=f"Tool-name prefix to report on (default: {TOOL_PREFIX}; '' for all tools)",
    )
    parser.add_argument(
        "--min-match-rate",
        type=float,
        default=None,
        help="Fail before reporting if the call->result join rate is below this",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=(
            f"How many bigrams / longest runs to show in the text report "
            f"(default {DEFAULT_TOP}; --json is never truncated)"
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Also write the full JSON report to this path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text",
    )
    return parser


def report_from_extraction(extraction: Extraction) -> UsageReport:
    """Build a :class:`UsageReport` from a completed extraction pass."""
    return build_report(
        extraction.calls,
        classification=classify_all(extraction.calls),
        extraction_summary=extraction.summary(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        extraction = scan(
            root=args.root, tool_prefix=args.prefix, min_match_rate=args.min_match_rate
        )
    except MatchRateError as exc:
        # Exit 1 (bad join) rather than a traceback: US-PM-6-9 scripts this CLI
        # and a partial join must never look like an empty corpus (exit 2).
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = report_from_extraction(extraction)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(format_usage_report(report, top=args.top))

    if args.out:
        out = Path(args.out).expanduser()
        if str(out.parent) not in ("", "."):
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        print(f"wrote JSON report to {out}", file=sys.stderr)

    if report.total_calls == 0:
        print(f"error: no {extraction.tool_prefix}* calls found", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
