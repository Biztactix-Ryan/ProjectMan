"""Build and write the project index from stories and tasks."""

from pathlib import Path

import yaml

from .models import IndexEntry, ProjectIndex
from .store import Store


def build_index(store: Store) -> ProjectIndex:
    """Read all epics, stories, and tasks, produce a ProjectIndex."""
    entries: list[IndexEntry] = []
    total_points = 0
    completed_points = 0

    for epic in store.list_epics():
        entries.append(
            IndexEntry(
                id=epic.id,
                title=epic.title,
                type="epic",
                status=epic.status.value,
            )
        )

    for story in store.list_stories():
        entries.append(
            IndexEntry(
                id=story.id,
                title=story.title,
                type="story",
                status=story.status.value,
                points=story.points,
                epic_id=story.epic_id,
            )
        )
        if story.points:
            total_points += story.points
            if story.status.value == "done":
                completed_points += story.points

    for task in store.list_tasks():
        entries.append(
            IndexEntry(
                id=task.id,
                title=task.title,
                type="task",
                status=task.status.value,
                points=task.points,
                story_id=task.story_id,
            )
        )
        if task.points:
            total_points += task.points
            if task.status.value == "done":
                completed_points += task.points

    epic_count = sum(1 for e in entries if e.type == "epic")
    story_count = sum(1 for e in entries if e.type == "story")
    task_count = sum(1 for e in entries if e.type == "task")

    return ProjectIndex(
        entries=entries,
        total_points=total_points,
        completed_points=completed_points,
        story_count=story_count,
        task_count=task_count,
        epic_count=epic_count,
    )


def write_index(store: Store) -> None:
    """Build index and write index.yaml to disk."""
    index = build_index(store)
    index_path = store.project_dir / "index.yaml"
    data = index.model_dump(mode="json")
    with open(index_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
