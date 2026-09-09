"""How long tasks actually take, per point value, from the activity log.

Points are an estimate of size; this module answers the different question
of *elapsed wall-clock time*, which is what decides whether a task will
outlive an orchestrator's one-hour prompt cache.  The signal is already in
``.project/activity.jsonl``: a task claimed under an orchestrator run logs a
status change to ``in-progress``, and the same run logs the change to
``done`` (or ``review``) when the worker hands it back.  The minutes between
those two lines are the grab-to-done duration, and grouping them by the
task's points gives a per-band history a planner can read.

Only transitions stamped with an ``orch-`` run id are counted.  A human
moving a task to in-progress on Friday and closing it on Monday is a real
event but not a measurement of how long the work took; an orchestrated run
is machine-paced start to finish, so its durations are comparable.

Everything here is tolerant in the way :mod:`projectman.activity_log` is:
the log is append-only history no reader may repair, so a malformed line, an
unparseable timestamp, a transition with no partner or a task whose file is
gone are all *skipped*.  This function never raises on log content.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from .activity_log import log_paths, read_log_entries
from .config import max_task_minutes
from .models import SprintFrontmatter
from .store import Store

#: The run-id prefix that marks an orchestrated (machine-paced) transition.
ORCH_RUN_PREFIX = "orch-"

#: Statuses that end a task's active stretch.  ``review`` counts because a
#: worker that hands back for review has finished working; the wait for a
#: verdict afterwards is the orchestrator's time, not the task's.
_END_STATUSES = ("done", "review")

#: Below this many measured tasks the per-points bands are noise: one slow
#: task would set the p90 for its whole band.  Planners are told so rather
#: than left to read a p90 computed from a single sample as a threshold.
MIN_HISTORY_SAMPLES = 3

#: Attached as ``note`` when the project has fewer than
#: :data:`MIN_HISTORY_SAMPLES` measured tasks.
THIN_HISTORY_NOTE = (
    "Fewer than three orchestrated tasks in this project have a measured "
    "grab-to-done duration — this history is too thin to flag long tasks. "
    "Size by the calibration bands until more runs have landed."
)


def _parse_timestamp(raw: Any) -> Optional[datetime]:
    """Parse a log timestamp to an aware UTC datetime, or None.

    ``Z`` is spelled out as ``+00:00`` because ``fromisoformat`` does not
    accept the military suffix before Python 3.11, and the writer has always
    used it.  A naive timestamp (written before the writer became
    timezone-aware) is read as UTC, matching :mod:`projectman.audit`.
    """
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list.

    Nearest rank (rather than interpolation) because these samples are few
    and the answer should be a duration that actually happened: a p90 of 44
    is a task someone waited 44 minutes for, not an average of two others.
    """
    rank = math.ceil(q * len(sorted_values))
    index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return sorted_values[index]


def _points_by_task(store: Store) -> dict[str, int]:
    """Task id to points, archived tasks included.

    Archived tasks are the bulk of the history — work that finished and was
    tidied away is exactly the work whose durations are known — so excluding
    them would throw away most of the sample.  Tasks with no estimate are
    left out: there is no band to file their duration under.
    """
    points: dict[str, int] = {}
    for meta in store.list_tasks(archived=None):
        if isinstance(meta.points, int) and meta.points > 0:
            points[meta.id] = meta.points
    return points


def task_durations(store: Store) -> list[tuple[str, float]]:
    """Every measurable grab-to-done stretch, as ``(task_id, minutes)``.

    One pass over the log, oldest line first.  A transition into
    ``in-progress`` opens a stretch for that task and a later transition to
    ``done`` or ``review`` closes it; a second claim of the same task (a
    release and re-grab) restarts the clock, so what is measured is the
    attempt that actually finished rather than the wall-clock span from the
    first attempt.  A close with nothing open is ignored, and a stretch
    still open when the log ends never becomes a sample.
    """
    open_since: dict[str, datetime] = {}
    durations: list[tuple[str, float]] = []
    for entry in read_log_entries(log_paths(store.project_dir)):
        if entry.get("event_type") != "update" or entry.get("item_type") != "task":
            continue
        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or not run_id.startswith(ORCH_RUN_PREFIX):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, dict):
            continue
        status = changes.get("status")
        if not isinstance(status, dict):
            continue
        after = status.get("after")
        if after not in ("in-progress",) + _END_STATUSES:
            continue
        item_id = entry.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            continue
        moment = _parse_timestamp(entry.get("timestamp"))
        if moment is None:
            continue
        if after == "in-progress":
            open_since[item_id] = moment
            continue
        started = open_since.pop(item_id, None)
        if started is None:
            continue
        minutes = (moment - started).total_seconds() / 60.0
        if minutes < 0:
            # Clock skew or a hand-edited line: a negative duration is not a
            # measurement, so drop it rather than let it drag a median down.
            continue
        durations.append((item_id, minutes))
    return durations


