"""Build and write the project index from stories and tasks."""

from collections import Counter
from pathlib import Path
from typing import Optional

import yaml

from .models import IndexEntry, ProjectIndex, is_archived
from .store import Store

#: The five files ``write_index`` derives from the item files.  Nothing in a
#: store is the source of truth for them — every byte is recomputed from the
#: epics, stories and tasks — so new stores do not track them; see
#: :func:`write_store_gitignore` and ``docs/reference/file-formats.md``.
DERIVED_INDEX_FILES = (
    "index.yaml",
    "INDEX.md",
    "INDEX-EPICS.md",
    "INDEX-STORIES.md",
    "INDEX-TASKS.md",
)

_GITIGNORE_HEADER = (
    "# Derived index files — regenerated from the epic, story and task files\n"
    "# by pm_reindex, pm_commit, `projectman reindex` and indexer.ensure_fresh\n"
    "# on the read path, so git never needs to carry them (US-PM-29).\n"
)

_STATUS_EMOJI = {
    "backlog": "\U0001f4cb",  # clipboard
    "draft": "\U0001f4dd",  # memo
    "ready": "\U0001f7e2",  # green circle
    "active": "\U0001f3c3",  # runner
    "in-progress": "\U0001f3c3",
    "todo": "\u26aa",  # white circle
    "review": "\U0001f50d",  # magnifying glass
    "done": "\u2705",  # check mark
    "blocked": "\U0001f6d1",  # stop sign
    "archived": "\U0001f4e6",  # package
}


def _status_label(status: str) -> str:
    emoji = _STATUS_EMOJI.get(status, "")
    return f"{emoji} {status}" if emoji else status


def _task_status_label(task) -> str:
    """Status label for a task, annotated when the task is archived.

    Archival is a flag beside a task's status, so rendering status alone would
    show an abandoned task as (say) plain "todo".
    """
    label = _status_label(task.status.value)
    if getattr(task, "archived", False):
        return f"{_STATUS_EMOJI['archived']} archived ({label})"
    return label


def build_index(
    store: Store,
    *,
    epics: Optional[list] = None,
    stories: Optional[list] = None,
    tasks: Optional[list] = None,
) -> ProjectIndex:
    """Read all epics, stories, and tasks, produce a ProjectIndex.

    Accepts optional pre-loaded lists to avoid redundant cache lookups.

    Archived items are still listed in ``entries`` — they happened, and the
    index is the record of what exists — but they are excluded from *both*
    sides of the points math.  Archived work is abandoned: counting it as
    completed inflates delivery, and leaving it in the denominator alone
    inflates the outstanding work a burndown says is still to do.  Dropping
    it from both is the only reading that says "this is no longer part of
    the plan".
    """
    if epics is None:
        epics = store.list_epics()
    if stories is None:
        stories = store.list_stories()
    if tasks is None:
        tasks = store.list_tasks()

    entries: list[IndexEntry] = []
    total_points = 0
    completed_points = 0

    for epic in epics:
        entries.append(
            IndexEntry(
                id=epic.id,
                title=epic.title,
                type="epic",
                status=epic.status.value,
            )
        )

    for story in stories:
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
        if story.points and not is_archived(story):
            total_points += story.points
            if story.status.value == "done":
                completed_points += story.points

    for task in tasks:
        entries.append(
            IndexEntry(
                id=task.id,
                title=task.title,
                type="task",
                status=task.status.value,
                archived=task.archived,
                points=task.points,
                story_id=task.story_id,
            )
        )
        if task.points and not is_archived(task):
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


