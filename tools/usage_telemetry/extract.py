"""Extraction pass: walk Claude Code transcripts and join tool calls to results.

Method (ported from the four studies in `the original usage studies`)::

    1. Walk every ``*.jsonl`` under ~/.claude/projects.
    2. Pass one  — collect ``tool_use`` blocks whose name starts with the tool
                   prefix (default ``mcp__projectman__``).
    3. Pass two  — collect **every** ``tool_result`` block, keyed by
                   ``tool_use_id``, with **no** filtering whatsoever.
    4. Join on ``tool_use_id`` and verify the match rate before trusting any
       downstream number.

The trap (an internal usage study, appendix): ``tool_result`` records do *not*
contain the string ``projectman`` anywhere. Pre-filtering result lines by that
string silently drops ~98% of results and every downstream statistic with them.
Both passes happen in a single read of each file, but the result collector is
deliberately unconditional -- do not "optimise" it by filtering.

What is deliberately *not* done here (later tasks in US-PM-6):

* failure classification (hard / soft / malformed)  -- US-PM-6-7
* the metrics report (counts, bytes, run lengths)   -- US-PM-6-8
* baseline capture                                  -- US-PM-6-9

Everything those need is preserved on :class:`ToolCall`: the raw ``input`` dict
(so ``__unparsedToolInput`` stays visible), ``is_error``, the *untruncated*
result text and byte count, and a per-session sequence number in transcript
order (so consecutive-run analysis is possible without re-reading anything).

Usage::

    python -m tools.usage_telemetry --out pm_calls.jsonl
    python -m tools.usage_telemetry --root /path/to/projects --min-match-rate 0.99
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Tool-name prefix identifying ProjectMan MCP calls.
TOOL_PREFIX = "mcp__projectman__"

#: Below this call->result join rate the corpus is not trustworthy and the run
#: is expected to fail loudly rather than report numbers built on a partial join.
DEFAULT_MIN_MATCH_RATE = 0.99

#: Studies truncated captured result bodies at this many characters. Byte/char
#: counts are always taken from the *full* body; only the stored preview is cut.
DEFAULT_PREVIEW_CHARS = 4000


class MatchRateError(RuntimeError):
    """Raised when the call->result join rate falls below the required minimum."""


def default_transcript_root() -> Path:
    """Root directory holding Claude Code session transcripts.

    Honours ``CLAUDE_PROJECTS_DIR`` so the scan can be pointed at a fixture
    corpus without touching the caller's real history.
    """
    env = os.environ.get("CLAUDE_PROJECTS_DIR")
    if env:
        return Path(env).expanduser()
    return Path("~/.claude/projects").expanduser()


@dataclass
class ToolResult:
    """A ``tool_result`` block, collected without any name-based filtering."""

    tool_use_id: str
    is_error: bool
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def bytes(self) -> int:
        return len(self.text.encode("utf-8", errors="replace"))


@dataclass
class ToolCall:
    """A ``tool_use`` block, plus its joined result once :func:`join` has run."""

    tool_use_id: str
    name: str
    input: dict[str, Any]
    timestamp: str | None
    #: Transcript file stem. This -- not ``session_id`` -- is the chronological
    #: ordering unit: a single ``session_id`` can span several transcript files
    #: (resumes, subagents), and interleaving those would invent adjacencies
    #: that never happened. The reference studies group by file for the same
    #: reason.
    session: str
    #: ``sessionId`` from the transcript record; may repeat across files.
    session_id: str | None
    project: str
    source_file: str
    line_no: int
    #: Position within ``session``, in transcript order, starting at 0.
    seq: int
    is_sidechain: bool = False
    result: ToolResult | None = None

    @property
    def tool(self) -> str:
        """Short tool name with the MCP prefix stripped (``pm_update``)."""
        _, sep, short = self.name.rpartition("__")
        return short if sep else self.name

    @property
    def matched(self) -> bool:
        return self.result is not None

    def to_record(self, preview_chars: int = DEFAULT_PREVIEW_CHARS) -> dict[str, Any]:
        """Flatten to a JSON-serialisable record (one line of the JSONL output).

        ``preview_chars <= 0`` stores the full result body.
        """
        text = self.result.text if self.result else None
        if text is not None and preview_chars > 0:
            text = text[:preview_chars]
        return {
            "tool_use_id": self.tool_use_id,
            "name": self.name,
            "tool": self.tool,
            "input": self.input,
            "ts": self.timestamp,
            "sess": self.session,
            "proj": self.project,
            "file": self.source_file,
            "line": self.line_no,
            "session_id": self.session_id,
            "seq": self.seq,
            "isSidechain": self.is_sidechain,
            "matched": self.matched,
            "is_error": self.result.is_error if self.result else None,
            "result_chars": self.result.chars if self.result else None,
            "result_bytes": self.result.bytes if self.result else None,
            "result_truncated": (
                bool(self.result and preview_chars > 0 and self.result.chars > preview_chars)
            ),
            "result_text": text,
        }


@dataclass
class ScanStats:
    """Corpus-level counters, reported so a bad scan is visible immediately."""

    files_scanned: int = 0
    files_unreadable: int = 0
    lines_read: int = 0
    blank_lines: int = 0
    json_parse_failures: int = 0
    tool_use_blocks_total: int = 0
    tool_result_blocks_total: int = 0
    duplicate_result_ids: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))


@dataclass
class Extraction:
    """Result of the extraction pass: prefix-filtered calls joined to results."""

    calls: list[ToolCall] = field(default_factory=list)
    results: dict[str, ToolResult] = field(default_factory=dict)
    stats: ScanStats = field(default_factory=ScanStats)
    tool_prefix: str = TOOL_PREFIX
    root: Path | None = None

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def matched_calls(self) -> list[ToolCall]:
        return [c for c in self.calls if c.matched]

    @property
    def unmatched_calls(self) -> list[ToolCall]:
        return [c for c in self.calls if not c.matched]

    @property
    def match_rate(self) -> float:
        """Fraction of prefix-matched calls that found a result.

        An empty corpus is vacuously 1.0; use :attr:`total_calls` to detect it.
        """
        if not self.calls:
            return 1.0
        return sum(1 for c in self.calls if c.matched) / len(self.calls)

    @property
    def sessions(self) -> set[str]:
        return {c.session for c in self.calls}

    @property
    def projects(self) -> set[str]:
        return {c.project for c in self.calls}

    @property
    def session_ids(self) -> set[str]:
        return {c.session_id for c in self.calls if c.session_id}

    def calls_by_session(self) -> dict[str, list[ToolCall]]:
        """Calls grouped by transcript file, each list in transcript order.

        Consecutive-run and bigram analysis (US-PM-6-8) builds on this. Grouping
        is by transcript (``ToolCall.session``) rather than ``session_id`` --
        see the note on :class:`ToolCall`.
        """
        grouped: dict[str, list[ToolCall]] = {}
        for call in self.calls:
            grouped.setdefault(call.session, []).append(call)
        for calls in grouped.values():
            calls.sort(key=lambda c: c.seq)
        return grouped

    def assert_match_rate(self, minimum: float = DEFAULT_MIN_MATCH_RATE) -> float:
        """Fail loudly when the join rate is below ``minimum``.

        A low match rate almost always means the result collector was filtered
        by tool name -- the trap this module exists to avoid.

        ``minimum`` must be a real fraction in ``[0, 1]``. A NaN threshold would
        make every comparison false and silently disable the only guard this
        module has, so it is rejected rather than honoured.
        """
        if not 0.0 <= minimum <= 1.0:  # also rejects NaN, which fails both sides
            raise ValueError(
                f"min_match_rate must be a fraction between 0 and 1, got {minimum!r} "
                "(99% is 0.99, not 99)"
            )
        rate = self.match_rate
        if rate < minimum:
            missing = len(self.unmatched_calls)
            raise MatchRateError(
                f"call->result match rate {rate:.4%} is below the required "
                f"{minimum:.4%}: {missing} of {self.total_calls} "
                f"{self.tool_prefix}* calls have no tool_result. "
                "Do NOT trust any downstream number. Most likely cause: "
                "tool_result blocks were filtered before the join (they never "
                "contain the tool name), or the corpus is truncated mid-session."
            )
        return rate

    def summary(self) -> dict[str, Any]:
        """Machine-readable summary of the extraction pass."""
        return {
            "root": str(self.root) if self.root else None,
            "tool_prefix": self.tool_prefix,
            "files_scanned": self.stats.files_scanned,
            "files_unreadable": self.stats.files_unreadable,
            "json_parse_failures": self.stats.json_parse_failures,
            "tool_use_blocks_total": self.stats.tool_use_blocks_total,
            "tool_result_blocks_total": self.stats.tool_result_blocks_total,
            "calls": self.total_calls,
            "matched": len(self.matched_calls),
            "unmatched": len(self.unmatched_calls),
            "match_rate": self.match_rate,
            "sessions": len(self.sessions),
            "session_ids": len(self.session_ids),
            "projects": sorted(self.projects),
        }


def iter_transcript_files(root: Path) -> list[Path]:
    """All ``*.jsonl`` transcripts under ``root``, in deterministic order.

    Sorted order matters: per-session sequence numbers are assigned in read
    order, so an unstable walk would make run-length analysis unstable too.
    """
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())


def _project_name(path: Path, root: Path) -> str:
    """First path component under ``root`` -- the encoded project directory."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return path.parent.name
    return rel.parts[0] if len(rel.parts) > 1 else path.stem


