"""Build and write the project index from stories and tasks."""

from collections import Counter
from pathlib import Path

import yaml

from .models import IndexEntry, ProjectIndex
from .store import Store

_STATUS_EMOJI = {
    "backlog": "\U0001F4CB",   # clipboard
    "draft": "\U0001F4DD",     # memo
    "ready": "\U0001F7E2",     # green circle
    "active": "\U0001F3C3",    # runner
    "in-progress": "\U0001F3C3",
    "todo": "\u26AA",          # white circle
    "review": "\U0001F50D",    # magnifying glass
    "done": "\u2705",          # check mark
    "blocked": "\U0001F6D1",   # stop sign
    "archived": "\U0001F4E6",  # package
}


def _status_label(status: str) -> str:
    emoji = _STATUS_EMOJI.get(status, "")
    return f"{emoji} {status}" if emoji else status


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


def write_markdown_indexes(store: Store) -> None:
    """Generate the 4 markdown index files in .project/."""
    epics = store.list_epics()
    stories = store.list_stories()
    tasks = store.list_tasks()

    # Pre-compute counts
    stories_per_epic: Counter[str] = Counter()
    for s in stories:
        if s.epic_id:
            stories_per_epic[s.epic_id] += 1

    tasks_per_story: Counter[str] = Counter()
    for t in tasks:
        tasks_per_story[t.story_id] += 1

    ac_per_story: dict[str, int] = {
        s.id: len(s.acceptance_criteria) for s in stories
    }

    points_per_epic: Counter[str] = Counter()
    for s in stories:
        if s.epic_id and s.points:
            points_per_epic[s.epic_id] += s.points

    project_name = store.config.name
    is_hub = store.config.hub

    # --- INDEX.md (or README.md at repo root for hubs) ---
    # For hubs the index lives at the repo root as README.md, so links
    # must be prefixed with .project/ to reach the sub-indexes.
    prefix = ".project/" if is_hub else ""
    lines = [
        f"# {project_name}",
        "",
        f"| Metric | Count |",
        f"| ------ | ----- |",
        f"| Epics | {len(epics)} |",
        f"| Stories | {len(stories)} |",
        f"| Tasks | {len(tasks)} |",
        "",
        "## Indexes",
        "",
        f"- [Epics]({prefix}INDEX-EPICS.md)",
        f"- [Stories]({prefix}INDEX-STORIES.md)",
        f"- [Tasks]({prefix}INDEX-TASKS.md)",
        "",
    ]
    index_content = "\n".join(lines)
    if is_hub:
        (store.root / "README.md").write_text(index_content)
    (store.project_dir / "INDEX.md").write_text(index_content)

    # --- INDEX-EPICS.md ---
    lines = ["# Epics", ""]
    if epics:
        lines.append("| ID | Title | Status | Priority | Stories | Points |")
        lines.append("| -- | ----- | ------ | -------- | ------- | ------ |")
        for e in sorted(epics, key=lambda x: x.id):
            link = f"[{e.id}](epics/{e.id}.md)"
            sc = stories_per_epic.get(e.id, 0)
            pts = points_per_epic.get(e.id, 0) or "—"
            lines.append(
                f"| {link} | {e.title} | {_status_label(e.status.value)} "
                f"| {e.priority.value} | {sc} | {pts} |"
            )
    else:
        lines.append("_No epics yet._")
    lines.append("")
    (store.project_dir / "INDEX-EPICS.md").write_text("\n".join(lines))

    # --- INDEX-STORIES.md ---
    lines = ["# Stories", ""]
    if stories:
        lines.append(
            "| ID | Title | Status | Priority | Points | Epic | ACs | Tasks |"
        )
        lines.append(
            "| -- | ----- | ------ | -------- | ------ | ---- | --- | ----- |"
        )
        for s in sorted(stories, key=lambda x: x.id):
            link = f"[{s.id}](stories/{s.id}.md)"
            pts = s.points if s.points is not None else "—"
            epic_link = (
                f"[{s.epic_id}](epics/{s.epic_id}.md)" if s.epic_id else "—"
            )
            acs = ac_per_story.get(s.id, 0)
            tc = tasks_per_story.get(s.id, 0)
            lines.append(
                f"| {link} | {s.title} | {_status_label(s.status.value)} "
                f"| {s.priority.value} | {pts} | {epic_link} | {acs} | {tc} |"
            )
    else:
        lines.append("_No stories yet._")
    lines.append("")
    (store.project_dir / "INDEX-STORIES.md").write_text("\n".join(lines))

    # --- INDEX-TASKS.md ---
    lines = ["# Tasks", ""]
    if tasks:
        lines.append("| ID | Title | Status | Points | Assignee | Story |")
        lines.append("| -- | ----- | ------ | ------ | -------- | ----- |")
        for t in sorted(tasks, key=lambda x: x.id):
            link = f"[{t.id}](tasks/{t.id}.md)"
            pts = t.points if t.points is not None else "—"
            assignee = t.assignee or "—"
            story_link = f"[{t.story_id}](stories/{t.story_id}.md)"
            lines.append(
                f"| {link} | {t.title} | {_status_label(t.status.value)} "
                f"| {pts} | {assignee} | {story_link} |"
            )
    else:
        lines.append("_No tasks yet._")
    lines.append("")
    (store.project_dir / "INDEX-TASKS.md").write_text("\n".join(lines))


def write_index(store: Store) -> None:
    """Build index and write index.yaml and markdown indexes to disk."""
    index = build_index(store)
    index_path = store.project_dir / "index.yaml"
    data = index.model_dump(mode="json")
    with open(index_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    write_markdown_indexes(store)
