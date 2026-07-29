"""Failure classification: hard errors, soft errors and malformed inputs.

This is the step two of the four studies in ``Study/`` got wrong. Two of them
counted only ``is_error`` and reported ~1% failure rates on corpora where the
real rate was 6-12%. Three classes exist and all three have to be counted::

    hard error       tool_result.is_error is true -- the transport reported a
                     failure (``<tool_use_error>InputValidationError: ...`` or
                     ``Error executing tool pm_x: 1 validation error ...``).

    soft error       the call succeeded at the transport layer (is_error false)
                     but the body *is* an error envelope:
                     ``{"result":"error: Run-log note must be 1024 ..."}``.
                     Invisible to any metric keyed off ``is_error``.

    malformed input  the arguments never parsed as JSON, so the harness hands
                     the raw text over as an ``__unparsedToolInput`` key in the
                     input dict rather than failing to parse. Counting parse
                     failures finds none of these; counting the key finds all.

Matching the soft-error prefix precisely matters. A loose ``error:\\s`` search
anywhere in the body also matches ordinary successful payloads -- ``pm_get`` on
a missing id returns ``- id: US-X-1\\n  error: 'Task not found'`` *inside* a
successful listing, and ``pm_estimate`` echoes story titles containing the word.
On the reference corpus the loose search over-counts by 6 calls. The patterns in
:data:`SOFT_ERROR_PATTERNS` are therefore anchored at the start of the body.

Precedence
----------
The classes overlap: on the reference corpus every one of the 27 malformed calls
*also* carries ``is_error``, because the harness rejects unparsable input at the
transport layer. Precedence for the *primary* (exclusive) class is::

    malformed input  >  hard error  >  soft error  >  success

Malformed wins because ``__unparsedToolInput`` is the root cause and the hard
error is only its downstream symptom; attributing those 27 to "hard error" would
hide the one thing that is actually fixable.

Both views are reported, so neither number is a surprise:

* **inclusive** counts -- every call carrying the marker, classes may overlap
  and therefore sum to more than the failure total (this is what the studies
  quote: 47 hard / 161 soft / 27 malformed);
* **exclusive** counts -- each call attributed to exactly one primary class,
  which sum *exactly* to the failure total.

The combined true failure rate is always a count of **distinct** calls, so it
can never double-count a call that is both malformed and hard.

Calls with no joined result (``matched`` false) are classified
:data:`UNMATCHED` and counted as neither success nor failure -- the extraction
pass already fails loudly below a 99% join rate (US-PM-6-6), so this should be
empty in practice.

Usage::

    python -m tools.usage_telemetry.classify
    python -m tools.usage_telemetry.classify --root /path/to/projects --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tools.usage_telemetry.extract import TOOL_PREFIX, ToolCall, scan

#: Input-dict key the harness inserts when tool arguments did not parse as JSON.
MALFORMED_INPUT_KEY = "__unparsedToolInput"

#: Primary class names.
HARD_ERROR = "hard_error"
SOFT_ERROR = "soft_error"
MALFORMED_INPUT = "malformed_input"
SUCCESS = "success"
UNMATCHED = "unmatched"

#: Primary classes in precedence order -- first match wins. See module docstring.
PRECEDENCE = (MALFORMED_INPUT, HARD_ERROR, SOFT_ERROR)

#: Classes that count towards the combined true failure rate.
FAILURE_CLASSES = frozenset(PRECEDENCE)

#: Soft-error body patterns, in the order they are tried. Each is anchored at
#: the start of the response body: an unanchored search also matches successful
#: payloads that merely *contain* an ``error:`` field (see module docstring).
#:
#: ``envelope`` is the MCP server's own shape, ``json.dumps({"result": "error: ..."})``
#: -- the one the studies matched as ``"result":"error:``. ``bare`` catches
#: bodies that are not the envelope at all, e.g. the harness's own
#: ``Error: result (74,006 characters) exceeds maximum allowed tokens``, which
#: is a real failed call whose payload never reached the caller.
SOFT_ERROR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("envelope", re.compile(r'^\s*\{\s*"result"\s*:\s*"error:', re.IGNORECASE)),
    ("bare", re.compile(r"^\s*error:", re.IGNORECASE)),
)

#: Soft-error messages are truncated to this many characters when grouped.
MESSAGE_CHARS = 160

_MESSAGE_RE = re.compile(r"^\s*error:\s*(.*)", re.IGNORECASE)


def is_malformed_input(call: ToolCall) -> bool:
    """True when the harness could not parse this call's arguments as JSON."""
    return MALFORMED_INPUT_KEY in (call.input or {})