def _result_text(content: Any) -> str:
    """Normalise a ``tool_result`` body to plain text.

    Bodies arrive either as a bare string or as a list of content blocks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    if content is None:
        return ""
    return json.dumps(content, default=str)


def iter_records(path: Path, stats: ScanStats) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a transcript, counting malformed lines."""
    try:
        handle = path.open("r", errors="replace")
    except OSError:
        stats.files_unreadable += 1
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                stats.blank_lines += 1
                continue
            stats.lines_read += 1
            try:
                record = json.loads(line)
            except ValueError:
                stats.json_parse_failures += 1
                continue
            if isinstance(record, dict):
                yield record


def scan(
    root: Path | str | None = None,
    tool_prefix: str = TOOL_PREFIX,
    min_match_rate: float | None = None,
) -> Extraction:
    """Run the extraction pass over a transcript corpus.

    Args:
        root: Transcript root. Defaults to :func:`default_transcript_root`.
        tool_prefix: Only ``tool_use`` blocks with this name prefix are kept.
            Pass ``""`` to keep every tool call.
        min_match_rate: When set, :meth:`Extraction.assert_match_rate` is called
            before returning, so a bad join raises instead of returning data.

    Returns:
        An :class:`Extraction` with calls already joined to their results.
    """
    root = Path(root).expanduser() if root is not None else default_transcript_root()
    extraction = Extraction(tool_prefix=tool_prefix, root=root)
    stats = extraction.stats

    for path in iter_transcript_files(root):
        stats.files_scanned += 1
        project = _project_name(path, root)
        session = path.stem
        seq = 0
        for line_no, record in enumerate(iter_records(path, stats), start=1):
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            session_id = record.get("sessionId")
            timestamp = record.get("timestamp")
            is_sidechain = bool(record.get("isSidechain"))

            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")

                if block_type == "tool_use":
                    # Pass one: prefix-filtered tool calls.
                    stats.tool_use_blocks_total += 1
                    name = block.get("name") or ""
                    if tool_prefix and not name.startswith(tool_prefix):
                        continue
                    tool_use_id = block.get("id")
                    if not tool_use_id:
                        continue
                    raw_input = block.get("input")
                    extraction.calls.append(
                        ToolCall(
                            tool_use_id=tool_use_id,
                            name=name,
                            input=raw_input if isinstance(raw_input, dict) else {},
                            timestamp=timestamp,
                            session=session,
                            session_id=session_id,
                            project=project,
                            source_file=str(path),
                            line_no=line_no,
                            seq=seq,
                            is_sidechain=is_sidechain,
                        )
                    )
                    seq += 1

                elif block_type == "tool_result":
                    # Pass two: EVERY result, unfiltered. Result records never
                    # contain the tool name -- filtering here drops ~98% of them.
                    stats.tool_result_blocks_total += 1
                    tool_use_id = block.get("tool_use_id")
                    if not tool_use_id:
                        continue
                    if tool_use_id in extraction.results:
                        stats.duplicate_result_ids += 1
                    extraction.results[tool_use_id] = ToolResult(
                        tool_use_id=tool_use_id,
                        is_error=bool(block.get("is_error")),
                        text=_result_text(block.get("content")),
                    )

    join(extraction)
    if min_match_rate is not None:
        extraction.assert_match_rate(min_match_rate)
    return extraction


