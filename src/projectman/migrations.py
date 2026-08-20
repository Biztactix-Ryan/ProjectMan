"""One-off data migrations for project state.

Nothing in this module runs implicitly.  Every entry point has to be called
deliberately (today: the ``projectman migrate-archived`` CLI command), and the
default is always a report, never a write.

Currently one migration lives here: repairing tasks that were archived while
``Store.archive`` implemented "archive a task" as "set the task to done"
(US-PM-16).  Those tasks sit on disk indistinguishable from delivered work and
inflate completion, burndown and velocity.

The contract below is ADR-002 (``.project/DECISIONS.md``), decided in
US-PM-17-6 and implemented in US-PM-17-7.  It describes what this module does
*today*, not what it is meant to grow into: the safety invariant is pinned by
``TestNoSignalNeverLeavesDone`` and this text's own factual references by
``TestTheDocstringMatchesTheCode``, both in
``tests/test_migrate_archived_as_done.py``.  Prose asserting a safety the code
did not honour is precisely the bug US-PM-17 exists to fix, so nothing written
here is allowed to run ahead of the implementation again.

Identification requires a positive archive signal
-------------------------------------------------
An archive is only ever recognised from evidence that an archive *happened* —
never inferred from the shape of a status change.  The signal is an activity
log event for the task that explicitly writes the ``archived`` field::

    {"event_type": "update", "item_id": "US-PM-9-3",
     "changes": {"archived": {"before": false, "after": true}}}

(A future dedicated ``"event_type": "archive"`` — the value already exists in
``EventType`` but nothing emits it — counts equally.)

A task is a migration candidate only when all of the following hold:

1. on disk it is ``status: done`` and *not* flagged ``archived``;
2. the log contains a positive archive signal for it whose ``after`` is true;
3. no later event cleared the flag (an unarchive after the archive means the
   current un-flagged state is correct and intentional);
4. no status change was recorded *after* the signal — work that continued
   past the archive means the task was resurrected, and re-flagging it would
   hide delivered work from the metrics.  Such a task is reported under
   ``skipped``.

That combination means one specific thing: the log says the task was archived
and the file has lost the flag — a dropped write, a restored or hand-edited
frontmatter, a bad merge.  The log is authoritative about an event it actually
recorded, so re-applying the flag is a repair, not a guess.

What applying does — and the invariant it preserves
---------------------------------------------------
Applying sets ``archived: true``.  It restores a ``status`` only when the same
signal event also recorded a ``status`` change, in which case the logged
``before`` value is authoritative.  Otherwise the status is left exactly as
found.

Under current archive semantics ``Store.archive`` never touches ``status``, so
in practice this migration only ever re-applies a flag.  The invariant that
matters:

    **The migration never moves a task out of ``done`` on inferred evidence.**
    A status is only ever written back when the log explicitly recorded that
    status changing during the archive itself.

Setting the flag alone is sufficient to fix the metrics, which is the whole
point of the migration: ``models.is_archived`` is what completion, burndown
and velocity consult, and it is satisfied by the flag regardless of status.

The rejected rule
-----------------
The original migration inferred an archive from a footprint: last status event
moved the task ``todo``/``blocked`` -> ``done`` and changed *only* ``status``.
The old ``archive`` was literally ``update(task_id, status="done")``, so that
is genuinely what it left behind — but it is *also* exactly what closing a
task in a single write leaves behind, and closing straight from ``todo`` is
routine (``pm_update(id, status="done")`` and ``pm_done_next`` on an ungrabbed
task both do it).  The two are byte-identical; no amount of narrowing
separates them.

Measured in this repository (US-PM-17-6): six tasks match the footprint, and
every one of the six carries the identical event — same ``changes`` payload,
same ``source``, same actor.  Four of them (``US-PRJ-29-2`` .. ``-5``) are
known-good closes from a ``/pm`` audit pass, and the old rule would have
reverted all four to ``todo``.

Secondary discriminators were tested against that data and rejected:

* **Run-log entry** — inverted and useless.  The four tasks that must *not* be
  migrated have run-log entries; the two older ones do not.  Absence proves
  nothing either way: when this was measured, 210 of this repo's 272 done tasks
  had no run log at all, because a status write without a ``note`` never
  creates one.
* **Assignee / points** — all six have ``assignee: null`` and ``points: null``.
  Zero separation.

Any rule built on those signals would still have to write on ambiguous
evidence, so all of them fail the invariant above.

Tasks matching the old footprint are reported under ``needs_review`` and never
written.  The report is the deliverable for that class; a human with outside
knowledge is the only thing that can resolve it, and the remedy is to archive
the task by hand (``pm_archive`` over MCP, or ``Store.archive`` directly — no
CLI subcommand exposes it today).  A task whose last status event moved it to
``done`` from ``in-progress``/``review`` is not even reported: that is what
ordinary completion looks like.

What this cannot tell you
-------------------------
* **Every pre-signal archive is unrecoverable by machine.**  Archives made
  before ``Store.archive`` recorded the ``archived`` flag left no trace that
  distinguishes them from completion — from *any* prior status, not just
  ``in-progress``.  This is the same stance the module always took for
  ``in-progress -> done``, now applied honestly to the rest.
  The manual remedy is ``pm_archive`` (or ``Store.archive``), which sets the
  flag and leaves ``status`` alone: an honest record, correct metrics, and no
  claim that the work was never done.
* **The log may not go back far enough.**  Tasks archived before activity
  logging existed, or in a truncated log, have no signal and are never
  candidates.
* **A signal event with an unusable payload** is reported under
  ``needs_review`` and left untouched — this migration never invents a status.

Every failure mode is biased the same way: skip rather than write.  A missed
archive stays a cosmetic metrics bug; a wrongly "restored" task destroys a real
record of completed work.  The difference from the previous version of this
docstring is that the rules above actually honour that bias — the earlier ones
asserted it while writing on evidence that could not support it.
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


#: Statuses a task can hold that mean no *recorded* work ran on it.  Reaching
#: ``done`` directly from one of these was once read as the fingerprint of the
#: old archive-as-done path; US-PM-17-6 established that it is equally the
#: fingerprint of closing a task in a single write, so under the target
#: contract this set only classifies tasks into ``needs_review`` and never
#: authorises a write.  See the module docstring.
NEVER_STARTED_STATUSES = frozenset({"todo", "blocked"})


@dataclass
class ArchivedAsDoneCandidate:
    """A task the log says was archived, whose file has lost the flag.

    ``prior_status`` is ``None`` unless the archive signal event itself
    recorded a status change; only then may a status be written back.  See the
    module docstring's invariant.
    """

    task_id: str
    prior_status: Optional[str] = None
    archived_at: Optional[str] = None
    title: str = ""

    def describe(self) -> str:
        when = f" at {self.archived_at}" if self.archived_at else ""
        move = (
            f"status done -> {self.prior_status}, "
            if self.prior_status is not None
            else "status left as done, "
        )
        return f"{self.task_id}: {move}archived: true (archived{when})"


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


def _changes(entry: dict[str, Any]) -> dict[str, Any]:
    """The ``changes`` mapping of an event, or an empty one."""
    changes = entry.get("changes") or {}
    return changes if isinstance(changes, dict) else {}


def _status_change(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The ``{before, after}`` status diff an event recorded, if it has one.

    Historical rows sometimes record a bare value rather than a diff; those
    carry no ``before`` and are not usable evidence, so they read as absent.
    """
    change = _changes(entry).get("status")
    return change if isinstance(change, dict) else None


