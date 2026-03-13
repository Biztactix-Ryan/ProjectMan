"""ProjectMan MCP server — FastMCP-based with stdio/SSE transport."""

import asyncio
from pathlib import Path
from typing import Optional

import frontmatter
import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import find_project_root, load_config
from .indexer import build_index, write_index
from .models import ChangesetStatus, ProjectIndex
from .store import Store

mcp = FastMCP("projectman")

# Lock for write operations in SSE (multi-client) mode
_write_lock = asyncio.Lock()


def _resolve_project_dir(project: Optional[str] = None) -> Path:
    """Return the .project/ directory for a project, handling hub layout."""
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            pm_dir = root / ".project" / "projects" / project
            if pm_dir.exists() and (pm_dir / "config.yaml").exists():
                return pm_dir
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    return root / ".project"


_store_cache: dict[Path, Store] = {}


def _store(project: Optional[str] = None) -> Store:
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            project_dir = root / ".project" / "projects" / project
            if project_dir.exists() and (project_dir / "config.yaml").exists():
                if project_dir not in _store_cache:
                    _store_cache[project_dir] = Store(root, project_dir=project_dir)
                return _store_cache[project_dir]
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    default_dir = root / ".project"
    if default_dir not in _store_cache:
        _store_cache[default_dir] = Store(root)
    return _store_cache[default_dir]


def _yaml_dump(data) -> str:
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


# ─── Query Tools ────────────────────────────────────────────────

@mcp.tool(title="Project Status", annotations=ToolAnnotations(title="Project Status", readOnlyHint=True))
def pm_status(project: Optional[str] = None) -> str:
    """Get project status summary: story/task counts, points, completion percentage.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        index = build_index(store)
        pct = 0
        if index.total_points > 0:
            pct = round(index.completed_points / index.total_points * 100)

        # Group by status
        status_groups = {}
        for entry in index.entries:
            status_groups.setdefault(entry.status, []).append(entry)

        # Changeset summary
        changesets = store.list_changesets()
        cs_by_status = {}
        for cs in changesets:
            cs_by_status.setdefault(cs.status.value, 0)
            cs_by_status[cs.status.value] += 1

        result = {
            "project": store.config.name,
            "epics": index.epic_count,
            "stories": index.story_count,
            "tasks": index.task_count,
            "total_points": index.total_points,
            "completed_points": index.completed_points,
            "completion": f"{pct}%",
            "by_status": {k: len(v) for k, v in status_groups.items()},
            "changesets": len(changesets),
            "changesets_by_status": cs_by_status,
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Get Item", annotations=ToolAnnotations(title="Get Item", readOnlyHint=True))
def pm_get(id: str, project: Optional[str] = None) -> str:
    """Get full details of an epic, story, or task by ID.

    Args:
        id: Epic ID (e.g. EPIC-PRJ-1), story ID (e.g. US-PRJ-1), or task ID (e.g. US-PRJ-1-1)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        meta, body = store.get(id)
        result = meta.model_dump(mode="json")
        result["body"] = body
        recent_log = store.get_run_log(id, limit=3)
        if recent_log:
            result["recent_run_log"] = [e.model_dump(mode="json") for e in recent_log]
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Batch Get Items", annotations=ToolAnnotations(title="Batch Get Items", readOnlyHint=True))
def pm_batch_get(type: str, project: Optional[str] = None) -> str:
    """Get all items of a type with full data in a single call.

    Returns all epics, stories, or tasks with frontmatter and body content.
    Much faster than calling pm_get for each item individually.

    Args:
        type: Item type to fetch: "epics", "stories", or "tasks"
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        items = store.list_all(type)
        return _yaml_dump(items)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Read Documentation", annotations=ToolAnnotations(title="Read Documentation", readOnlyHint=True))
def pm_docs(doc: Optional[str] = None, project: Optional[str] = None) -> str:
    """Read project documentation files.

    Args:
        doc: Specific doc to read: "project", "infrastructure", "security", "vision", "architecture", or "decisions". Omit for a summary of all.
        project: Optional project name (hub mode only)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        doc_map = {
            "project": "PROJECT.md",
            "infrastructure": "INFRASTRUCTURE.md",
            "security": "SECURITY.md",
            "vision": "VISION.md",
            "architecture": "ARCHITECTURE.md",
            "decisions": "DECISIONS.md",
        }

        if doc:
            filename = doc_map.get(doc.lower())
            if not filename:
                return f"error: unknown doc '{doc}'. Use: project, infrastructure, security, vision, architecture, or decisions"
            path = proj_dir / filename
            if not path.exists():
                return f"error: {filename} not found"
            return path.read_text()

        # Summary mode: return all docs with their status
        import os
        from datetime import date as _date
        summary = {}
        for key, filename in doc_map.items():
            path = proj_dir / filename
            if path.exists():
                content = path.read_text()
                mtime = _date.fromtimestamp(os.path.getmtime(path))
                age = (_date.today() - mtime).days
                lines = [l for l in content.splitlines() if l.strip()
                         and not l.strip().startswith("<!--")
                         and not l.strip().startswith("-->")]
                summary[key] = {
                    "file": filename,
                    "last_modified": str(mtime),
                    "age_days": age,
                    "content_lines": len(lines),
                    "status": "stale" if age > 30 else "current",
                }
            else:
                summary[key] = {"file": filename, "status": "missing"}
        return _yaml_dump(summary)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Update Documentation", annotations=ToolAnnotations(title="Update Documentation", readOnlyHint=False, destructiveHint=False))