def is_hard_error(call: ToolCall) -> bool:
    """True when the joined ``tool_result`` carries ``is_error``."""
    return call.result is not None and call.result.is_error


def soft_error_pattern(text: str | None) -> str | None:
    """Name of the first :data:`SOFT_ERROR_PATTERNS` entry matching ``text``.

    Returns ``None`` when the body is not an error envelope.
    """
    if not text:
        return None
    for name, pattern in SOFT_ERROR_PATTERNS:
        if pattern.match(text):
            return name
    return None


def is_soft_error(call: ToolCall) -> bool:
    """True when the body is an error envelope, regardless of ``is_error``.

    Soft and hard are measured independently so the overlap between them stays
    visible; :attr:`CallClass.primary` is what applies precedence.
    """
    return call.result is not None and soft_error_pattern(call.result.text) is not None


def soft_error_message(text: str | None, limit: int = MESSAGE_CHARS) -> str | None:
    """The human-readable message from a soft-error body, or ``None``.

    Unwraps the ``{"result": "..."}`` envelope when present, strips the
    ``error:`` prefix and keeps the first line, so that messages with variable
    tails (blocker lists, ids) group together.
    """
    if not text:
        return None
    body = text
    try:
        decoded = json.loads(text)
    except ValueError:
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("result"), str):
        body = decoded["result"]
    match = _MESSAGE_RE.match(body)
    if not match:
        return None
    message = match.group(1).splitlines()[0].strip() if match.group(1).strip() else ""
    return message[:limit] if limit > 0 else message


@dataclass(frozen=True)
class CallClass:
    """How one joined call classifies, in both the inclusive and primary views."""

    call: ToolCall
    matched: bool
    malformed: bool
    hard: bool
    soft: bool
    soft_pattern: str | None = None
    message: str | None = None

    @property
    def tool(self) -> str:
        return self.call.tool

    @property
    def failed(self) -> bool:
        """True when the call carries any failure marker.

        An unmatched call is *not* a failure -- its outcome is unknown.
        """
        return self.malformed or self.hard or self.soft

    @property
    def primary(self) -> str:
        """The single class this call is attributed to. See :data:`PRECEDENCE`."""
        if not self.matched and not self.malformed:
            return UNMATCHED
        if self.malformed:
            return MALFORMED_INPUT
        if self.hard:
            return HARD_ERROR
        if self.soft:
            return SOFT_ERROR
        return SUCCESS

    @property
    def classes(self) -> tuple[str, ...]:
        """Every failure class this call carries, in precedence order."""
        carried = {
            MALFORMED_INPUT: self.malformed,
            HARD_ERROR: self.hard,
            SOFT_ERROR: self.soft,
        }
        return tuple(name for name in PRECEDENCE if carried[name])


def classify(call: ToolCall) -> CallClass:
    """Classify a single joined call across all three failure classes."""
    text = call.result.text if call.result is not None else None
    pattern = soft_error_pattern(text)
    return CallClass(
        call=call,
        matched=call.result is not None,
        malformed=is_malformed_input(call),
        hard=is_hard_error(call),
        soft=pattern is not None,
        soft_pattern=pattern,
        message=soft_error_message(text) if pattern else None,
    )


@dataclass
class ToolBreakdown:
    """Per-tool counts. Class counts are inclusive; ``failures`` is distinct."""

    tool: str
    calls: int = 0
    hard: int = 0
    soft: int = 0
    malformed: int = 0
    failures: int = 0
    unmatched: int = 0

    @property
    def successes(self) -> int:
        return self.calls - self.failures - self.unmatched

    @property
    def failure_rate(self) -> float:
        return self.failures / self.calls if self.calls else 0.0

    @property
    def hard_rate(self) -> float:
        return self.hard / self.calls if self.calls else 0.0

    @property
    def soft_rate(self) -> float:
        return self.soft / self.calls if self.calls else 0.0

    @property
    def malformed_rate(self) -> float:
        return self.malformed / self.calls if self.calls else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "calls": self.calls,
            "hard": self.hard,
            "soft": self.soft,
            "malformed": self.malformed,
            "failures": self.failures,
            "unmatched": self.unmatched,
            "successes": self.successes,
            "failure_rate": self.failure_rate,
        }


