"""What an orchestrator run cost in context, read from the session transcript.

An orchestrated run's real price is not points or minutes, it is *context*:
every dispatch, every tool result and every cache miss grows the prompt the
orchestrator carries, and when it grows past the window the run stops.  The
measurement already exists — Claude Code writes each session to a JSONL
transcript under ``~/.claude/projects/<project>/<session>.jsonl``, and each
assistant record carries the usage the API reported for that call.  This
module turns one of those files into the numbers the epic's success criteria
are stated in, so every run is measured the same way instead of by whichever
scratchpad script was to hand.

The arithmetic that matters:

* ``input_tokens + cache_read_input_tokens + cache_creation_input_tokens`` is
  the context the model actually saw at that call.  Growth is the peak of
  that minus the first one.
* The harness writes **one record per content block**, all sharing the same
  ``message.id`` and the same ``usage``.  Counting records would multiply a
  single API call by its block count, so usage is counted once per message
  id and content blocks are deduped by their own ids.
* A *full cache miss* — the expensive kind — is a call whose fresh tokens
  (``cache_creation + input``) are more than half the context: the prefix
  cache expired and the whole prompt was re-sent.  The gap in minutes before
  it is the interesting part, because it is almost always a worker wait that
  outlived the one-hour cache TTL.

A transcript is somebody else's append-only output; nothing here may repair
it or refuse it.  Malformed lines, records with no usage, unparseable
timestamps and unmatched tool results are all *skipped*.  These functions
never raise on transcript content.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

#: Where Claude Code keeps session transcripts, one directory per project.
DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"

#: Tool name whose ``tool_use`` blocks are worker dispatches.
DISPATCH_TOOL = "Agent"

#: Tool-name suffixes whose ``tool_use`` blocks accept a finished task.  The
#: MCP prefix (``mcp__projectman__``) varies with how the server is mounted,
#: so only the tail is matched.
ACCEPT_TOOL_SUFFIXES = ("pm_accept", "pm_done_next")

#: Marker the harness wraps a finished worker's hand-back in.  The first user
#: record carrying it after a dispatch ends that dispatch's wait.
TASK_NOTIFICATION = "<task-notification>"

#: Fraction of the context above which fresh (uncached) tokens mean the
#: prefix cache was gone, not merely appended to.
MISS_FRACTION = 0.5


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list.

    Nearest rank, matching :mod:`projectman.durations`: with a handful of
    waits the answer should be a wait that actually happened rather than an
    average of two that did not.
    """
    rank = math.ceil(q * len(sorted_values))
    index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return sorted_values[index]


def _parse_timestamp(raw: Any) -> Optional[datetime]:
    """Parse a transcript timestamp to an aware UTC datetime, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int(value: Any) -> int:
    """A usage counter as an int; anything else counts as zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _blocks(message: Any) -> list[dict[str, Any]]:
    """The content blocks of a record's message, tolerating any other shape."""
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _text_of(block: dict[str, Any]) -> str:
    """The human-readable text of a block, for marker scanning."""
    text = block.get("text")
    return text if isinstance(text, str) else ""


def _result_bytes(content: Any) -> int:
    """Size of a ``tool_result`` payload in bytes.

    The harness writes the payload either as a plain string or as a list of
    ``{"type": "text", "text": ...}`` blocks; both are the same result to a
    reader, so both are measured as their UTF-8 length.
    """
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(_text_of(block).encode("utf-8", "replace"))
            elif isinstance(block, str):
                total += len(block.encode("utf-8", "replace"))
        return total
    if isinstance(content, dict):
        return len(_text_of(content).encode("utf-8", "replace"))
    return 0


def _is_accept(name: Any) -> bool:
    """True for the tool calls that close a task off."""
    return isinstance(name, str) and name.endswith(ACCEPT_TOOL_SUFFIXES)


def _records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the parsed records of a transcript, one line at a time.

    Streaming, never ``read()``: these files run to hundreds of megabytes.
    Malformed lines and anything that is not a JSON object are skipped.
    """
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(record, dict):
                yield record


def _file_contains(path: Path, needle: str) -> bool:
    """True when ``needle`` appears anywhere in the file, scanning by line."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if needle in line:
                    return True
    except OSError:
        return False
    return False


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    """``numerator / denominator`` to one decimal, or None when undefined."""
    if not denominator:
        return None
    return round(numerator / denominator, 1)


