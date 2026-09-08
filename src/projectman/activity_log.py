"""The activity log (JSONL): one writer, one reader.

Every ``LogEntry`` the project records is appended here by
:func:`append_log_entry`, and every reader of that file goes through
:func:`iter_log_entries` / :func:`read_log_entries`.  Reading used to be
hand-rolled once per caller (``pm_activity`` in ``server.py`` and
``migrations.read_activity_log``), which meant "tolerate a missing file,
skip a corrupt line" was re-decided in each of them.  It is decided here.

The log is also bounded here (US-PRJ-52-10).  A project that configures
``activity_log_max_bytes`` or ``activity_log_max_days`` gets the live
``activity.jsonl`` renamed to a dated sibling — ``activity-YYYYMMDD-HHMMSS
.jsonl`` — on the append that finds it over the bound, and readers walk
those siblings oldest-first before the live file, so nothing a caller could
see before rotation disappears afterwards.  With neither key set nothing
rotates, which is what every existing project gets.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

from projectman.models import LogEntry

#: One log file, or several read back to back.  Rotation hands the reader
#: the rotated siblings followed by the live file; a caller with a single
#: file still passes a single path.
LogPaths = Union[str, Path, Iterable[Union[str, Path]]]

#: The live log's filename inside ``.project/``.
LIVE_LOG_NAME = "activity.jsonl"

#: Rotated siblings, named for the moment they were rotated out.  The
#: fixed-width timestamp is what makes a plain name sort a chronological
#: one, so the pattern is matched strictly: an ``activity-old.jsonl`` a
#: human dropped in the directory is not mistaken for rotation output.
ROTATED_LOG_GLOB = "activity-*.jsonl"
_ROTATED_LOG_RE = re.compile(r"^activity-\d{8}-\d{6}\.jsonl$")

#: How many leading lines to read looking for the log's oldest timestamp
#: before giving up and using the file's mtime.  A handful of corrupt
#: leading lines should not make the age bound scan a 300 KB file.
_AGE_PROBE_LINES = 100


def _rotated_name(moment: datetime) -> str:
    """The sibling filename for a log rotated out at ``moment``."""
    return f"activity-{moment.strftime('%Y%m%d-%H%M%S')}.jsonl"


def rotated_log_paths(project_dir: Path) -> list[Path]:
    """The rotated siblings in ``project_dir``, oldest first.

    Sorted by name, which is chronological because the timestamp in the
    name is fixed-width and zero-padded.  Anything that does not match the
    rotation pattern exactly is ignored.
    """
    directory = Path(project_dir)
    try:
        candidates = list(directory.glob(ROTATED_LOG_GLOB))
    except OSError:
        return []
    return sorted(
        (p for p in candidates if _ROTATED_LOG_RE.match(p.name)),
        key=lambda p: p.name,
    )


def log_paths(project_dir: Path) -> list[Path]:
    """Every activity-log file in ``project_dir``, oldest first.

    Rotated siblings in chronological order, then the live
    ``activity.jsonl``.  Only files that exist are returned, so an empty
    list means "this project has no activity log at all" — the distinction
    ``pm_activity`` reports as *No activity log found*.  Feed the result
    straight to :func:`read_log_entries`, which reads paths in order.
    """
    directory = Path(project_dir)
    paths = rotated_log_paths(directory)
    live = directory / LIVE_LOG_NAME
    if live.exists():
        paths.append(live)
    return paths


def _first_entry_timestamp(path: Path) -> Optional[datetime]:
    """The timestamp of the oldest entry in ``path``, or None.

    None when the file is missing, empty, or has no parseable timestamp in
    its first :data:`_AGE_PROBE_LINES` lines.  Naive timestamps (written
    before the writer became timezone-aware) are read as UTC.
    """
    try:
        with path.open() as f:
            for index, line in enumerate(f):
                if index >= _AGE_PROBE_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                raw = entry.get("timestamp")
                if not isinstance(raw, str):
                    continue
                try:
                    parsed = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
    except OSError:
        return None
    return None


def _log_start(path: Path) -> Optional[datetime]:
    """When the live log started collecting, for the age bound.

    The oldest entry's own timestamp, because that — not the file's mtime —
    is the span the bound is about: mtime is the *last* append, so a busy
    log would look permanently young by it.  When no entry yields a
    timestamp the file's mtime stands in, which is the best available
    answer for a log of nothing but corrupt lines.
    """
    started = _first_entry_timestamp(path)
    if started is not None:
        return started
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _bound(value: Any) -> Optional[float]:
    """Normalise a configured bound to a positive float, or None.

    None, junk, zero and negatives all mean "no bound": a bound of zero
    would rotate on every single append, which is never what someone
    typing a number into config.yaml meant.
    """
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def should_rotate(
    path: Path,
    *,
    max_bytes: Any = None,
    max_days: Any = None,
    now: Optional[datetime] = None,
) -> bool:
    """Whether the live log at ``path`` is past a configured bound.

    False when neither bound is configured (the default), when the file
    does not exist, and when it is empty — rotating an empty file would
    only litter the directory with empty siblings.
    """
    size_bound = _bound(max_bytes)
    age_bound = _bound(max_days)
    if size_bound is None and age_bound is None:
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size == 0:
        return False
    if size_bound is not None and size >= size_bound:
        return True
    if age_bound is not None:
        started = _log_start(path)
        if started is not None:
            moment = now or datetime.now(timezone.utc)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            if moment - started >= timedelta(days=age_bound):
                return True
    return False


def rotate_log(path: Path, now: Optional[datetime] = None) -> Optional[Path]:
    """Rename the live log to its dated sibling; return the new path.

    A rename, not a copy-and-truncate: on one filesystem it is atomic, so
    there is no instant at which an entry lives in neither file.  The
    caller then appends to a fresh ``activity.jsonl``.

    Returns None if the rename failed for any reason — the caller must
    still write its entry to the live file rather than lose it.  A name
    already taken (two rotations inside one second) pushes the stamp
    forward a second at a time, which keeps names sorting chronologically;
    ``activity-…-2.jsonl`` would not.
    """
    path = Path(path)
    moment = now or datetime.now(timezone.utc)
    for _ in range(60):
        target = path.parent / _rotated_name(moment)
        if not target.exists():
            try:
                path.rename(target)
            except OSError:
                return None
            return target
        moment = moment + timedelta(seconds=1)
    return None


def append_log_entry(
    path: Path,
    entry: LogEntry,
    *,
    max_bytes: Any = None,
    max_days: Any = None,
) -> None:
    """Atomically append a single LogEntry as a JSONL line.

    Opens in append mode so existing content is never overwritten.
    Each entry is serialized as compact JSON (no embedded newlines)
    followed by a single newline character.

    When ``max_bytes`` or ``max_days`` is set and the file on disk is
    already past that bound, the file is rotated to a dated sibling
    *before* the write, so the entry lands at the head of a fresh log.  The
    order matters: the bound is checked against what is already there, the
    rename happens, and only then is the line written — so no append can
    ever be the one that disappears.  If the rename fails the entry is
    written to the live file anyway; an oversized log is a smaller problem
    than a lost event.
    """
    path = Path(path)
    if should_rotate(path, max_bytes=max_bytes, max_days=max_days):
        rotate_log(path)
    line = entry.model_dump_json() + "\n"
    with open(path, "a") as f:
        f.write(line)
        f.flush()


def _as_paths(source: LogPaths) -> list[Path]:
    """Normalise a single path or an iterable of paths to a list of Paths."""
    if isinstance(source, (str, Path)):
        return [Path(source)]
    return [Path(p) for p in source]


def iter_log_entries(source: LogPaths) -> Iterator[dict[str, Any]]:
    """Yield the events in one or more log files, oldest line first.

    Tolerant by design, because the log is append-only history that no
    reader is in a position to repair: a file that does not exist (or
    cannot be read) yields nothing, and a blank or unparseable line is
    skipped rather than fatal.  A migration or a status query that refuses
    to answer because one historical line is malformed is less useful than
    one that reports on everything it could parse.

    Events are yielded as the raw JSON objects on disk, not as validated
    :class:`~projectman.models.LogEntry` models: lines written by older
    versions may carry fields the model has since dropped or lack ones it
    has since gained, and callers filter on keys by name.  Validating here
    would silently hide rows that ``pm_activity`` shows today.  Anything
    that parses to something other than a JSON object is skipped.

    When several paths are given they are read in the order given, so the
    caller controls chronology (rotated files first, live file last).
    """
    for path in _as_paths(source):
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        yield entry
        except OSError:
            # Missing file, unreadable file, a directory where a file was
            # expected: all mean "no entries from here", never a crash.
            continue


def read_log_entries(
    source: LogPaths,
    *,
    newest_first: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read the events in one or more log files into a list.

    Oldest first by default, matching the order they were appended in.
    Pass ``newest_first=True`` to reverse that, and ``limit`` to keep only
    the first ``limit`` events of the resulting order — so
    ``newest_first=True, limit=20`` is "the twenty most recent events".
    """
    entries = list(iter_log_entries(source))
    if newest_first:
        entries.reverse()
    if limit is not None:
        entries = entries[: max(limit, 0)]
    return entries