def pm_update_doc(
    doc: str,
    content: str,
    project: Optional[str] = None,
) -> str:
    """Update a project documentation file.

    Args:
        doc: Which doc to update: "project", "infrastructure", "security", "vision", "architecture", or "decisions"
        content: The full new content for the document
        project: Optional project name (hub mode only)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        doc_map = {
            "project": "PROJECT.md",
            "infrastructure": "INFRASTRUCTURE.md",
            "security": "SECURITY.md",
            "vision": "VISION.md",
            "architecture": "ARCHITECTURE.md",
            "decisions": "DECISIONS.md",
        }

        filename = doc_map.get(doc.lower())
        if not filename:
            return f"error: unknown doc '{doc}'. Use: project, infrastructure, security, vision, architecture, or decisions"

        path = proj_dir / filename
        path.write_text(content)
        return f"updated: {filename}"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Active Work", annotations=ToolAnnotations(title="Active Work", readOnlyHint=True))
def pm_active(
    project: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List active/in-progress stories and tasks.

    Args:
        project: Optional project name (hub mode only)
        tag: Filter to show only items (or their parent stories) with this tag
        limit: Max items per list (default 20)
        offset: Starting index for pagination (default 0)
    """
    try:
        store = _store(project)
        all_stories = store.list_stories(status="active")
        all_tasks = store.list_tasks(status="in-progress")

        if tag:
            all_stories = [s for s in all_stories if tag in s.tags]
            story_cache = {s.id: s for s in store.list_stories()}
            all_tasks = [
                t for t in all_tasks
                if tag in t.tags or (
                    story_cache.get(t.story_id) is not None
                    and tag in story_cache[t.story_id].tags
                )
            ]

        stories_page = all_stories[offset : offset + limit]
        tasks_page = all_tasks[offset : offset + limit]

        result = {
            "active_stories": [s.model_dump(mode="json") for s in stories_page],
            "active_stories_total": len(all_stories),
            "active_tasks": [t.model_dump(mode="json") for t in tasks_page],
            "active_tasks_total": len(all_tasks),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < len(all_stories) or (offset + limit) < len(all_tasks),
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Search Items", annotations=ToolAnnotations(title="Search Items", readOnlyHint=True))
def pm_search(query: str, project: Optional[str] = None, tag: Optional[str] = None) -> str:
    """Search stories and tasks by keyword or semantic similarity.

    Args:
        query: Search query string
        project: Optional project name (hub mode only)
        tag: Optional tag to filter results (only items with this tag are returned)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        # Try embeddings first, fall back to keyword
        try:
            from .embeddings import EmbeddingStore
            emb_store = EmbeddingStore(proj_dir)
            results = emb_store.search(query, top_k=10)
            if results:
                # Post-filter by tag if specified
                if tag:
                    store = Store(proj_dir)
                    filtered = []
                    for r in results:
                        try:
                            meta, _ = store.get(r.id)
                            if tag in (meta.tags if hasattr(meta, "tags") else []):
                                filtered.append(r)
                        except Exception:
                            pass
                    results = filtered
                return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": round(r.score, 3)} for r in results])
        except (ImportError, Exception):
            pass

        from .search import keyword_search
        results = keyword_search(query, proj_dir, tag=tag)
        return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": r.score, "snippet": r.snippet} for r in results])
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Task Board", annotations=ToolAnnotations(title="Task Board", readOnlyHint=True))
def pm_board(
    project: Optional[str] = None,
    assignee: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Show the task board — available tasks grouped by status and readiness.

    Args:
        project: Optional project name (hub mode only)
        assignee: Filter to show only tasks for this assignee
        tag: Filter to show only tasks (or their parent stories) with this tag
        limit: Max items per board group (default 10). Totals are always shown.
    """
    try:
        from .readiness import check_readiness, compute_hints
        from .deps import topological_sort

        store = _store(project)
        all_tasks = store.list_tasks()

        # Build a story lookup for priority ordering and context
        story_cache = {}
        for story in store.list_stories():
            story_cache[story.id] = story

        # Build topological position map per story for dependency-aware ordering
        story_tasks: dict[str, list] = {}
        for task in all_tasks:
            story_tasks.setdefault(task.story_id, []).append(task)
        topo_position: dict[str, int] = {}
        for sid, tasks_in_story in story_tasks.items():
            try:
                sorted_tasks = topological_sort(tasks_in_story)
            except Exception:
                sorted_tasks = tasks_in_story
            for idx, t in enumerate(sorted_tasks):
                topo_position[t.id] = idx

        available = []
        not_ready = []
        in_progress = []
        in_review = []
        blocked = []

        for task in all_tasks:
            _, task_body = store.get_task(task.id)
            story = story_cache.get(task.story_id)
            story_label = f"{story.id} — {story.title}" if story else task.story_id

            if assignee and task.assignee != assignee:
                continue

            if tag:
                task_has_tag = tag in task.tags
                story_has_tag = story is not None and tag in story.tags
                if not task_has_tag and not story_has_tag:
                    continue

            if task.status.value == "in-progress":
                in_progress.append({
                    "id": task.id,
                    "title": task.title,
                    "points": task.points,
                    "assignee": task.assignee,
                    "story": story_label,
                })
            elif task.status.value == "review":
                in_review.append({
                    "id": task.id,
                    "title": task.title,
                    "points": task.points,
                    "assignee": task.assignee,
                    "story": story_label,
                })
            elif task.status.value == "blocked":
                blocked.append({
                    "id": task.id,
                    "title": task.title,
                    "points": task.points,
                    "assignee": task.assignee,
                    "story": story_label,
                })
            elif task.status.value == "todo" and not assignee:
                readiness = check_readiness(task, task_body, store)
                if readiness["ready"]:
                    hints = compute_hints(task, task_body)
                    priority_order = {"must": 0, "should": 1, "could": 2, "wont": 3}
                    story_priority = priority_order.get(
                        story.priority.value if story else "should", 1
                    )
                    available.append({
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "story": story_label,
                        "hints": hints,
                        "_sort": (story_priority, task.story_id, topo_position.get(task.id, 0), task.points or 99),
                    })
                else:
                    not_ready.append({
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "story": story_label,
                        "blockers": readiness["blockers"],
                    })

        # Sort available tasks by priority > story > topological order > points
        available.sort(key=lambda t: t["_sort"])
        for t in available:
            del t["_sort"]

        result = {
            "board": {
                "available": available[:limit],
                "not_ready": not_ready[:limit],
                "in_progress": in_progress[:limit],
                "in_review": in_review[:limit],
                "blocked": blocked[:limit],
            },
            "summary": {
                "available": len(available),
                "not_ready": len(not_ready),
                "in_progress": len(in_progress),
                "in_review": len(in_review),
                "blocked": len(blocked),
            },
            "limit": limit,
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Burndown Data", annotations=ToolAnnotations(title="Burndown Data", readOnlyHint=True))
def pm_burndown(project: Optional[str] = None) -> str:
    """Get burndown data: total vs completed points.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        # Hub mode: aggregate across projects
        if config.hub and not project:
            try:
                from .hub.rollup import rollup
                data = rollup(root)
                return _yaml_dump(data)
            except (ImportError, Exception):
                pass

        store = _store(project)
        index = build_index(store)

        remaining = index.total_points - index.completed_points
        result = {
            "project": store.config.name,
            "total_points": index.total_points,
            "completed_points": index.completed_points,
            "remaining_points": remaining,
            "completion": f"{round(index.completed_points / max(index.total_points, 1) * 100)}%",
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


# ─── Write Tools ────────────────────────────────────────────────

@mcp.tool(title="Create Story", annotations=ToolAnnotations(title="Create Story", readOnlyHint=False, destructiveHint=False))
def pm_create_story(
    title: str,
    description: str,
    priority: Optional[str] = None,
    points: Optional[int] = None,
    epic_id: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    tags: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new user story.

    Args:
        title: Story title
        description: Story description ("As a [user], I want [goal] so that [benefit]")
        priority: Priority level: must, should, could, wont
        points: Story points (fibonacci: 1,2,3,5,8,13)
        epic_id: Optional parent epic ID (e.g. EPIC-PRJ-1)
        acceptance_criteria: Comma-separated acceptance criteria (e.g. "Users can log in,Error shown on invalid password")
        tags: Comma-separated tags (e.g. "security,mvp")
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        ac_list = [c.strip() for c in acceptance_criteria.split(",")] if acceptance_criteria else None
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        meta, test_tasks = store.create_story(title, description, priority, points, tags=tag_list, acceptance_criteria=ac_list)
        if epic_id:
            store.update(meta.id, epic_id=epic_id)
            meta, _ = store.get_story(meta.id)
        write_index(store)
        result = {"created": meta.model_dump(mode="json")}
        if test_tasks:
            result["test_tasks"] = [t.model_dump(mode="json") for t in test_tasks]
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Create Epic", annotations=ToolAnnotations(title="Create Epic", readOnlyHint=False, destructiveHint=False))
def pm_create_epic(
    title: str,
    description: str,
    priority: Optional[str] = None,
    target_date: Optional[str] = None,
    tags: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new epic for grouping related stories.

    Args:
        title: Epic title (short strategic name)
        description: Epic description (vision, success criteria, scope)
        priority: Priority level: must, should, could, wont
        target_date: Optional target date (YYYY-MM-DD)
        tags: Comma-separated tags (e.g. "security,mvp")
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        meta = store.create_epic(title, description, priority, target_date, tag_list)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Epic Details", annotations=ToolAnnotations(title="Epic Details", readOnlyHint=True))
def pm_epic(
    id: str,
    project: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Get epic details with rollup of linked stories and tasks.

    Args:
        id: Epic ID (e.g. EPIC-PRJ-1)
        project: Optional project name (hub mode only)
        limit: Max stories to return (default 10)
        offset: Starting index for story pagination (default 0)
    """
    try:
        store = _store(project)
        meta, body = store.get_epic(id)

        # Find linked stories — compute rollup from ALL, paginate the detail list
        linked_stories = [s for s in store.list_stories() if s.epic_id == id]
        story_data = []
        total_points = 0
        completed_points = 0

        for i, story in enumerate(linked_stories):
            tasks = store.list_tasks(story_id=story.id)
            story_points = sum(t.points or 0 for t in tasks)
            done_points = sum(t.points or 0 for t in tasks if t.status.value == "done")
            total_points += story_points
            completed_points += done_points

            # Only include full detail for the current page
            if offset <= i < offset + limit:
                task_summary = [
                    {"id": t.id, "title": t.title, "status": t.status.value, "points": t.points}
                    for t in tasks
                ]
                story_data.append({
                    "id": story.id,
                    "title": story.title,
                    "status": story.status.value,
                    "points": story.points,
                    "tasks": task_summary,
                    "task_points": story_points,
                    "done_points": done_points,
                })

        total_stories = len(linked_stories)
        has_more = (offset + limit) < total_stories

        result = {
            "epic": meta.model_dump(mode="json"),
            "body": body,
            "stories": story_data,
            "rollup": {
                "story_count": total_stories,
                "total_points": total_points,
                "completed_points": completed_points,
                "completion": f"{round(completed_points / max(total_points, 1) * 100)}%",
            },
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }
        if has_more:
            result["next_offset"] = offset + limit
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Project Context", annotations=ToolAnnotations(title="Project Context", readOnlyHint=True))
def pm_context(
    project: Optional[str] = None,
    limit: int = 20,
) -> str:
    """Get combined hub + project context for an agent starting work.

    Returns hub-level vision/architecture (if hub mode) plus project-specific
    docs, active epics, and active stories.

    Args:
        project: Optional project name (hub mode only)
        limit: Max epics/stories to include (default 20)
    """
    try:
        hub_root = find_project_root()
        hub_config = load_config(hub_root)
        store = _store(project)
        proj_dir = store.project_dir

        result = {}

        # Hub-level context (if hub mode)
        if hub_config.hub:
            hub_dir = hub_root / ".project"
            for doc_key, filename in [("vision", "VISION.md"), ("architecture", "ARCHITECTURE.md")]:
                path = hub_dir / filename
                if path.exists():
                    result[f"hub_{doc_key}"] = path.read_text()

        # Project-level context
        project_docs = {}
        for doc_key, filename in [("project", "PROJECT.md"), ("infrastructure", "INFRASTRUCTURE.md"), ("security", "SECURITY.md")]:
            path = proj_dir / filename
            if path.exists():
                project_docs[doc_key] = path.read_text()
        result["project_docs"] = project_docs

        # Active epics
        active_epics = store.list_epics(status="active")
        result["active_epics_total"] = len(active_epics)
        if active_epics:
            result["active_epics"] = [
                {"id": e.id, "title": e.title, "priority": e.priority.value}
                for e in active_epics[:limit]
            ]

        # Active stories
        active_stories = store.list_stories(status="active")
        result["active_stories_total"] = len(active_stories)
        if active_stories:
            result["active_stories"] = [
                {"id": s.id, "title": s.title, "epic_id": s.epic_id, "priority": s.priority.value}
                for s in active_stories[:limit]
            ]

        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Create Task", annotations=ToolAnnotations(title="Create Task", readOnlyHint=False, destructiveHint=False))
def pm_create_task(
    story_id: str,
    title: str,
    description: str,
    points: Optional[int] = None,
    tags: Optional[str] = None,
    depends_on: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new task under a story.

    Args:
        story_id: Parent story ID (e.g. US-PRJ-1)
        title: Task title
        description: Task description with implementation details
        points: Task points (fibonacci: 1,2,3,5,8,13)
        tags: Comma-separated tags (e.g. "backend,api")
        depends_on: Comma-separated task IDs this task depends on (e.g. "US-PRJ-1-1,US-PRJ-1-2")
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        dep_list = [d.strip() for d in depends_on.split(",")] if depends_on else None
        meta = store.create_task(story_id, title, description, points, tags=tag_list, depends_on=dep_list)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Batch Create Tasks", annotations=ToolAnnotations(title="Batch Create Tasks", readOnlyHint=False, destructiveHint=False))
def pm_create_tasks(
    story_id: str,
    tasks: list[dict],
    project: Optional[str] = None,
) -> str:
    """Create multiple tasks under a story in a single call.

    Args:
        story_id: Parent story ID (e.g. US-PRJ-1)
        tasks: List of task dicts, each with keys: title (str), description (str), points (int, optional), depends_on (list[str], optional)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        created = store.create_tasks(story_id, tasks)
        write_index(store)
        total_points = sum(t.points or 0 for t in created)
        return _yaml_dump({
            "created": [t.model_dump(mode="json") for t in created],
            "count": len(created),
            "total_points": total_points,
        })
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Update Item", annotations=ToolAnnotations(title="Update Item", readOnlyHint=False, destructiveHint=False))
def pm_update(
    id: str,
    status: Optional[str] = None,
    points: Optional[int] = None,
    title: Optional[str] = None,
    assignee: Optional[str] = None,
    epic_id: Optional[str] = None,
    body: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    tags: Optional[str] = None,
    depends_on: Optional[str] = None,
    outcome: Optional[str] = None,
    note: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Update an epic, story, or task.

    Args:
        id: Epic, story, or task ID
        status: New status (epics: draft/active/done/archived; stories: backlog/ready/active/done/archived; tasks: todo/in-progress/review/done/blocked)
        points: New point estimate (fibonacci: 1,2,3,5,8,13)
        title: New title
        assignee: Assignee name (tasks only)
        epic_id: Link a story to an epic (stories only)
        body: New markdown body/description content
        acceptance_criteria: Comma-separated acceptance criteria (stories only, e.g. "Users can log in,Error shown on invalid password")
        tags: Comma-separated tags (e.g. "security,mvp,backend")
        depends_on: Comma-separated task IDs this task depends on (tasks only, e.g. "US-PRJ-1-1,US-PRJ-1-2")
        outcome: Run-log outcome (success/partial/blocked/failed/info). When provided with note, appends a run-log entry for tracking work attempts.
        note: Run-log note describing what was accomplished or what blocked progress (max 1024 chars). Requires outcome.
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        kwargs = {}
        if status is not None:
            kwargs["status"] = status
        if points is not None:
            kwargs["points"] = points
        if title is not None:
            kwargs["title"] = title
        if assignee is not None:
            kwargs["assignee"] = assignee
        if epic_id is not None:
            kwargs["epic_id"] = epic_id
        if body is not None:
            kwargs["body"] = body
        if acceptance_criteria is not None:
            kwargs["acceptance_criteria"] = [c.strip() for c in acceptance_criteria.split(",")]
        if tags is not None:
            kwargs["tags"] = [t.strip() for t in tags.split(",")]
        if depends_on is not None:
            kwargs["depends_on"] = [d.strip() for d in depends_on.split(",")]
        if outcome is not None:
            kwargs["outcome"] = outcome
        if note is not None:
            kwargs["note"] = note

        meta = store.update(id, **kwargs)
        write_index(store)
        return _yaml_dump({"updated": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Archive Item", annotations=ToolAnnotations(title="Archive Item", readOnlyHint=False, destructiveHint=True))
def pm_archive(id: str, project: Optional[str] = None) -> str:
    """Archive an epic, story, or task.

    Args:
        id: Epic, story, or task ID to archive
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        store.archive(id)
        write_index(store)
        return f"archived: {id}"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Grab Task", annotations=ToolAnnotations(title="Grab Task", readOnlyHint=False, destructiveHint=False))
def pm_grab(
    task_id: str,
    assignee: str = "claude",
    project: Optional[str] = None,
) -> str:
    """Claim a task — validates readiness, assigns, sets in-progress, loads context.

    Args:
        task_id: Task ID to claim (e.g. US-PRJ-1-1)
        assignee: Who is claiming (default "claude" for AI agents, or a human name)
        project: Optional project name (hub mode only)
    """
    try:
        from .readiness import check_readiness

        store = _store(project)
        task_meta, task_body = store.get_task(task_id)

        # Validate readiness
        readiness = check_readiness(task_meta, task_body, store)
        if not readiness["ready"]:
            return _yaml_dump({
                "error": "task is not ready to grab",
                "blockers": readiness["blockers"],
            })

        # Claim: set assignee and status
        store.update(task_id, assignee=assignee, status="in-progress")
        write_index(store)

        # Re-read updated task
        task_meta, task_body = store.get_task(task_id)

        # Load parent story context
        story_context = {}
        try:
            story_meta, story_body = store.get_story(task_meta.story_id)
            story_context = {
                "id": story_meta.id,
                "title": story_meta.title,
                "status": story_meta.status.value,
                "priority": story_meta.priority.value,
                "body": story_body,
            }
        except FileNotFoundError:
            story_context = {"id": task_meta.story_id, "error": "not found"}

        # Load sibling tasks (cap at 20 to avoid bloat)
        siblings = store.list_tasks(story_id=task_meta.story_id)
        all_siblings = [s for s in siblings if s.id != task_id]
        sibling_map = {s.id: s for s in siblings}
        sibling_list = [
            {"id": s.id, "title": s.title, "status": s.status.value, "assignee": s.assignee}
            for s in all_siblings[:20]
        ]

        # Build dependency status
        dependency_status = []
        if task_meta.depends_on:
            for dep_id in task_meta.depends_on:
                dep = sibling_map.get(dep_id)
                if dep:
                    dependency_status.append({
                        "id": dep.id,
                        "title": dep.title,
                        "status": dep.status.value,
                    })

        result = {
            "grabbed": {
                "task": task_meta.model_dump(mode="json"),
                "body": task_body,
                "story_context": story_context,
                "sibling_tasks": sibling_list,
                "sibling_tasks_total": len(all_siblings),
                "dependency_status": dependency_status,
                "warnings": readiness["warnings"],
            },
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


# ─── Intelligence Tools ─────────────────────────────────────────

@mcp.tool(title="Estimation Context", annotations=ToolAnnotations(title="Estimation Context", readOnlyHint=True))
def pm_estimate(id: str, project: Optional[str] = None) -> str:
    """Get estimation context for a story or task — returns content + calibration guidelines.

    Args:
        id: Story or task ID to estimate
        project: Optional project name (hub mode only)
    """
    try:
        from .estimator import estimate
        store = _store(project)
        return estimate(store, id)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Scoping Context", annotations=ToolAnnotations(title="Scoping Context", readOnlyHint=True))
def pm_scope(id: str, project: Optional[str] = None) -> str:
    """Get scoping context for a story — returns story + existing tasks + decomposition guidance.

    Args:
        id: Story ID to scope into tasks
        project: Optional project name (hub mode only)
    """
    try:
        from .scoper import scope
        store = _store(project)
        return scope(store, id)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Project Audit", annotations=ToolAnnotations(title="Project Audit", readOnlyHint=True))
def pm_audit(project: Optional[str] = None) -> str:
    """Run project audit — checks for drift, inconsistencies, stale items.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        from .audit import run_audit
        root = find_project_root()
        if project:
            config = load_config(root)
            if config.hub:
                pm_dir = root / ".project" / "projects" / project
                if not (pm_dir / "config.yaml").exists():
                    return f"error: project '{project}' not found in hub"
                return run_audit(root, project_dir=pm_dir)
        return run_audit(root)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Hub Repair", annotations=ToolAnnotations(title="Hub Repair", readOnlyHint=False, destructiveHint=False))
def pm_repair() -> str:
    """Scan the hub for unregistered projects, initialize missing PM data
    directories (hub_root/.project/projects/{name}/), rebuild all indexes
    and embeddings, and regenerate dashboards.
    Hub mode only. Writes a REPAIR.md report."""
    try:
        config = load_config(find_project_root())
        if not config.hub:
            return "error: not a hub project"
        from .hub.registry import repair
        return repair()
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Validate Branches", annotations=ToolAnnotations(title="Validate Branches", readOnlyHint=True))
def pm_validate_branches() -> str:
    """Validate that each hub submodule is on its expected tracked branch.

    Returns structured data with aligned, misaligned, detached, and missing
    projects plus an overall ok flag and summary string.
    """
    try:
        from .hub.registry import validate_branches
        root = find_project_root()
        result = validate_branches(root=root)
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Next Malformed File", annotations=ToolAnnotations(title="Next Malformed File", readOnlyHint=True))
def pm_malformed(project: Optional[str] = None) -> str:
    """Get the next malformed file to fix. Returns one file at a time with its full
    content. Call pm_fix_malformed to fix it (which removes it from the queue),
    then call pm_malformed again to get the next one. Repeat until done.

    Args:
        project: Optional project name (hub mode only). Omit to scan all.
    """
    try:
        import frontmatter

        root = find_project_root()
        config = load_config(root)

        # Collect all malformed files across projects
        all_files = []  # list of (project_name, path)
        dirs_to_scan = []
        if project:
            proj_dir = _resolve_project_dir(project)
            malformed_dir = proj_dir / "malformed"
            if malformed_dir.exists():
                dirs_to_scan.append((project, malformed_dir))
        elif config.hub:
            hub_mal = root / ".project" / "malformed"
            if hub_mal.exists() and any(hub_mal.iterdir()):
                dirs_to_scan.append(("hub", hub_mal))
            for name in config.projects:
                mal = root / ".project" / "projects" / name / "malformed"
                if mal.exists() and any(mal.iterdir()):
                    dirs_to_scan.append((name, mal))
        else:
            malformed_dir = root / ".project" / "malformed"
            if malformed_dir.exists():
                dirs_to_scan.append((config.name, malformed_dir))

        for proj_name, mal_dir in dirs_to_scan:
            for path in sorted(mal_dir.glob("*.md")):
                all_files.append((proj_name, path))

        total = len(all_files)
        if total == 0:
            return "no malformed files"

        # Always return the first file — fixing removes it, so next call gets the next one
        proj_name, path = all_files[0]

        entry = {"file": path.name, "project": proj_name}
        try:
            post = frontmatter.load(str(path))
            entry["frontmatter"] = dict(post.metadata)
            entry["body"] = post.content
        except Exception:
            entry["raw_content"] = path.read_text()

        result = {
            "remaining": total,
            "item": entry,
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Fix Malformed File", annotations=ToolAnnotations(title="Fix Malformed File", readOnlyHint=False, destructiveHint=False))
def pm_fix_malformed(
    filename: str,
    id: str,
    title: str,
    item_type: str,
    body: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    points: Optional[int] = None,
    story_id: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Fix a malformed file by rewriting it with valid frontmatter, then restore it.

    Args:
        filename: The malformed filename (e.g. PRJ-1.md)
        id: Correct item ID (e.g. PRJ-1 for story, PRJ-1-1 for task)
        title: Correct title
        item_type: "story" or "task"
        body: New body content (keeps original if not provided)
        status: Status (stories: backlog/ready/active/done; tasks: todo/in-progress/review/done/blocked)
        priority: Priority for stories (must/should/could/wont)
        points: Story points
        story_id: Parent story ID (required for tasks)
        project: Optional project name (hub mode only)
    """
    try:
        import frontmatter as fm
        from datetime import date
        from .models import StoryFrontmatter, TaskFrontmatter

        proj_dir = _resolve_project_dir(project)
        malformed_dir = proj_dir / "malformed"
        source = malformed_dir / filename

        if not source.exists():
            return f"error: {filename} not found in malformed/"

        # Read existing body if not provided
        if body is None:
            try:
                post = fm.load(str(source))
                body = post.content or ""
            except Exception:
                body = source.read_text()

        today = date.today()

        dest_filename = f"{id}.md"

        if item_type == "task":
            if not story_id:
                return "error: story_id is required for tasks"
            meta = TaskFrontmatter(
                id=id,
                story_id=story_id,
                title=title,
                status=status or "todo",
                points=points,
                created=today,
                updated=today,
            )
            dest = proj_dir / "tasks" / dest_filename
        else:
            meta = StoryFrontmatter(
                id=id,
                title=title,
                status=status or "backlog",
                priority=priority or "should",
                points=points,
                tags=[],
                created=today,
                updated=today,
            )
            dest = proj_dir / "stories" / dest_filename

        # Write the fixed file to its correct location with ID-based filename
        post = fm.Post(content=body, **meta.model_dump(mode="json"))
        dest.write_text(fm.dumps(post))
        source.unlink()

        # Clean up empty malformed dir
        if not any(malformed_dir.iterdir()):
            malformed_dir.rmdir()

        store = _store(project)
        write_index(store)
        return _yaml_dump({"fixed": meta.model_dump(mode="json"), "restored_to": str(dest)})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Restore File", annotations=ToolAnnotations(title="Restore File", readOnlyHint=False, destructiveHint=False))
def pm_restore(filename: str, project: Optional[str] = None) -> str:
    """Restore a fixed file from the malformed quarantine back to stories/ or tasks/.

    Args:
        filename: The filename to restore (e.g. PRJ-1.md)
        project: Optional project name (hub mode only)
    """
    try:
        import frontmatter as fm
        from .models import StoryFrontmatter, TaskFrontmatter

        proj_dir = _resolve_project_dir(project)
        malformed_dir = proj_dir / "malformed"
        source = malformed_dir / filename

        if not source.exists():
            return f"error: {filename} not found in malformed/"

        # Validate before restoring
        post = fm.load(str(source))
        stem = source.stem
        parts = stem.split("-")
        is_task = len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()

        if is_task:
            TaskFrontmatter(**post.metadata)
            dest = proj_dir / "tasks" / filename
        else:
            StoryFrontmatter(**post.metadata)
            dest = proj_dir / "stories" / filename

        import shutil
        shutil.move(str(source), str(dest))

        # Clean up empty malformed dir
        if not any(malformed_dir.iterdir()):
            malformed_dir.rmdir()

        store = _store(project)
        write_index(store)
        return f"restored: {filename} → {'tasks' if is_task else 'stories'}/"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Rebuild Index", annotations=ToolAnnotations(title="Rebuild Index", readOnlyHint=False, destructiveHint=False))
def pm_reindex(project: Optional[str] = None) -> str:
    """Rebuild the project index and optionally reindex embeddings.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        write_index(store)

        # Try to reindex embeddings too
        try:
            from .embeddings import EmbeddingStore
            emb = EmbeddingStore(store.project_dir)
            emb.reindex_all(store)
            return "reindexed: index.yaml + embeddings"
        except (ImportError, Exception):
            return "reindexed: index.yaml (embeddings not available)"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Auto-Scope Discovery", annotations=ToolAnnotations(title="Auto-Scope Discovery", readOnlyHint=True))
def pm_auto_scope(
    mode: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> str:
    """Discover what needs scoping — returns codebase signals (full scan) or undecomposed stories (incremental).

    Auto-detects mode: full scan when no epics/stories exist, incremental when stories lack tasks.
    Use with /pm-autoscope skill for automated epic/story/task creation.

    Args:
        mode: Force mode: "full" (codebase scan for new projects) or "incremental" (scope existing stories). Auto-detected if omitted.
        project: Optional project name (hub mode only)
        limit: Max stories per batch in incremental mode (default 5)
        offset: Starting index for pagination in incremental mode (default 0)
    """
    try:
        from .scoper import auto_scope
        store = _store(project)
        return auto_scope(store, mode=mode, limit=limit, offset=offset)
    except Exception as e:
        return f"error: {e}"


# ─── Git Tools ───────────────────────────────────────────────────

@mcp.tool(title="Git Status Dashboard", annotations=ToolAnnotations(title="Git Status Dashboard", readOnlyHint=True))
def pm_git_status(project: Optional[str] = None) -> str:
    """Show git status across all hub submodules — branch, dirty, ahead/behind, PRs.

    Returns the structured list from git_status_all() including PR data.
    Use this as the first thing to check before any coordinated operation.

    Args:
        project: Optional project name to check a single subproject instead of all
    """
    try:
        from .hub.registry import git_status_all

        root = find_project_root()
        data = git_status_all(root=root)

        if project:
            # Filter to a single project
            matched = [p for p in data.get("projects", []) if p["name"] == project]
            if not matched:
                return f"error: project '{project}' not found in hub status"
            return _yaml_dump({
                "projects": matched,
                "total": 1,
                "issues": 1 if matched[0].get("issues") else 0,
                "ok": not matched[0].get("issues"),
                "summary": f"Status for {project}",
            })

        return _yaml_dump(data)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Commit PM Changes", annotations=ToolAnnotations(title="Commit PM Changes", readOnlyHint=False, destructiveHint=False))
def pm_commit(
    scope: str = "all",
    message: Optional[str] = None,
) -> str:
    """Commit .project/ changes with an auto-generated message.

    Stages changes under .project/ filtered by scope and commits them.
    If no message is provided, one is generated from the changed files
    (e.g. "pm: update US-PRJ-5, US-PRJ-3-1").

    Args:
        scope: Commit scope — "hub" (hub-level only, excludes subprojects), "project:<name>" (specific subproject), or "all" (everything under .project/)
        message: Optional commit message (auto-generated if omitted)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        if config.hub:
            from .hub.registry import pm_commit as _hub_commit
            result = _hub_commit(scope=scope, message=message, root=root)
        else:
            # Non-hub: scope is ignored (single project)
            store = Store(root)
            result = store.commit_project_changes(message=message)
            # Normalize key name to match hub format
            if "files_changed" in result:
                result["files_committed"] = result.pop("files_changed")

        if isinstance(result, dict) and result.get("nothing_to_commit"):
            return "error: No .project/ changes to commit"
        return _yaml_dump({"committed": result})
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        return f"error: {e}"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Push PM Changes", annotations=ToolAnnotations(title="Push PM Changes", readOnlyHint=False, destructiveHint=False))
def pm_push(
    scope: str = "hub",
) -> str:
    """Push committed .project/ changes to the remote.

    Validates branch alignment before pushing.  In hub mode, uses
    scope-aware routing with auto-rebase on conflict.

    Args:
        scope: Push scope — "hub" (hub repo on main), "project:<name>" (specific subproject), or "all" (coordinated push)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        if config.hub:
            from .hub.registry import pm_push as _hub_push
            result = _hub_push(scope=scope, root=root)
            return _yaml_dump({"pushed": result})
        else:
            # Non-hub: push normally
            store = Store(root)
            result = store.push_project_changes()
            return _yaml_dump({"pushed": result})
    except RuntimeError as e:
        return f"error: {e}"
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Coordinated Push All", annotations=ToolAnnotations(title="Coordinated Push All", readOnlyHint=False, destructiveHint=False))
def pm_push_all(
    dry_run: bool = False,
    projects: Optional[str] = None,
) -> str:
    """Coordinated push: preflight, push subprojects, then push hub.

    Discovers dirty projects automatically (or uses explicit list),
    runs preflight validation, pushes subprojects in order, then pushes
    the hub with auto-rebase.

    Args:
        dry_run: If True, show what would be pushed without executing
        projects: Optional comma-separated project names (e.g. "api,web"). Omit to auto-discover dirty projects.
    """
    try:
        from .hub.registry import coordinated_push
        root = find_project_root()

        project_list = (
            [p.strip() for p in projects.split(",") if p.strip()]
            if projects
            else None
        )

        result = coordinated_push(
            projects=project_list,
            dry_run=dry_run,
            root=root,
        )
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


# ─── Changeset Tools ────────────────────────────────────────────

@mcp.tool(title="Create Changeset", annotations=ToolAnnotations(title="Create Changeset", readOnlyHint=False, destructiveHint=False))
def pm_changeset_create(
    title: str,
    projects: str,
    description: str = "",
    project: Optional[str] = None,
) -> str:
    """Create a changeset grouping related changes across multiple projects.

    Args:
        title: Changeset name (e.g. "add-auth")
        projects: Comma-separated project names (e.g. "api,web,worker")
        description: Optional description of the changeset
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        project_list = [p.strip() for p in projects.split(",") if p.strip()]
        if not project_list:
            return "error: at least one project is required"
        meta = store.create_changeset(title, project_list, description)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Changeset Status", annotations=ToolAnnotations(title="Changeset Status", readOnlyHint=True))
def pm_changeset_status(
    changeset_id: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Get changeset status — one changeset by ID, or list all open changesets.

    Args:
        changeset_id: Optional changeset ID (e.g. CS-PRJ-1). Omit to list all.
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        if changeset_id:
            meta, body = store.get_changeset(changeset_id)
            result = meta.model_dump(mode="json")
            result["body"] = body
            return _yaml_dump(result)
        else:
            changesets = store.list_changesets()
            return _yaml_dump({
                "changesets": [cs.model_dump(mode="json") for cs in changesets],
                "count": len(changesets),
            })
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Add Project to Changeset", annotations=ToolAnnotations(title="Add Project to Changeset", readOnlyHint=False, destructiveHint=False))
def pm_changeset_add_project(
    changeset_id: str,
    name: str,
    ref: str = "",
    project: Optional[str] = None,
) -> str:
    """Add a project entry to an existing changeset.

    Args:
        changeset_id: Changeset ID (e.g. CS-PRJ-1)
        name: Project name to add
        ref: Optional git ref/branch for this project
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        meta = store.add_changeset_entry(changeset_id, name, ref=ref)
        return _yaml_dump({"updated": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Changeset Create PRs", annotations=ToolAnnotations(title="Changeset Create PRs", readOnlyHint=True))
def pm_changeset_create_prs(
    changeset_id: str,
    project: Optional[str] = None,
) -> str:
    """Generate PR creation commands for all projects in a changeset.

    Returns the gh CLI commands to create cross-referenced PRs for each project
    in the changeset. Does not execute them — the caller should review and run.

    Args:
        changeset_id: Changeset ID (e.g. CS-PRJ-1)
        project: Optional project name (hub mode only)
    """
    try:
        from .changesets import changeset_create_prs

        store = _store(project)
        result = changeset_create_prs(store, changeset_id)
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Changeset Push", annotations=ToolAnnotations(title="Changeset Push", readOnlyHint=False, destructiveHint=False))
def pm_changeset_push(
    changeset_id: str,
    project: Optional[str] = None,
) -> str:
    """Mark a changeset as merged and report status for hub ref updates.

    Checks all entries — if all are merged, marks the changeset as merged.
    If some are still pending, marks as partial and reports what's outstanding.

    Args:
        changeset_id: Changeset ID (e.g. CS-PRJ-1)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        meta, body = store.get_changeset(changeset_id)

        from datetime import date as _date

        merged = [e for e in meta.entries if e.status == "merged"]
        pending = [e for e in meta.entries if e.status != "merged"]

        if not pending:
            # All merged — update changeset status
            meta.status = ChangesetStatus.merged
            meta.updated = _date.today()
            post = frontmatter.Post(
                content=body,
                **meta.model_dump(mode="json"),
            )
            store._changeset_path(changeset_id).write_text(
                frontmatter.dumps(post)
            )
            return _yaml_dump({
                "changeset": meta.id,
                "status": "merged",
                "message": "All PRs merged — safe to update hub submodule refs.",
                "projects": [e.project for e in meta.entries],
            })
        else:
            # Partial — update status
            if merged:
                meta.status = ChangesetStatus.partial
                meta.updated = _date.today()
                post = frontmatter.Post(
                    content=body,
                    **meta.model_dump(mode="json"),
                )
                store._changeset_path(changeset_id).write_text(
                    frontmatter.dumps(post)
                )

            return _yaml_dump({
                "changeset": meta.id,
                "status": "partial",
                "merged": [e.project for e in merged],
                "pending": [{"project": e.project, "ref": e.ref, "status": e.status} for e in pending],
                "message": "Not all PRs merged — do NOT update hub refs yet.",
            })
    except Exception as e:
        return f"error: {e}"


# ─── Web Server Tools ───────────────────────────────────────────

import subprocess
import socket

_web_process: Optional[subprocess.Popen] = None
_web_host: Optional[str] = None
_web_port: Optional[int] = None


def _port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


@mcp.tool(title="Start Web UI", annotations=ToolAnnotations(title="Start Web UI", readOnlyHint=False, destructiveHint=False))
def pm_web_start(host: str = "127.0.0.1", port: int = 8000) -> str:
    """Start the ProjectMan web dashboard as a background server.

    Returns the URL on success, or an error if the port is in use (try a different port).

    Args:
        host: Host/IP to bind to (default 127.0.0.1, use 0.0.0.0 for all interfaces)
        port: Port to listen on (default 8000, try another if this is taken)
    """
    global _web_process, _web_host, _web_port

    # Already running?
    if _web_process is not None and _web_process.poll() is None:
        return _yaml_dump({
            "status": "already_running",
            "url": f"http://{_web_host}:{_web_port}",
            "pid": _web_process.pid,
        })

    # Check port availability
    if not _port_available(host, port):
        return _yaml_dump({
            "status": "error",
            "error": f"Port {port} is already in use",
            "suggestion": f"Try port {port + 1} or another available port",
        })

    # Check web dependencies
    try:
        import uvicorn  # noqa: F401
        import fastapi  # noqa: F401
    except ImportError:
        return _yaml_dump({
            "status": "error",
            "error": "Web dependencies not installed. Install with: pip install projectman[web]",
        })

    # Find project root for the working directory
    try:
        root = find_project_root()
    except Exception as e:
        return _yaml_dump({"status": "error", "error": f"No project found: {e}"})

    # Start uvicorn as a subprocess
    try:
        import sys
        _web_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "projectman.web.app:app",
             "--host", host, "--port", str(port)],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _web_host = host
        _web_port = port

        return _yaml_dump({
            "status": "started",
            "url": f"http://{host}:{port}",
            "pid": _web_process.pid,
        })
    except Exception as e:
        _web_process = None
        return _yaml_dump({"status": "error", "error": str(e)})


@mcp.tool(title="Stop Web UI", annotations=ToolAnnotations(title="Stop Web UI", readOnlyHint=False, destructiveHint=False))
def pm_web_stop() -> str:
    """Stop the running ProjectMan web server."""
    global _web_process, _web_host, _web_port

    if _web_process is None or _web_process.poll() is not None:
        _web_process = None
        _web_host = None
        _web_port = None
        return _yaml_dump({"status": "not_running"})

    pid = _web_process.pid
    try:
        _web_process.terminate()
        try:
            _web_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _web_process.kill()
            _web_process.wait(timeout=3)
    except Exception as e:
        return _yaml_dump({"status": "error", "error": str(e)})
    finally:
        _web_process = None
        _web_host = None
        _web_port = None

    return _yaml_dump({"status": "stopped", "pid": pid})


@mcp.tool(title="Web UI Status", annotations=ToolAnnotations(title="Web UI Status", readOnlyHint=True))
def pm_web_status() -> str:
    """Check if the ProjectMan web server is running and on what host/port."""
    global _web_process, _web_host, _web_port

    if _web_process is None:
        return _yaml_dump({"running": False})

    if _web_process.poll() is not None:
        # Process exited
        exit_code = _web_process.returncode
        _web_process = None
        _web_host = None
        _web_port = None
        return _yaml_dump({"running": False, "exited_with": exit_code})

    return _yaml_dump({
        "running": True,
        "url": f"http://{_web_host}:{_web_port}",
        "pid": _web_process.pid,
        "host": _web_host,
        "port": _web_port,
    })


# ─── Activity Log ───────────────────────────────────────────────


@mcp.tool(title="Activity Log", annotations=ToolAnnotations(title="Activity Log", readOnlyHint=True))
def pm_activity(
    item_id: Optional[str] = None,
    event_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    project: Optional[str] = None,
) -> str:
    """Query the activity log for project mutations.

    Args:
        item_id: Filter by item ID (e.g. US-PRJ-1)
        event_type: Filter by event type: create, update, delete, archive
        from_date: Filter from date (ISO 8601, e.g. 2026-01-01)
        to_date: Filter to date (ISO 8601, e.g. 2026-12-31)
        actor: Filter by actor name
        limit: Max entries to return (default 20)
        offset: Starting index for pagination (default 0)
        project: Optional project name (hub mode only)
    """
    import json
    from datetime import datetime

    try:
        pm_dir = _resolve_project_dir(project)
        log_path = pm_dir / "activity.jsonl"

        if not log_path.exists():
            return _yaml_dump({"entries": [], "total": 0, "message": "No activity log found"})

        # Parse all entries
        entries = []
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # Apply filters
        if item_id:
            entries = [e for e in entries if e.get("item_id") == item_id]
        if event_type:
            entries = [e for e in entries if e.get("event_type") == event_type]
        if actor:
            entries = [e for e in entries if e.get("actor") == actor]
        if from_date:
            from_dt = datetime.fromisoformat(from_date)
            entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= from_dt]
        if to_date:
            to_dt = datetime.fromisoformat(to_date)
            entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) <= to_dt]

        total = len(entries)

        # Most recent first, then paginate
        entries = list(reversed(entries))
        entries = entries[offset : offset + limit]

        # Format human-readable output
        formatted = []
        for e in entries:
            ts = e.get("timestamp", "?")
            line_parts = [
                f"[{ts}]",
                e.get("event_type", "?").upper(),
                e.get("item_type", "?"),
                e.get("item_id", "?"),
            ]
            if e.get("actor"):
                line_parts.append(f"by {e['actor']}")
            changes = e.get("changes", {})
            if changes:
                change_strs = []
                for field, val in changes.items():
                    if isinstance(val, dict) and "before" in val and "after" in val:
                        change_strs.append(f"{field}: {val['before']} → {val['after']}")
                    else:
                        change_strs.append(f"{field}: {val}")
                if change_strs:
                    line_parts.append(f"({', '.join(change_strs)})")
            formatted.append(" ".join(line_parts))

        result = {
            "total": total,
            "showing": f"{offset + 1}-{offset + len(entries)} of {total}" if entries else "0 of 0",
            "entries": formatted,
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Run Log", annotations=ToolAnnotations(title="Run Log", readOnlyHint=True))
def pm_run_log(
    id: str,
    limit: int = 20,
    offset: int = 0,
    project: Optional[str] = None,
) -> str:
    """Read the run log for an epic, story, or task. Returns a JSON array of log entries
    showing previous work attempts, outcomes, and notes.

    Args:
        id: Epic, story, or task ID
        limit: Max entries to return (default 20, most recent first)
        offset: Number of entries to skip
        project: Optional project name (hub mode only)
    """
    try:
        import json

        store = _store(project)
        entries = store.get_run_log(id, limit=limit, offset=offset)
        result = [e.model_dump(mode="json") for e in entries]
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"error: {e}"


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 22001) -> None:
    """Run the MCP server with the specified transport.

    Args:
        transport: "stdio" or "sse"
        host: Host to bind to (SSE mode only)
        port: Port to bind to (SSE mode only)
    """
    if transport == "sse":
        mcp.settings.host = host
        mcp.settings.port = port
    mcp.run(transport=transport)