def _status_events(
    entries: list[dict[str, Any]], task_id: str, *, updates_only: bool = True
) -> list[tuple[int, dict[str, Any]]]:
    """``(index, event)`` pairs for events that changed ``task_id``'s status."""
    events: list[tuple[int, dict[str, Any]]] = []
    for index, entry in enumerate(entries):
        if entry.get("item_id") != task_id:
            continue
        if updates_only and entry.get("event_type") != "update":
            continue
        if _status_change(entry) is None:
            continue
        events.append((index, entry))
    return events


def _archived_write(entry: dict[str, Any]) -> Optional[bool]:
    """The value an event explicitly wrote to ``archived``, or ``None``.

    A dedicated ``event_type: "archive"`` counts as writing true — the value
    exists in ``EventType`` and nothing emits it yet, but when something does
    it is the same signal.  Anything that does not explicitly record the flag
    returns ``None``: absence of a write, not a write of false.
    """
    change = _changes(entry).get("archived")
    if isinstance(change, dict):
        return bool(change["after"]) if "after" in change else None
    if isinstance(change, bool):
        return change
    if entry.get("event_type") == "archive":
        return True
    return None


def _archive_signal(
    entries: list[dict[str, Any]], task_id: str
) -> Optional[tuple[int, dict[str, Any]]]:
    """The positive archive signal in force for ``task_id``, if any.

    Last explicit write wins: an archive followed by an unarchive leaves no
    signal, because the current un-flagged state is then correct and
    intentional.  Returns ``(index, event)`` so callers can ask what happened
    after it.
    """
    signal: Optional[tuple[int, dict[str, Any]]] = None
    for index, entry in enumerate(entries):
        if entry.get("item_id") != task_id:
            continue
        wrote = _archived_write(entry)
        if wrote is None:
            continue
        signal = (index, entry) if wrote else None
    return signal


def _valid_task_status(value: Any) -> Optional[str]:
    """Normalise a logged status value to a real TaskStatus string, or None."""
    if value is None:
        return None
    text = str(getattr(value, "value", value))
    try:
        return TaskStatus(text).value
    except ValueError:
        return None