@dataclass
class Classification:
    """Corpus-level failure classification.

    ``hard``/``soft``/``malformed`` are *inclusive* counts and may overlap;
    ``primary_counts`` partitions the same calls into exactly one class each.
    ``failures`` is always the number of distinct failing calls.
    """

    classified: list[CallClass] = field(default_factory=list)

    # ---- totals -------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.classified)

    @property
    def unmatched(self) -> int:
        return sum(1 for c in self.classified if c.primary == UNMATCHED)

    @property
    def hard(self) -> int:
        """Inclusive: every call with ``is_error``, however else it classifies."""
        return sum(1 for c in self.classified if c.hard)

    @property
    def soft(self) -> int:
        """Inclusive: every call whose body is an error envelope."""
        return sum(1 for c in self.classified if c.soft)

    @property
    def malformed(self) -> int:
        """Inclusive: every call carrying ``__unparsedToolInput``."""
        return sum(1 for c in self.classified if c.malformed)

    @property
    def failures(self) -> int:
        """Distinct failing calls -- never a sum of the three classes."""
        return sum(1 for c in self.classified if c.failed)

    @property
    def successes(self) -> int:
        return sum(1 for c in self.classified if c.primary == SUCCESS)

    # ---- rates --------------------------------------------------------
    def _rate(self, count: int) -> float:
        return count / self.total if self.total else 0.0

    @property
    def hard_rate(self) -> float:
        return self._rate(self.hard)

    @property
    def soft_rate(self) -> float:
        return self._rate(self.soft)

    @property
    def malformed_rate(self) -> float:
        return self._rate(self.malformed)

    @property
    def failure_rate(self) -> float:
        """The combined true failure rate: distinct failures over all calls."""
        return self._rate(self.failures)

    # ---- views --------------------------------------------------------
    @property
    def primary_counts(self) -> dict[str, int]:
        """Exclusive partition; the failure classes sum to :attr:`failures`."""
        counts = dict.fromkeys(
            (MALFORMED_INPUT, HARD_ERROR, SOFT_ERROR, SUCCESS, UNMATCHED), 0
        )
        for item in self.classified:
            counts[item.primary] += 1
        return counts

    @property
    def overlaps(self) -> dict[str, int]:
        """Counts of calls carrying more than one class, keyed ``a+b``."""
        counts: dict[str, int] = {}
        for item in self.classified:
            if len(item.classes) > 1:
                counts["+".join(item.classes)] = counts.get("+".join(item.classes), 0) + 1
        return counts

    @property
    def soft_patterns(self) -> dict[str, int]:
        """How many soft errors each :data:`SOFT_ERROR_PATTERNS` entry matched."""
        counts = {name: 0 for name, _ in SOFT_ERROR_PATTERNS}
        for item in self.classified:
            if item.soft_pattern:
                counts[item.soft_pattern] += 1
        return counts

    def failing(self, cls: str | None = None) -> list[CallClass]:
        """Failing calls, optionally restricted to one *inclusive* class."""
        if cls is None:
            return [c for c in self.classified if c.failed]
        if cls == MALFORMED_INPUT:
            return [c for c in self.classified if c.malformed]
        if cls == HARD_ERROR:
            return [c for c in self.classified if c.hard]
        if cls == SOFT_ERROR:
            return [c for c in self.classified if c.soft]
        raise ValueError(f"unknown failure class {cls!r}")

    def by_tool(self) -> dict[str, ToolBreakdown]:
        """Per-tool breakdown, ordered by failures then calls, descending."""
        table: dict[str, ToolBreakdown] = {}
        for item in self.classified:
            row = table.get(item.tool)
            if row is None:
                row = table[item.tool] = ToolBreakdown(tool=item.tool)
            row.calls += 1
            row.hard += item.hard
            row.soft += item.soft
            row.malformed += item.malformed
            row.failures += item.failed
            row.unmatched += item.primary == UNMATCHED
        return dict(
            sorted(table.items(), key=lambda kv: (-kv[1].failures, -kv[1].calls, kv[0]))
        )

    def top_messages(self, limit: int = 10) -> list[tuple[str, str, int]]:
        """Most frequent ``(tool, message, count)`` soft-error messages."""
        counts: dict[tuple[str, str], int] = {}
        for item in self.classified:
            if item.soft and item.message is not None:
                key = (item.tool, item.message)
                counts[key] = counts.get(key, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(tool, message, n) for (tool, message), n in ranked[:limit]]

    def as_dict(self) -> dict[str, Any]:
        """Machine-readable summary."""
        return {
            "total_calls": self.total,
            "unmatched": self.unmatched,
            "inclusive": {
                "hard_error": self.hard,
                "soft_error": self.soft,
                "malformed_input": self.malformed,
            },
            "rates": {
                "hard_error": self.hard_rate,
                "soft_error": self.soft_rate,
                "malformed_input": self.malformed_rate,
                "combined_failure_rate": self.failure_rate,
            },
            "exclusive": self.primary_counts,
            "overlaps": self.overlaps,
            "soft_patterns": self.soft_patterns,
            "failures": self.failures,
            "successes": self.successes,
            "by_tool": [row.as_dict() for row in self.by_tool().values()],
            "top_soft_messages": [
                {"tool": tool, "message": message, "count": n}
                for tool, message, n in self.top_messages()
            ],
        }


