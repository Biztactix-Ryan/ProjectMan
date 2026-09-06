"""Hub rollup — aggregate stats across all subprojects."""

from pathlib import Path
from typing import Optional

import yaml

from ..indexer import build_index
from ..models import ProjectConfig
from ..store import Store
from .stores import hub_stores, not_attached_row


def load_config_from(pm_dir: Path) -> ProjectConfig:
    """Load a ProjectConfig from an arbitrary .project-style directory."""
    with open(pm_dir / "config.yaml") as f:
        data = yaml.safe_load(f)
    return ProjectConfig(**data)


def rollup(root: Optional[Path] = None) -> dict:
    """Aggregate index stats across every subproject store in the map.

    Store locations come from :func:`projectman.hub.stores.hub_stores`, which
    puts each subproject's PM data inside its own checkout at
    ``projects/{name}/.project`` (US-PM-31).

    A subproject whose store is not mounted there is *reported*, not raised
    on: its row is ``{name, prefix, status: "not attached", hint}`` and no
    ``Store`` is constructed for it (US-PM-31-9).  A hub read has no business
    failing because one of ten submodules has not been migrated yet, so the
    other nine still contribute their numbers to the totals.
    """
    from ..config import find_project_root
    root = root or find_project_root()

    totals = {
        "projects": [],
        "hub_epics": 0,
        "total_epics": 0,
        "total_stories": 0,
        "total_tasks": 0,
        "total_points": 0,
        "completed_points": 0,
    }

    # Epics live in the hub's own store now (US-PM-36), and a hub epic belongs
    # to no single project — so it is counted once here, outside the project
    # rows, and never lands in a per-project "Epics" column.  Subproject epics
    # are still summed below, so a hub whose epics have not been migrated up
    # yet still adds up to the same total.
    try:
        totals["hub_epics"] = build_index(Store(root)).epic_count
        totals["total_epics"] += totals["hub_epics"]
    except Exception:
        # A hub read never fails on its own store being mid-write; the rows
        # below are the part callers came for.
        pass

    for entry in hub_stores(root):
        name = entry["name"]
        pm_dir = entry["path"]
        if not entry["attached"]:
            # Missing, unmounted, or unreadable — all one answer, and never a
            # Store() call.  See stores.not_attached_row.
            totals["projects"].append(not_attached_row(entry))
            continue

        try:
            store = Store(root, project_dir=pm_dir)
            sub_config = load_config_from(pm_dir)
            index = build_index(store)

            project_data = {
                "name": name,
                "status": "active",
                "repo": sub_config.repo,
                "epics": index.epic_count,
                "stories": index.story_count,
                "tasks": index.task_count,
                "total_points": index.total_points,
                "completed_points": index.completed_points,
            }

            totals["projects"].append(project_data)
            totals["total_epics"] += index.epic_count
            totals["total_stories"] += index.story_count
            totals["total_tasks"] += index.task_count
            totals["total_points"] += index.total_points
            totals["completed_points"] += index.completed_points
        except Exception as e:
            totals["projects"].append({
                "name": name,
                "status": f"error: {e}",
            })

    pct = 0
    if totals["total_points"] > 0:
        pct = round(totals["completed_points"] / totals["total_points"] * 100)
    totals["completion"] = f"{pct}%"

    return totals