def _review_old_footprint(
    entries: list[dict[str, Any]], task_id: str
) -> Optional[SkippedTask]:
    """Classify a signal-less done task against the *rejected* footprint.

    Returns a :class:`SkippedTask` for ``needs_review`` when the task's history
    has the shape the old migration used to act on — last status event moved it
    ``todo``/``blocked`` -> ``done`` changing only ``status``.  That shape is
    equally the shape of closing a task in a single write, so it is reported
    for a human and never written.  ``None`` means "nothing worth reporting":
    ordinary completion, no history, or a log that disagrees with the file.
    """
    events = _status_events(entries, task_id)
    if not events:
        return None

    # Work continued after the task was first marked done: whatever the
    # earlier ``-> done`` was, the current one is a later, separate close.
    if any(str(_status_change(e).get("before")) == "done" for _, e in events):
        return None

    _, last = events[-1]
    change = _status_change(last)
    if str(change.get("after")) != "done":
        # The last status write is not what produced the current ``done``;
        # log and file disagree, and guessing is exactly what is banned.
        return None
    if set(_changes(last)) != {"status"}:
        # The old archive wrote status and nothing else.
        return None

    prior = _valid_task_status(change.get("before"))
    if prior is None:
        return SkippedTask(
            task_id,
            "archive-shaped event has no usable prior status; "
            "nothing written and no status invented",
        )
    if prior not in NEVER_STARTED_STATUSES:
        # in-progress/review -> done is what ordinary completion looks like.
        return None

    return SkippedTask(
        task_id,
        f"closed {prior} -> done in a single write: indistinguishable from a "
        f"pre-US-PM-16 archive, so nothing is written. If it really was "
        f"abandoned, archive it by hand — pm_archive over MCP, or "
        f"Store.archive({task_id!r}) directly; no CLI subcommand exposes it",
    )


def find_archived_as_done(store) -> MigrationReport:
    """Identify tasks the activity log says were archived but whose files
    have lost the ``archived`` flag.

    Read-only: nothing on disk is touched.  See the module docstring for the
    rules, the invariant they preserve, and what they cannot detect.
    """
    report = MigrationReport(applied=False)
    entries = read_activity_log(store.project_dir)

    for meta in store.list_tasks(status="done"):
        if getattr(meta, "archived", False):
            # Already migrated, or archived under the new semantics and
            # genuinely done.  Either way, honestly recorded — leave it.
            continue
        report.examined += 1

        signal = _archive_signal(entries, meta.id)
        if signal is None:
            # No positive evidence an archive ever happened.  The most this
            # can ever be is a report for a human.
            review = _review_old_footprint(entries, meta.id)
            if review is not None:
                report.needs_review.append(review)
            continue

        index, event = signal

        # Resurrection guard: a status change recorded after the archive means
        # the task was picked back up.  Re-flagging it would drop real work out
        # of the metrics, which is the same damage this migration exists to
        # undo, pointed the other way.
        later = _status_events(entries, meta.id, updates_only=False)
        if any(i > index for i, _ in later):
            report.skipped.append(
                SkippedTask(
                    meta.id, "status changed after the archive was recorded"
                )
            )
            continue

        prior: Optional[str] = None
        change = _changes(event).get("status")
        if change is not None:
            # The archive itself moved the status, so the logged ``before`` is
            # authoritative — but only if it is actually usable.
            prior = (
                _valid_task_status(change.get("before"))
                if isinstance(change, dict)
                else None
            )
            if prior is None:
                report.needs_review.append(
                    SkippedTask(
                        meta.id,
                        "archive event recorded a status change with no usable "
                        "prior status; left untouched rather than invented",
                    )
                )
                continue

        report.candidates.append(
            ArchivedAsDoneCandidate(
                task_id=meta.id,
                prior_status=prior,
                archived_at=event.get("timestamp"),
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

    Applying sets ``archived: true``, and restores a status only for the
    candidates whose archive signal recorded one (see the module docstring's
    invariant — a status is never inferred).  Nothing under ``needs_review`` or
    ``skipped`` is ever written.  The operation is idempotent by construction:
    a migrated task carries the ``archived`` flag, so it is filtered out before
    identification even begins on any subsequent run.
    """
    report = find_archived_as_done(store)
    if not apply:
        return report

    report.applied = True
    for candidate in report.candidates:
        fields: dict[str, Any] = {"archived": True}
        if candidate.prior_status is not None:
            fields["status"] = candidate.prior_status
        try:
            store.update(candidate.task_id, **fields)
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
        lines.append(
            f"  {len(report.needs_review)} need manual review (never written):"
        )
        for s in report.needs_review:
            lines.append(f"    {s.task_id}: {s.reason}")

    if report.errors:
        lines.append("  errors:")
        for e in report.errors:
            lines.append(f"    {e}")

    if not report.applied and report.candidates:
        lines.append("  re-run with --apply to write these changes")

    return "\n".join(lines)
