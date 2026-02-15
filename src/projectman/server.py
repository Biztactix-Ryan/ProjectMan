"""ProjectMan MCP server — FastMCP-based with stdio transport."""

from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP

from .config import find_project_root, load_config
from .indexer import build_index, write_index
from .models import ProjectIndex
from .store import Store

mcp = FastMCP("projectman")


def _resolve_root(project: Optional[str] = None) -> Path:
    """Resolve project root, handling hub mode project names."""
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            sub_root = root / "projects" / project
            if sub_root.exists() and (sub_root / ".project").exists():
                return sub_root
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    return root


def _store(project: Optional[str] = None) -> Store:
    return Store(_resolve_root(project))


def _yaml_dump(data) -> str:
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


# ─── Query Tools ────────────────────────────────────────────────

@mcp.tool()
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


@mcp.tool()
def pm_get(id: str) -> str:
    """Get full details of a story or task by ID.

    Args:
        id: Story ID (e.g. PRJ-1) or task ID (e.g. PRJ-1-1)
    """
    try:
        store = _store()
        meta, body = store.get(id)
        result = meta.model_dump(mode="json")
        result["body"] = body
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_active(project: Optional[str] = None) -> str:
    """List active/in-progress stories and tasks.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        active_stories = store.list_stories(status="active")
        active_tasks = store.list_tasks(status="in-progress")

        result = {
            "active_stories": [s.model_dump(mode="json") for s in active_stories],
            "active_tasks": [t.model_dump(mode="json") for t in active_tasks],
        }
        return _yaml_dump(result)
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_search(query: str, project: Optional[str] = None) -> str:
    """Search stories and tasks by keyword or semantic similarity.

    Args:
        query: Search query string
        project: Optional project name (hub mode only)
    """
    try:
        root = _resolve_root(project)
        proj_dir = root / ".project"

        # Try embeddings first, fall back to keyword
        try:
            from .embeddings import EmbeddingStore
            emb_store = EmbeddingStore(proj_dir)
            results = emb_store.search(query, top_k=10)
            return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": round(r.score, 3)} for r in results])
        except (ImportError, Exception):
            pass

        from .search import keyword_search
        results = keyword_search(query, proj_dir)
        return _yaml_dump([{"id": r.id, "title": r.title, "type": r.type, "score": r.score, "snippet": r.snippet} for r in results])
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_burndown(project: Optional[str] = None) -> str:
    """Get burndown data: total vs completed points.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        root = _resolve_root(project)
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

@mcp.tool()
def pm_create_story(
    title: str,
    description: str,
    priority: Optional[str] = None,
    points: Optional[int] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new user story.

    Args:
        title: Story title
        description: Story description ("As a [user], I want [goal] so that [benefit]")
        priority: Priority level: must, should, could, wont
        points: Story points (fibonacci: 1,2,3,5,8,13)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        meta = store.create_story(title, description, priority, points)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_create_task(
    story_id: str,
    title: str,
    description: str,
    points: Optional[int] = None,
) -> str:
    """Create a new task under a story.

    Args:
        story_id: Parent story ID (e.g. PRJ-1)
        title: Task title
        description: Task description with implementation details
        points: Task points (fibonacci: 1,2,3,5,8,13)
    """
    try:
        store = _store()
        meta = store.create_task(story_id, title, description, points)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_update(
    id: str,
    status: Optional[str] = None,
    points: Optional[int] = None,
    title: Optional[str] = None,
    assignee: Optional[str] = None,
) -> str:
    """Update a story or task.

    Args:
        id: Story or task ID
        status: New status (stories: backlog/ready/active/done/archived; tasks: todo/in-progress/review/done/blocked)
        points: New point estimate (fibonacci: 1,2,3,5,8,13)
        title: New title
        assignee: Assignee name (tasks only)
    """
    try:
        store = _store()
        kwargs = {}
        if status is not None:
            kwargs["status"] = status
        if points is not None:
            kwargs["points"] = points
        if title is not None:
            kwargs["title"] = title
        if assignee is not None:
            kwargs["assignee"] = assignee

        meta = store.update(id, **kwargs)
        write_index(store)
        return _yaml_dump({"updated": meta.model_dump(mode="json")})
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_archive(id: str) -> str:
    """Archive a story or task.

    Args:
        id: Story or task ID to archive
    """
    try:
        store = _store()
        store.archive(id)
        write_index(store)
        return f"archived: {id}"
    except Exception as e:
        return f"error: {e}"


# ─── Intelligence Tools ─────────────────────────────────────────

@mcp.tool()
def pm_estimate(id: str) -> str:
    """Get estimation context for a story or task — returns content + calibration guidelines.

    Args:
        id: Story or task ID to estimate
    """
    try:
        from .estimator import estimate
        store = _store()
        return estimate(store, id)
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_scope(id: str) -> str:
    """Get scoping context for a story — returns story + existing tasks + decomposition guidance.

    Args:
        id: Story ID to scope into tasks
    """
    try:
        from .scoper import scope
        store = _store()
        return scope(store, id)
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_audit(project: Optional[str] = None) -> str:
    """Run project audit — checks for drift, inconsistencies, stale items.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        from .audit import run_audit
        root = _resolve_root(project)
        return run_audit(root)
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
def pm_repair() -> str:
    """Scan the hub for unregistered projects, initialize missing .project/ dirs,
    rebuild all indexes and embeddings, and regenerate dashboards.
    Hub mode only. Writes a REPAIR.md report."""
    try:
        config = load_config(find_project_root())
        if not config.hub:
            return "error: not a hub project"
        from .hub.registry import repair
        return repair()
    except Exception as e:
        return f"error: {e}"


@mcp.tool()
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