def classify_all(calls: Iterable[ToolCall]) -> Classification:
    """Classify every joined call in ``calls``."""
    return Classification(classified=[classify(call) for call in calls])


def format_report(report: Classification) -> str:
    """Human-readable rendering of a :class:`Classification`."""
    exclusive = report.primary_counts
    lines = [
        f"calls                 {report.total}",
        "",
        "failure classes (inclusive -- a call can carry more than one)",
        f"  hard errors         {report.hard:>6}  {report.hard_rate:>7.2%}  (is_error)",
        (
            f"  soft errors         {report.soft:>6}  {report.soft_rate:>7.2%}  "
            "(error body, is_error false)"
        ),
        (
            f"  malformed inputs    {report.malformed:>6}  "
            f"{report.malformed_rate:>7.2%}  ({MALFORMED_INPUT_KEY})"
        ),
        (
            f"  COMBINED (distinct) {report.failures:>6}  {report.failure_rate:>7.2%}  "
            "true failure rate"
        ),
        "",
        "primary class (exclusive -- malformed > hard > soft)",
        f"  malformed inputs    {exclusive[MALFORMED_INPUT]:>6}",
        f"  hard errors         {exclusive[HARD_ERROR]:>6}",
        f"  soft errors         {exclusive[SOFT_ERROR]:>6}",
        f"  successes           {exclusive[SUCCESS]:>6}",
        f"  unmatched           {exclusive[UNMATCHED]:>6}",
    ]

    overlaps = report.overlaps
    if overlaps:
        lines.append("")
        lines.append("overlaps")
        for key, count in sorted(overlaps.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {key:<34}{count:>6}")

    patterns = {k: v for k, v in report.soft_patterns.items() if v}
    if patterns:
        lines.append("")
        lines.append("soft-error patterns")
        for name, count in sorted(patterns.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name:<34}{count:>6}")

    lines.append("")
    lines.append("per tool (calls / hard / soft / malformed / failures / rate)")
    for row in report.by_tool().values():
        lines.append(
            f"  {row.tool:<22}{row.calls:>6}{row.hard:>7}{row.soft:>7}"
            f"{row.malformed:>11}{row.failures:>10}  {row.failure_rate:>7.2%}"
        )

    messages = report.top_messages()
    if messages:
        lines.append("")
        lines.append("top soft-error messages")
        for tool, message, count in messages:
            lines.append(f"  {count:>5}  {tool:<18}{message}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.usage_telemetry.classify",
        description=(
            "Classify ProjectMan MCP tool calls into hard errors, soft errors "
            "and malformed inputs, and report the combined true failure rate."
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
        help=f"Tool-name prefix to classify (default: {TOOL_PREFIX}; '' for all tools)",
    )
    parser.add_argument(
        "--min-match-rate",
        type=float,
        default=None,
        help="Fail before classifying if the call->result join rate is below this",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    extraction = scan(
        root=args.root, tool_prefix=args.prefix, min_match_rate=args.min_match_rate
    )
    report = classify_all(extraction.calls)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(format_report(report))

    if report.total == 0:
        print(f"error: no {extraction.tool_prefix}* calls found", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
