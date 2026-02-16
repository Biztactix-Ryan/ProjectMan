"""ProjectMan MCP server — FastMCP-based with stdio transport."""

from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import find_project_root, load_config
from .indexer import build_index, write_index
from .models import ProjectIndex
from .store import Store

mcp = FastMCP("projectman")


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


def _store(project: Optional[str] = None) -> Store:
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            project_dir = root / ".project" / "projects" / project
            if project_dir.exists() and (project_dir / "config.yaml").exists():
                return Store(root, project_dir=project_dir)
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    return Store(root)


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

        result = {
            "project": store.config.name,
            "epics": index.epic_count,
            "stories": index.story_count,
            "tasks": index.task_count,
            "total_points": index.total_points,
            "completed_points": index.completed_points,
            "completion": f"{pct}%",
            "by_status": {k: len(v) for k, v in status_groups.items()},
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
        return _yaml_dump(result)
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
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List active/in-progress stories and tasks.

    Args:
        project: Optional project name (hub mode only)
        limit: Max items per list (default 20)
        offset: Starting index for pagination (default 0)
    """
    try:
        store = _store(project)
        all_stories = store.list_stories(status="active")
        all_tasks = store.list_tasks(status="in-progress")

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
def pm_search(query: str, project: Optional[str] = None) -> str:
    """Search stories and tasks by keyword or semantic similarity.

    Args:
        query: Search query string
        project: Optional project name (hub mode only)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        # Try embeddings first, fall back to keyword
        try:
            from .embeddings import EmbeddingStore
            emb_store = EmbeddingStore(proj_dir)
            results = emb_store.search(query, top_k=10)
            if results:
                return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": round(r.score, 3)} for r in results])
        except (ImportError, Exception):
            pass

        from .search import keyword_search
        results = keyword_search(query, proj_dir)
        return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": r.score, "snippet": r.snippet} for r in results])
    except Exception as e:
        return f"error: {e}"


@mcp.tool(title="Task Board", annotations=ToolAnnotations(title="Task Board", readOnlyHint=True))
def pm_board(
    project: Optional[str] = None,
    assignee: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Show the task board — available tasks grouped by status and readiness.

    Args:
        project: Optional project name (hub mode only)
        assignee: Filter to show only tasks for this assignee
        limit: Max items per board group (default 10). Totals are always shown.
    """
    try:
        from .readiness import check_readiness, compute_hints

        store = _store(project)
        all_tasks = store.list_tasks()

        # Build a story lookup for priority ordering and context
        story_cache = {}
        for story in store.list_stories():
            story_cache[story.id] = story

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
                        "_sort": (story_priority, task.story_id, task.id, task.points or 99),
                    })
                else:
                    not_ready.append({
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "story": story_label,
                        "blockers": readiness["blockers"],
                    })

        # Sort available tasks by priority > story > task sequence > points
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
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        ac_list = [c.strip() for c in acceptance_criteria.split(",")] if acceptance_criteria else None
        meta, test_tasks = store.create_story(title, description, priority, points, acceptance_criteria=ac_list)
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
    project: Optional[str] = None,
) -> str:
    """Create a new task under a story.

    Args:
        story_id: Parent story ID (e.g. US-PRJ-1)
        title: Task title
        description: Task description with implementation details
        points: Task points (fibonacci: 1,2,3,5,8,13)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        meta = store.create_task(story_id, title, description, points)
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
        tasks: List of task dicts, each with keys: title (str), description (str), points (int, optional)
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
        sibling_list = [
            {"id": s.id, "title": s.title, "status": s.status.value, "assignee": s.assignee}
            for s in all_siblings[:20]
        ]

        result = {
            "grabbed": {
                "task": task_meta.model_dump(mode="json"),
                "body": task_body,
                "story_context": story_context,
                "sibling_tasks": sibling_list,
                "sibling_tasks_total": len(all_siblings),
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