def duration_history(store: Store) -> dict[str, Any]:
    """Per-points grab-to-done duration history for this project.

    Returns ``{"by_points": {points: {"p50", "p90", "max", "n"}}, "n": total}``
    with ``by_points`` ordered by points ascending.  Minutes are rounded to
    one decimal.  ``n`` at the top level counts every paired stretch that
    landed in a band, so a caller can tell "no history" (0) from "thin
    history" (a handful) without summing the bands.

    An empty or missing log, a project whose tasks carry no points, or a log
    of nothing but unpaired transitions all yield ``{"by_points": {}, "n": 0}``.
    """
    points_by_task = _points_by_task(store)
    samples: dict[int, list[float]] = {}
    for task_id, minutes in task_durations(store):
        points = points_by_task.get(task_id)
        if points is None:
            continue
        samples.setdefault(points, []).append(minutes)

    by_points: dict[int, dict[str, Any]] = {}
    total = 0
    for points in sorted(samples):
        values = sorted(samples[points])
        total += len(values)
        by_points[points] = {
            "p50": round(_percentile(values, 0.5), 1),
            "p90": round(_percentile(values, 0.9), 1),
            "max": round(values[-1], 1),
            "n": len(values),
        }
    return {"by_points": by_points, "n": total}


def duration_history_block(store: Store) -> dict[str, Any]:
    """The duration history as a planning tool reports it.

    :func:`duration_history` answers what the log says; this answers what a
    planner needs beside it — the project's own ``max_task_minutes`` ceiling,
    so a reader comparing a band's p90 against it does not have to fetch the
    config separately, and a ``note`` when the sample is too small for that
    comparison to mean anything.

    Returns ``{"by_points", "n", "max_task_minutes"}`` plus ``"note"`` only
    when ``n`` is under :data:`MIN_HISTORY_SAMPLES`.  The key order is stable
    so the YAML the tools emit reads the same way every time.
    """
    block: dict[str, Any] = dict(duration_history(store))
    block["max_task_minutes"] = max_task_minutes(store.config)
    if block["n"] < MIN_HISTORY_SAMPLES:
        block["note"] = THIN_HISTORY_NOTE
    return block


def long_task_risk(store: Store, sprint: SprintFrontmatter) -> list[dict[str, Any]]:
    """The sprint's open tasks whose points band usually runs past the limit.

    A task is flagged when its points band has a p90 above the project's
    ``orchestrate.max_task_minutes`` — that is, when one task in ten of that
    size has historically outlived the orchestrator's prompt cache.  p90
    rather than the median because the median says what a typical task costs
    and the tail is what actually breaks a run.

    Only *open* tasks of the sprint's planned stories are considered: a task
    already done cannot be re-scoped, and an archived one is not owed.  Bands
    with fewer than :data:`MIN_HISTORY_SAMPLES` measurements are skipped
    entirely — a p90 drawn from one or two samples is the slowest of them,
    not a percentile, and flagging on it would cry wolf on a project with
    almost no history.  Tasks with no estimate have no band and are not
    flagged.

    Returns one ``{"id", "points", "p50", "p90", "max_task_minutes"}`` entry
    per flagged task, in sprint order (planned stories, then task id), and an
    empty list when nothing is flagged — the caller can always show the key.
    The threshold rides on each entry so a caller reporting a single flagged
    task does not have to fetch the config to say what it exceeded.
    """
    limit = max_task_minutes(store.config)
    risky_bands = {
        points: band
        for points, band in duration_history(store)["by_points"].items()
        if band["n"] >= MIN_HISTORY_SAMPLES and band["p90"] > limit
    }
    if not risky_bands:
        return []

    flagged: list[dict[str, Any]] = []
    for story_id in sprint.planned_stories:
        for task in store.list_tasks(story_id=story_id, archived=False):
            if task.status.value == "done":
                continue
            band = risky_bands.get(task.points)
            if band is None:
                continue
            flagged.append(
                {
                    "id": task.id,
                    "points": task.points,
                    "p50": band["p50"],
                    "p90": band["p90"],
                    "max_task_minutes": limit,
                }
            )
    return flagged
