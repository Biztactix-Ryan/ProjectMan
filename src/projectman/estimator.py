"""Estimation support — provides context for LLM-driven point estimation."""

import yaml

from .durations import duration_history_block
from .store import Store
from .models import FIBONACCI_POINTS


def estimate(store: Store, item_id: str) -> str:
    """Return item content + calibration guidelines + historical data.

    The calibration bands say what a point *should* mean in minutes; the
    ``duration_history`` block beside them says what points have actually
    cost this project (per-band p50/p90/max/n) and the ``max_task_minutes``
    ceiling those numbers are read against, so a sizer can tell a 3 that runs
    an hour here from a 3 that runs three.  See
    :func:`projectman.durations.duration_history_block`.
    """
    meta, body = store.get(item_id)

    # Historical average from completed stories
    done_stories = store.list_stories(status="done")
    avg_points = 0.0
    if done_stories:
        pointed = [s.points for s in done_stories if s.points]
        if pointed:
            avg_points = sum(pointed) / len(pointed)

    calibration = {
        "fibonacci_scale": sorted(FIBONACCI_POINTS),
        "calibration": {
            1: "Trivial — ~15 min, single file change",
            2: "Small — ~30 min, a few related changes",
            3: "Medium — ~1 hour, moderate complexity",
            5: "Large — ~half day, multiple files/concerns",
            8: "Very large — ~full day, significant complexity",
            13: "Epic-sized — 2+ days, consider decomposing",
        },
        "historical_average": round(avg_points, 1) if avg_points else "no data",
    }

    result = {
        "item": meta.model_dump(mode="json"),
        "body": body,
        "current_points": meta.points,
        "estimation_guidance": calibration,
        "duration_history": duration_history_block(store),
    }

    return yaml.dump(result, default_flow_style=False, sort_keys=False, allow_unicode=True, width=10000)
