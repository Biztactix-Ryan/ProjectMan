"""Append-only activity log writer (JSONL format)."""

from __future__ import annotations

import json
from pathlib import Path

from projectman.models import LogEntry


def append_log_entry(path: Path, entry: LogEntry) -> None:
    """Atomically append a single LogEntry as a JSONL line.

    Opens in append mode so existing content is never overwritten.
    Each entry is serialized as compact JSON (no embedded newlines)
    followed by a single newline character.
    """
    line = entry.model_dump_json() + "\n"
    with open(path, "a") as f:
        f.write(line)
        f.flush()