def write_markdown_indexes(
    store: Store,
    *,
    epics: Optional[list] = None,
    stories: Optional[list] = None,
    tasks: Optional[list] = None,
) -> None:
    """Generate the 4 markdown index files in .project/.

    Accepts optional pre-loaded lists to avoid redundant cache lookups.
    """
    if epics is None:
        epics = store.list_epics()
    if stories is None:
        stories = store.list_stories()
    if tasks is None:
        tasks = store.list_tasks()

    # Pre-compute counts
    stories_per_epic: Counter[str] = Counter()
    for s in stories:
        if s.epic_id:
            stories_per_epic[s.epic_id] += 1

    tasks_per_story: Counter[str] = Counter()
    for t in tasks:
        tasks_per_story[t.story_id] += 1

    ac_per_story: dict[str, int] = {s.id: len(s.acceptance_criteria) for s in stories}

    points_per_epic: Counter[str] = Counter()
    for s in stories:
        if s.epic_id and s.points:
            points_per_epic[s.epic_id] += s.points

    project_name = store.config.name

    # --- INDEX.md ---
    lines = [
        f"# {project_name}",
        "",
        "| Metric | Count |",
        "| ------ | ----- |",
        f"| Epics | {len(epics)} |",
        f"| Stories | {len(stories)} |",
        f"| Tasks | {len(tasks)} |",
        "",
        "## Indexes",
        "",
        "- [Epics](INDEX-EPICS.md)",
        "- [Stories](INDEX-STORIES.md)",
        "- [Tasks](INDEX-TASKS.md)",
        "",
    ]
    index_content = "\n".join(lines)

    (store.project_dir / "INDEX.md").write_text(index_content)

    # --- INDEX-EPICS.md ---
    lines = ["# Epics", ""]
    if epics:
        lines.append("| ID | Title | Status | Priority | Tags | Stories | Points |")
        lines.append("| -- | ----- | ------ | -------- | ---- | ------- | ------ |")
        for e in sorted(epics, key=lambda x: x.id):
            link = f"[{e.id}](epics/{e.id}.md)"
            sc = stories_per_epic.get(e.id, 0)
            pts = points_per_epic.get(e.id, 0) or "—"
            tags = ", ".join(e.tags) if e.tags else ""
            lines.append(
                f"| {link} | {e.title} | {_status_label(e.status.value)} "
                f"| {e.priority.value} | {tags} | {sc} | {pts} |"
            )
    else:
        lines.append("_No epics yet._")
    lines.append("")
    (store.project_dir / "INDEX-EPICS.md").write_text("\n".join(lines))

    # --- INDEX-STORIES.md ---
    lines = ["# Stories", ""]
    if stories:
        lines.append(
            "| ID | Title | Status | Priority | Points | Tags | Epic | ACs | Tasks |"
        )
        lines.append(
            "| -- | ----- | ------ | -------- | ------ | ---- | ---- | --- | ----- |"
        )
        for s in sorted(stories, key=lambda x: x.id):
            link = f"[{s.id}](stories/{s.id}.md)"
            pts = s.points if s.points is not None else "—"
            tags = ", ".join(s.tags) if s.tags else ""
            epic_link = f"[{s.epic_id}](epics/{s.epic_id}.md)" if s.epic_id else "—"
            acs = ac_per_story.get(s.id, 0)
            tc = tasks_per_story.get(s.id, 0)
            lines.append(
                f"| {link} | {s.title} | {_status_label(s.status.value)} "
                f"| {s.priority.value} | {pts} | {tags} | {epic_link} | {acs} | {tc} |"
            )
    else:
        lines.append("_No stories yet._")
    lines.append("")
    (store.project_dir / "INDEX-STORIES.md").write_text("\n".join(lines))

    # --- INDEX-TASKS.md ---
    lines = ["# Tasks", ""]
    if tasks:
        lines.append(
            "| ID | Title | Status | Points | Tags | Assignee | Depends On | Story |"
        )
        lines.append(
            "| -- | ----- | ------ | ------ | ---- | -------- | ---------- | ----- |"
        )
        for t in sorted(tasks, key=lambda x: x.id):
            link = f"[{t.id}](tasks/{t.id}.md)"
            pts = t.points if t.points is not None else "—"
            tags = ", ".join(t.tags) if t.tags else ""
            assignee = t.assignee or "—"
            deps = ", ".join(t.depends_on) if t.depends_on else "—"
            story_link = f"[{t.story_id}](stories/{t.story_id}.md)"
            lines.append(
                f"| {link} | {t.title} | {_task_status_label(t)} "
                f"| {pts} | {tags} | {assignee} | {deps} | {story_link} |"
            )
    else:
        lines.append("_No tasks yet._")
    lines.append("")
    (store.project_dir / "INDEX-TASKS.md").write_text("\n".join(lines))


