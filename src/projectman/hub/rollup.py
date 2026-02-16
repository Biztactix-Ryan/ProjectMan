"""Hub rollup — aggregate stats across all subprojects."""

from pathlib import Path
from typing import Optional

import yaml

from ..config import load_config
from ..indexer import build_index
from ..models import ProjectConfig
from ..store import Store


def load_config_from(pm_dir: Path) -> ProjectConfig:
    """Load a ProjectConfig from an arbitrary .project-style directory."""
    with open(pm_dir / "config.yaml") as f:
        data = yaml.safe_load(f)
    return ProjectConfig(**data)


def rollup(root: Optional[Path] = None) -> dict:
    """Iterate hub PM data dirs (.project/projects/{name}/), aggregate index stats."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    totals = {
        "projects": [],
        "total_epics": 0,
        "total_stories": 0,
        "total_tasks": 0,
        "total_points": 0,
        "completed_points": 0,
    }

    for name in config.projects:
        pm_dir = root / ".project" / "projects" / name
        if not (pm_dir / "config.yaml").exists():
            totals["projects"].append({
                "name": name,
                "status": "not initialized",
            })
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
