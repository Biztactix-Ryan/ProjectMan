"""One-off data migrations for project state.

Nothing in this module runs implicitly.  Every entry point has to be called
deliberately (today: the ``projectman migrate-archived`` CLI command), and the
default is always a report, never a write.

Currently one migration lives here: repairing tasks that were archived while
``Store.archive`` implemented "archive a task" as "set the task to done"
(US-PM-16).  Those tasks sit on disk indistinguishable from delivered work and
inflate completion, burndown and velocity.

How identification works
------------------------
The old ``archive`` was literally ``update(task_id, status="done")``, so the
activity log records it as an ordinary ``update`` event.  There is *no*
distinct archive event type — that is the central constraint here.  What the
log does preserve is the status the task held immediately before, and that is
enough to recognise the footprint:

    {"event_type": "update", "changes": {"status": {"before": "todo",
                                                    "after": "done"}}}

A task is treated as archived-as-done only when all of the following hold:

1. on disk it is ``status: done`` and not already flagged ``archived``;
2. its last status-changing event moved it *to* ``done``;
3. that event changed **only** ``status`` — the old archive passed no other
   field, whereas real edits usually carry an assignee, points or a body too;
4. the status it moved *from* is one work never actually ran in
   (``todo`` or ``blocked``) — see the limits below;
5. nothing in its history ever moved it *out of* ``done`` (no re-open), and
   nothing ever set the ``archived`` flag.

What this cannot tell you
-------------------------
* **Archive from ``in-progress`` or ``review`` is unrecoverable.**  Under the
  old behaviour that produced ``in-progress -> done`` with only ``status``
  changed, which is byte-for-byte what genuinely finishing a task produces.
  Rule 4 deliberately declines to guess, because the alternative is demoting
  real completed work.  Such tasks are invisible to this migration and have to
  be fixed by hand.
* **A re-open hides an earlier archive.**  If a task was archived-as-done, then
  re-opened and legitimately completed, rule 5 skips it.  That is the correct
  trade: the task demonstrably had work done on it after being marked done, so
  the final ``done`` is far more likely to be real.
* **The log may not go back far enough.**  Tasks completed or archived before
  activity logging existed, or in a truncated log, have no status event at all
  and are simply never candidates.
* **The prior status is only as good as the log.**  If the archive-shaped event
  is missing its ``before`` value, the task is reported under ``needs_review``
  and left untouched — this migration never invents a status.

Every one of those failure modes is biased the same way: skip rather than
write.  A missed archive stays a cosmetic metrics bug; a wrongly "restored"
task destroys a real record of completed work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .models import TaskStatus

__all__ = [
    "ArchivedAsDoneCandidate",
    "SkippedTask",
    "MigrationReport",
    "read_activity_log",
    "find_archived_as_done",
    "migrate_archived_as_done",
    "format_report",
]


#: Statuses a task can hold that mean work never actually ran on it.  Reaching
#: ``done`` directly from one of these is the fingerprint of the old
#: archive-as-done path rather than of somebody finishing the work.
NEVER_STARTED_STATUSES = frozenset({"todo", "blocked"})


@dataclass
class ArchivedAsDoneCandidate:
    """A task the log says was archived under the old archive-as-done path."""

    task_id: str
    prior_status: str
    archived_at: Optional[str] = None
    title: str = ""

    def describe(self) -> str:
        when = f" at {self.archived_at}" if self.archived_at else ""
        return (
            f"{self.task_id}: status done -> {self.prior_status}, "
            f"archived: true (archived{when})"
        )


@dataclass
class SkippedTask:
    """A task that looked archive-shaped but was deliberately left alone."""

    task_id: str
    reason: str


@dataclass
class MigrationReport:
    """Result of a dry run or an applied run."""

    applied: bool = False
    examined: int = 0
    candidates: list[ArchivedAsDoneCandidate] = field(default_factory=list)
    migrated: list[str] = field(default_factory=list)
    skipped: list[SkippedTask] = field(default_factory=list)
    needs_review: list[SkippedTask] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.migrated)


def read_activity_log(project_dir: Path) -> list[dict[str, Any]]:
    """Read ``activity.jsonl``, tolerating a missing file and bad lines.

    A corrupt line is skipped rather than fatal: a migration that refuses to
    run because one historical line is malformed is less useful than one that
    reports on everything it could parse.
    """
    log_path = Path(project_dir) / "activity.jsonl"
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _status_events(entries: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    """Events for ``task_id`` that changed its status, in log order."""
    events = []
    for entry in entries:
        if entry.get("item_id") != task_id:
            continue
        if entry.get("event_type") != "update":
            continue
        changes = entry.get("changes") or {}
        if not isinstance(changes, dict) or "status" not in changes:
            continue
        if not isinstance(changes["status"], dict):
            continue
        events.append(entry)
    return events


def _touched_archived_flag(entries: list[dict[str, Any]], task_id: str) -> bool:
    """True if the ``archived`` flag was ever explicitly written for this task.

    Any such event means the task went through the post-US-PM-16 archive path,
    where archival is already recorded honestly.  There is nothing to migrate,
    and re-deriving state from ``status`` would fight the explicit flag.
    """
    for entry in entries:
        if entry.get("item_id") != task_id:
            continue
        changes = entry.get("changes") or {}
        if isinstance(changes, dict) and "archived" in changes:
            return True
    return False


def _valid_task_status(value: Any) -> Optional[str]:
    """Normalise a logged status value to a real TaskStatus string, or None."""
    if value is None:
        return None
    text = str(getattr(value, "value", value))
    try:
        return TaskStatus(text).value
    except ValueError:
        return None


def find_archived_as_done(store) -> MigrationReport:
    """Identify tasks archived under the old archive-as-done behaviour.

    Read-only: nothing on disk is touched.  See the module docstring for the
    rules and, more importantly, for what they cannot detect.
    """
    report = MigrationReport(applied=False)
    entries = read_activity_log(store.project_dir)

    for meta in store.list_tasks(status="done"):
        if getattr(meta, "archived", False):
            # Already migrated, or archived under the new semantics and
            # genuinely done.  Either way, honestly recorded — leave it.
            continue
        report.examined += 1

        events = _status_events(entries, meta.id)
        if not events:
            # No recorded status history: cannot claim this was an archive.
            continue

        if _touched_archived_flag(entries, meta.id):
            continue

        # Re-open guard: work continued after the task was first marked done,
        # so the current ``done`` is much more likely to be real completion.
        if any(
            str(e["changes"]["status"].get("before")) == "done" for e in events
        ):
            report.skipped.append(
                SkippedTask(meta.id, "re-opened after being marked done")
            )
            continue

        last = events[-1]
        change = last["changes"]["status"]
        if str(change.get("after")) != "done":
            # Last status write was not the one that produced the current
            # ``done`` — the log and the file disagree; do not guess.
            continue
        if set(last.get("changes", {}).keys()) != {"status"}:
            # The old archive wrote status and nothing else.
            continue

        prior = _valid_task_status(change.get("before"))
        if prior is None:
            report.needs_review.append(
                SkippedTask(
                    meta.id,
                    "archive-shaped event has no usable prior status; "
                    "status left as-is rather than invented",
                )
            )
            continue
        if prior not in NEVER_STARTED_STATUSES:
            # in-progress/review -> done is indistinguishable from genuine
            # completion.  Declining to guess protects real delivered work.
            continue

        report.candidates.append(
            ArchivedAsDoneCandidate(
                task_id=meta.id,
                prior_status=prior,
                archived_at=last.get("timestamp"),
                title=meta.title,
            )
        )

    report.candidates.sort(key=lambda c: c.task_id)
    report.skipped.sort(key=lambda s: s.task_id)
    report.needs_review.sort(key=lambda s: s.task_id)
    return report


def migrate_archived_as_done(store, apply: bool = False) -> MigrationReport:
    """Report on — and, only when ``apply`` is true, correct — archived tasks.

    ``apply=False`` (the default) is a pure dry run: it writes nothing, not
    even an activity log entry.

    Applying sets ``archived: true`` and restores the status the task held
    before it was archived.  That makes the operation idempotent by
    construction: a migrated task is no longer ``status: done`` *and* carries
    the ``archived`` flag, so it fails the candidate test twice over on any
    subsequent run.
    """
    report = find_archived_as_done(store)
    if not apply:
        return report

    report.applied = True
    for candidate in report.candidates:
        try:
            store.update(
                candidate.task_id,
                archived=True,
                status=candidate.prior_status,
            )
            report.migrated.append(candidate.task_id)
        except Exception as exc:  # pragma: no cover - defensive
            report.errors.append(f"{candidate.task_id}: {exc}")

    if report.migrated:
        try:
            from .indexer import write_index

            write_index(store)
        except Exception as exc:  # pragma: no cover - defensive
            report.errors.append(f"index rebuild failed: {exc}")

    return report


def format_report(report: MigrationReport) -> str:
    """Render a report for the terminal."""
    lines: list[str] = []
    mode = "APPLIED" if report.applied else "DRY RUN — nothing written"
    lines.append(f"migrate-archived ({mode})")
    lines.append(f"  done tasks examined: {report.examined}")

    if report.candidates:
        verb = "migrated" if report.applied else "would change"
        lines.append(f"  {len(report.candidates)} task(s) {verb}:")
        for c in report.candidates:
            lines.append(f"    {c.describe()}")
    else:
        lines.append("  no archived-as-done tasks found")

    if report.skipped:
        lines.append(f"  {len(report.skipped)} skipped (not migrated):")
        for s in report.skipped:
            lines.append(f"    {s.task_id}: {s.reason}")

    if report.needs_review:
        lines.append(f"  {len(report.needs_review)} need manual review:")
        for s in report.needs_review:
            lines.append(f"    {s.task_id}: {s.reason}")

    if report.errors:
        lines.append("  errors:")
        for e in report.errors:
            lines.append(f"    {e}")

    if not report.applied and report.candidates:
        lines.append("  re-run with --apply to write these changes")

    return "\n".join(lines)