def write_index(store: Store) -> None:
    """Build index and write index.yaml and markdown indexes to disk.

    Always reads directly from disk to guarantee index reflects current state,
    bypassing the cache which may be stale due to external changes (e.g., git pull).
    """
    epic_entries = store._read_epics_from_disk()
    story_entries = store._read_stories_from_disk()
    task_entries = store._read_tasks_from_disk()

    epics = [meta for meta, _ in epic_entries]
    stories = [meta for meta, _ in story_entries]
    tasks = [meta for meta, _ in task_entries]

    index = build_index(store, epics=epics, stories=stories, tasks=tasks)
    index_path = store.project_dir / "index.yaml"
    data = index.model_dump(mode="json")
    with open(index_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    write_markdown_indexes(store, epics=epics, stories=stories, tasks=tasks)


def write_store_gitignore(project_dir: Path) -> Path:
    """Ensure ``{project_dir}/.gitignore`` excludes the derived index files.

    Called when a store is scaffolded (``projectman init``).  The five
    files in
    :data:`DERIVED_INDEX_FILES` are a rendering of the item files beside
    them, so tracking them buys nothing and costs on every write: the item
    change and its index echo land in the same commit, a one-task edit
    reads as four changed files instead of two, ``index.yaml`` is a
    guaranteed conflict for any two branches that touched different tasks,
    and a plain *read* through ``ensure_fresh`` can dirty the tree.  The
    numbers behind that decision are in ``docs/reference/file-formats.md``.

    Idempotent, and additive rather than destructive: an existing
    ``.gitignore`` keeps every line it has and gains only the derived names
    it is missing, so a store that ignores other things too is safe to
    re-scaffold.  Returns the path written.
    """
    path = project_dir / ".gitignore"
    existing = path.read_text() if path.exists() else ""
    present = {line.strip() for line in existing.splitlines()}
    missing = [name for name in DERIVED_INDEX_FILES if name not in present]
    if not missing:
        return path

    if not existing:
        path.write_text(_GITIGNORE_HEADER + "\n".join(missing) + "\n")
        return path

    prefix = existing if existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + "\n" + _GITIGNORE_HEADER + "\n".join(missing) + "\n")
    return path


def _newest_item_mtime_ns(store: Store) -> Optional[int]:
    """Modification time of the most recently written epic, story or task file.

    ``None`` when the project holds no item files at all: nothing can have
    outrun the index, so there is nothing to be stale against.
    """
    newest: Optional[int] = None
    for directory in (store.epics_dir, store.stories_dir, store.tasks_dir):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:  # vanished mid-scan; the next read will catch it
                continue
            if newest is None or mtime > newest:
                newest = mtime
    return newest


def index_is_stale(store: Store) -> bool:
    """True when ``index.yaml`` is missing, or older than the newest item file.

    The comparison is strict: ``write_index`` writes ``index.yaml`` *after*
    reading the item files, so a fresh index always carries the later
    timestamp, and equality means "written together", not "behind".
    """
    try:
        index_mtime = (store.project_dir / "index.yaml").stat().st_mtime_ns
    except OSError:
        # No index at all (or unreadable) — a reader has nothing to serve.
        return True
    newest = _newest_item_mtime_ns(store)
    return newest is not None and newest > index_mtime


def ensure_fresh(store: Store) -> bool:
    """Rebuild the derived index files when they have fallen behind the items.

    Mutating tools no longer rewrite the indexes (story US-PM-29): the five
    derived files are only as current as the last ``pm_reindex``,
    ``pm_commit`` or ``projectman reindex``.  Any reader that serves numbers
    out of ``index.yaml`` rather than out of the ``Store`` must therefore
    check before it reads, and this is that check — a stat of the item files
    against ``index.yaml``, and a full rebuild only when the items have moved
    on.

    Returns True if a rebuild happened.  Cheap and side-effect free when the
    index is already current, so it is safe on a read path.
    """
    if not store.project_dir.is_dir():
        return False
    if not index_is_stale(store):
        return False
    write_index(store)
    return True