def join(extraction: Extraction) -> Extraction:
    """Attach each call's result by ``tool_use_id``. Idempotent."""
    for call in extraction.calls:
        call.result = extraction.results.get(call.tool_use_id)
    return extraction


def write_jsonl(
    extraction: Extraction,
    path: Path | str,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
) -> int:
    """Write one JSON record per joined call. Returns the number written."""
    path = Path(path).expanduser()
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8") as out:
        for call in extraction.calls:
            out.write(json.dumps(call.to_record(preview_chars), default=str) + "\n")
            written += 1
    return written


def _format_summary(extraction: Extraction) -> str:
    s = extraction.summary()
    lines = [
        f"root                  {s['root']}",
        f"tool prefix           {s['tool_prefix']}",
        (
            f"transcript files      {s['files_scanned']} "
            f"({s['files_unreadable']} unreadable, {s['json_parse_failures']} bad JSON lines)"
        ),
        f"tool_use blocks       {s['tool_use_blocks_total']} (all tools)",
        f"tool_result blocks    {s['tool_result_blocks_total']} (unfiltered)",
        (
            f"matched calls         {s['calls']} across {s['sessions']} transcripts "
            f"({s['session_ids']} session ids)"
        ),
        f"match rate            {s['matched']}/{s['calls']} ({s['match_rate']:.2%})",
        f"projects              {', '.join(s['projects']) or '-'}",
    ]
    return "\n".join(lines)