def find_transcripts(
    run_id: str, root: Optional[Path | str] = None
) -> list[Path]:
    """The transcripts mentioning ``run_id``, newest first.

    A run id is stamped into the orchestrator's own prompts and tool calls,
    so the file that contains the string is the file that recorded the run —
    no session-to-run index is needed.  Each candidate is scanned line by
    line and abandoned at the first hit, so a match costs a partial read.
    Unreadable files are skipped rather than raised over.
    """
    if not run_id:
        return []
    base = Path(root) if root is not None else DEFAULT_TRANSCRIPT_ROOT
    matches: list[Path] = []
    try:
        candidates = sorted(base.rglob("*.jsonl"))
    except OSError:
        return []
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if run_id in line:
                        matches.append(candidate)
                        break
        except OSError:
            continue

    def _mtime(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0

    matches.sort(key=_mtime, reverse=True)
    return matches


def analyze(path: Path | str, run_id: Optional[str] = None) -> dict[str, Any]:
    """Measure one transcript's context cost.

    ``run_id``, when given and present in the file, starts the accounting at
    the first record that mentions it: a session can hold several runs, and
    the base context of *this* run is what it had when the run began.  A run
    id that never appears is not an error — the whole file is measured.

    Returns a plain dict (JSON- and YAML-safe, no objects):

    ``base``/``peak``/``growth``
        Context at the first call, the largest context seen, and the
        difference.
    ``per_dispatch``/``per_task``
        Growth divided by dispatches and by accepted tasks, ``None`` when
        there were none of either.
    ``calls_per_dispatch``/``output_per_call``
        How many API calls a dispatch costs, and output tokens per call.
    ``tool_bytes``
        ``{tool name: bytes of tool_result content}``, largest first.
    ``waits``
        ``{p50, p90, max, n}`` minutes from an ``Agent`` launch to the task
        notification that answered it.
    ``misses``
        ``[{at, gap_min, tokens}]`` — every full cache miss, with the idle
        minutes before it (``None`` for the first call, which has no
        predecessor to be idle from).
    ``dispatches``/``accepts``/``calls``
        The raw counts the ratios are built from.
    """
    path = Path(path)

    seen_messages: set[str] = set()
    seen_blocks: set[str] = set()
    tool_names: dict[str, str] = {}
    tool_bytes: dict[str, int] = {}
    pending_launches: list[datetime] = []
    waits: list[float] = []
    misses: list[dict[str, Any]] = []

    base: Optional[int] = None
    peak = 0
    calls = 0
    dispatches = 0
    accepts = 0
    output_tokens = 0
    previous_call: Optional[datetime] = None
    # Gate on the run id only when the file actually mentions it: a run id
    # that never appears means this is not that run's transcript, and
    # measuring nothing would be a worse answer than measuring the file.
    started = not run_id or not _file_contains(path, run_id)

    for record in _records(path):
        if not started:
            # Cheap scan: the run id is somewhere in this record's JSON if
            # the run had started by the time it was written.
            try:
                started = run_id in json.dumps(record)
            except (TypeError, ValueError):
                started = False
            if not started:
                continue

        message = record.get("message")
        blocks = _blocks(message)
        role = record.get("type")
        if not isinstance(role, str):
            role = message.get("role") if isinstance(message, dict) else None
        timestamp = _parse_timestamp(record.get("timestamp"))

        if role == "assistant":
            usage = message.get("usage") if isinstance(message, dict) else None
            message_id = message.get("id") if isinstance(message, dict) else None
            fresh = counted = False
            if isinstance(usage, dict) and (
                not isinstance(message_id, str) or message_id not in seen_messages
            ):
                if isinstance(message_id, str):
                    seen_messages.add(message_id)
                counted = True
                inputs = _int(usage.get("input_tokens"))
                creation = _int(usage.get("cache_creation_input_tokens"))
                context = (
                    inputs + creation + _int(usage.get("cache_read_input_tokens"))
                )
                calls += 1
                output_tokens += _int(usage.get("output_tokens"))
                if base is None:
                    base = context
                peak = max(peak, context)
                fresh = context > 0 and (inputs + creation) > context * MISS_FRACTION
            if counted:
                if fresh:
                    gap = None
                    if timestamp is not None and previous_call is not None:
                        gap = round(
                            (timestamp - previous_call).total_seconds() / 60.0, 1
                        )
                    misses.append(
                        {
                            "at": timestamp.isoformat() if timestamp else None,
                            "gap_min": gap,
                            "tokens": inputs + creation,
                        }
                    )
                if timestamp is not None:
                    previous_call = timestamp

        for block in blocks:
            kind = block.get("type")
            if kind == "tool_use":
                block_id = block.get("id")
                if isinstance(block_id, str):
                    if block_id in seen_blocks:
                        continue
                    seen_blocks.add(block_id)
                name = block.get("name")
                if isinstance(block_id, str) and isinstance(name, str):
                    tool_names[block_id] = name
                if name == DISPATCH_TOOL:
                    dispatches += 1
                    if timestamp is not None:
                        pending_launches.append(timestamp)
                elif _is_accept(name):
                    accepts += 1
            elif kind == "tool_result":
                use_id = block.get("tool_use_id")
                name = tool_names.get(use_id, "unknown") if isinstance(use_id, str) else "unknown"
                size = _result_bytes(block.get("content"))
                if size:
                    tool_bytes[name] = tool_bytes.get(name, 0) + size

        if role == "user" and pending_launches and timestamp is not None:
            if any(TASK_NOTIFICATION in _text_of(block) for block in blocks):
                launched = pending_launches.pop(0)
                waits.append(
                    max((timestamp - launched).total_seconds() / 60.0, 0.0)
                )

    base_value = base if base is not None else 0
    growth = max(peak - base_value, 0)
    sorted_waits = sorted(waits)
    return {
        "base": base_value,
        "peak": peak,
        "growth": growth,
        "per_dispatch": _ratio(growth, dispatches),
        "per_task": _ratio(growth, accepts),
        "calls_per_dispatch": _ratio(calls, dispatches),
        "output_per_call": _ratio(output_tokens, calls),
        "tool_bytes": dict(
            sorted(tool_bytes.items(), key=lambda item: (-item[1], item[0]))
        ),
        "waits": {
            "p50": round(_percentile(sorted_waits, 0.5), 1) if sorted_waits else None,
            "p90": round(_percentile(sorted_waits, 0.9), 1) if sorted_waits else None,
            "max": round(sorted_waits[-1], 1) if sorted_waits else None,
            "n": len(sorted_waits),
        },
        "misses": misses,
        "dispatches": dispatches,
        "accepts": accepts,
        "calls": calls,
    }
