"""Estimation support — provides context for LLM-driven point estimation."""

import yaml

from .store import Store
from .models import FIBONACCI_POINTS


def estimate(store: Store, item_id: str) -> str:
    """Return item content + calibration guidelines + historical data."""
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
    }

    return yaml.dump(result, default_flow_style=False, sort_keys=False)