def _match_rate_arg(value: str) -> float:
    """argparse type for ``--min-match-rate``: a real fraction in ``[0, 1]``.

    ``float("nan")`` parses happily and would turn the threshold comparison into
    a no-op, so the guard is validated at the boundary instead of trusting input.
    """
    try:
        rate = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not 0.0 <= rate <= 1.0:  # NaN fails both comparisons and lands here too
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a fraction between 0 and 1 (99% is 0.99, not 99)"
        )
    return rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.usage_telemetry",
        description=(
            "Extraction pass for the ProjectMan usage-telemetry study: walk "
            "Claude Code transcripts and join tool calls to their results."
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
        help=f"Tool-name prefix to extract (default: {TOOL_PREFIX}; '' for all tools)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write joined calls to this JSONL file",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=DEFAULT_PREVIEW_CHARS,
        help=(
            "Truncate stored result bodies to N chars (0 = full body). "
            f"Default {DEFAULT_PREVIEW_CHARS}; byte counts always use the full body."
        ),
    )
    parser.add_argument(
        "--min-match-rate",
        type=_match_rate_arg,
        default=DEFAULT_MIN_MATCH_RATE,
        help=f"Fail if the join rate drops below this (default {DEFAULT_MIN_MATCH_RATE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the summary as JSON instead of text",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    extraction = scan(root=args.root, tool_prefix=args.prefix)

    if args.json:
        print(json.dumps(extraction.summary(), indent=2))
    else:
        print(_format_summary(extraction))

    if args.out:
        written = write_jsonl(extraction, args.out, args.preview_chars)
        print(f"wrote {written} records to {args.out}", file=sys.stderr)

    if extraction.stats.files_scanned == 0:
        print(f"error: no transcripts found under {extraction.root}", file=sys.stderr)
        return 2
    if extraction.total_calls == 0:
        print(
            f"error: no {extraction.tool_prefix}* tool calls found under {extraction.root}",
            file=sys.stderr,
        )
        return 2

    try:
        extraction.assert_match_rate(args.min_match_rate)
    except MatchRateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for call in extraction.unmatched_calls[:10]:
            print(
                f"  unmatched {call.tool_use_id} {call.name} "
                f"{call.source_file}:{call.line_no}",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
