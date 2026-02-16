"""JSON API endpoints (/api/*)."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from projectman.config import find_project_root, load_config
from projectman.indexer import build_index, write_index
from projectman.store import Store
from projectman.web.schemas import (
    CreateEpicRequest,
    CreateStoryRequest,
    CreateTaskRequest,
    GrabTaskRequest,
    UpdateDocRequest,
    UpdateItemRequest,
)

router = APIRouter(prefix="/api")


# ─── Dependencies ────────────────────────────────────────────────


def get_root() -> Path:
    """Return the project root directory (always the hub/repo root)."""
    return find_project_root()


def get_project_dir(project: Optional[str] = Query(None)) -> Path:
    """Return the .project/ data directory, routing to hub subprojects when needed."""
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            proj_dir = root / ".project" / "projects" / project
            if proj_dir.exists() and (proj_dir / "config.yaml").exists():
                return proj_dir
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found in hub")
    return root / ".project"


def get_store(project: Optional[str] = Query(None)) -> Store:
    """Provide a Store instance, routing hub subprojects to .project/projects/{name}/."""
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            project_dir = root / ".project" / "projects" / project
            if project_dir.exists() and (project_dir / "config.yaml").exists():
                return Store(root, project_dir=project_dir)
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found in hub")
    return Store(root)


# ─── Project ─────────────────────────────────────────────────────


@router.get("/status")
def api_status(store: Store = Depends(get_store)) -> dict:
    """Project status summary: counts, points, completion."""
    index = build_index(store)
    pct = 0
    if index.total_points > 0:
        pct = round(index.completed_points / index.total_points * 100)

    status_groups: dict[str, int] = {}
    for entry in index.entries:
        status_groups[entry.status] = status_groups.get(entry.status, 0) + 1

    return {
        "project": store.config.name,
        "epics": index.epic_count,
        "stories": index.story_count,
        "tasks": index.task_count,
        "total_points": index.total_points,
        "completed_points": index.completed_points,
        "completion": f"{pct}%",
        "by_status": status_groups,
    }


@router.get("/config")
def api_config(root: Path = Depends(get_root)) -> dict:
    """Project configuration."""
    config = load_config(root)
    return config.model_dump(mode="json")


# ─── Epics ───────────────────────────────────────────────────────


@router.get("/epics")
def list_epics(
    status: Optional[str] = None,
    store: Store = Depends(get_store),
) -> list[dict]:
    """List all epics, optionally filtered by status."""
    epics = store.list_epics(status=status)
    return [e.model_dump(mode="json") for e in epics]


@router.post("/epics", status_code=201)
def create_epic(body: CreateEpicRequest, store: Store = Depends(get_store)) -> dict:
    """Create a new epic."""
    meta = store.create_epic(
        title=body.title,
        description=body.description,
        priority=body.priority,
        target_date=body.target_date,
        tags=body.tags,
    )
    write_index(store)
    return meta.model_dump(mode="json")


@router.get("/epics/{epic_id}")
def get_epic(epic_id: str, store: Store = Depends(get_store)) -> dict:
    """Get epic detail with linked stories and rollup."""
    try:
        meta, body = store.get_epic(epic_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Epic not found: {epic_id}")

    linked_stories = [s for s in store.list_stories() if s.epic_id == epic_id]
    story_data = []
    total_points = 0
    completed_points = 0

    for story in linked_stories:
        tasks = store.list_tasks(story_id=story.id)
        task_points = sum(t.points or 0 for t in tasks)
        done_points = sum(t.points or 0 for t in tasks if t.status.value == "done")
        total_points += task_points
        completed_points += done_points
        story_data.append({
            "id": story.id,
            "title": story.title,
            "status": story.status.value,
            "points": story.points,
            "task_points": task_points,
            "done_points": done_points,
        })

    pct = round(completed_points / max(total_points, 1) * 100)
    return {
        "epic": meta.model_dump(mode="json"),
        "body": body,
        "stories": story_data,
        "rollup": {
            "story_count": len(linked_stories),
            "total_points": total_points,
            "completed_points": completed_points,
            "completion": f"{pct}%",
        },
    }


@router.patch("/epics/{epic_id}")
def update_epic(
    epic_id: str,
    body: UpdateItemRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Update epic fields."""
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(epic_id, **kwargs)
        write_index(store)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Epic not found: {epic_id}")


@router.delete("/epics/{epic_id}")
def archive_epic(epic_id: str, store: Store = Depends(get_store)) -> dict:
    """Archive an epic."""
    try:
        store.archive(epic_id)
        write_index(store)
        return {"archived": epic_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Epic not found: {epic_id}")


# ─── Stories ─────────────────────────────────────────────────────


@router.get("/stories")
def list_stories(
    status: Optional[str] = None,
    store: Store = Depends(get_store),
) -> list[dict]:
    """List all stories, optionally filtered by status."""
    stories = store.list_stories(status=status)
    return [s.model_dump(mode="json") for s in stories]


@router.post("/stories", status_code=201)
def create_story(body: CreateStoryRequest, store: Store = Depends(get_store)) -> dict:
    """Create a new story."""
    meta, test_tasks = store.create_story(
        title=body.title,
        description=body.description,
        priority=body.priority,
        points=body.points,
        acceptance_criteria=body.acceptance_criteria,
    )
    if body.epic_id:
        store.update(meta.id, epic_id=body.epic_id)
        meta, _ = store.get_story(meta.id)
    write_index(store)
    result = meta.model_dump(mode="json")
    if test_tasks:
        result["test_tasks"] = [t.model_dump(mode="json") for t in test_tasks]
    return result


@router.get("/stories/{story_id}")
def get_story(story_id: str, store: Store = Depends(get_store)) -> dict:
    """Get story detail with body and child tasks."""
    try:
        meta, body = store.get_story(story_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    tasks = store.list_tasks(story_id=story_id)
    return {
        **meta.model_dump(mode="json"),
        "body": body,
        "tasks": [t.model_dump(mode="json") for t in tasks],
    }


@router.patch("/stories/{story_id}")
def update_story(
    story_id: str,
    body: UpdateItemRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Update story fields."""
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(story_id, **kwargs)
        write_index(store)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")


@router.delete("/stories/{story_id}")
def archive_story(story_id: str, store: Store = Depends(get_store)) -> dict:
    """Archive a story."""
    try:
        store.archive(story_id)
        write_index(store)
        return {"archived": story_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")


# ─── Tasks ───────────────────────────────────────────────────────


@router.get("/tasks")
def list_tasks(
    story_id: Optional[str] = None,
    status: Optional[str] = None,
    store: Store = Depends(get_store),
) -> list[dict]:
    """List tasks, optionally filtered by story_id and/or status."""
    tasks = store.list_tasks(story_id=story_id, status=status)
    return [t.model_dump(mode="json") for t in tasks]


@router.post("/tasks", status_code=201)
def create_task(body: CreateTaskRequest, store: Store = Depends(get_store)) -> dict:
    """Create a new task under a story."""
    try:
        meta = store.create_task(
            story_id=body.story_id,
            title=body.title,
            description=body.description,
            points=body.points,
        )
        write_index(store)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Story not found: {body.story_id}")


@router.get("/tasks/{task_id}")
def get_task(task_id: str, store: Store = Depends(get_store)) -> dict:
    """Get task detail with body."""
    try:
        meta, body = store.get_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {**meta.model_dump(mode="json"), "body": body}


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: UpdateItemRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Update task fields."""
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(task_id, **kwargs)
        write_index(store)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")


@router.post("/tasks/{task_id}/grab")
def grab_task(
    task_id: str,
    body: GrabTaskRequest = GrabTaskRequest(),
    store: Store = Depends(get_store),
) -> dict:
    """Claim a task — validates readiness, assigns, sets in-progress."""
    from projectman.readiness import check_readiness

    try:
        task_meta, task_body = store.get_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    readiness = check_readiness(task_meta, task_body, store)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=409,
            detail={"error": "task is not ready", "blockers": readiness["blockers"]},
        )

    store.update(task_id, assignee=body.assignee, status="in-progress")
    write_index(store)
    task_meta, task_body = store.get_task(task_id)

    story_context = {}
    try:
        story_meta, story_body = store.get_story(task_meta.story_id)
        story_context = {
            "id": story_meta.id,
            "title": story_meta.title,
            "status": story_meta.status.value,
        }
    except FileNotFoundError:
        story_context = {"id": task_meta.story_id, "error": "not found"}

    return {
        "task": task_meta.model_dump(mode="json"),
        "body": task_body,
        "story_context": story_context,
    }


@router.delete("/tasks/{task_id}")
def archive_task(task_id: str, store: Store = Depends(get_store)) -> dict:
    """Archive a task."""
    try:
        store.archive(task_id)
        write_index(store)
        return {"archived": task_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")


# ─── Board & Intelligence ────────────────────────────────────────


@router.get("/board")
def api_board(
    assignee: Optional[str] = None,
    store: Store = Depends(get_store),
) -> dict:
    """Task board grouped by status columns with readiness indicators."""
    from projectman.readiness import check_readiness, compute_hints

    all_tasks = store.list_tasks()
    story_cache = {s.id: s for s in store.list_stories()}

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

        entry = {
            "id": task.id,
            "title": task.title,
            "points": task.points,
            "assignee": task.assignee,
            "story": story_label,
        }

        if task.status.value == "in-progress":
            in_progress.append(entry)
        elif task.status.value == "review":
            in_review.append(entry)
        elif task.status.value == "blocked":
            blocked.append(entry)
        elif task.status.value == "todo" and not assignee:
            readiness = check_readiness(task, task_body, store)
            if readiness["ready"]:
                priority_order = {"must": 0, "should": 1, "could": 2, "wont": 3}
                sort_key = (
                    priority_order.get(story.priority.value if story else "should", 1),
                    task.story_id,
                    task.id,
                )
                available.append({**entry, "_sort": sort_key})
            else:
                not_ready.append({**entry, "blockers": readiness["blockers"]})

    available.sort(key=lambda t: t["_sort"])
    for t in available:
        del t["_sort"]

    return {
        "board": {
            "available": available,
            "not_ready": not_ready,
            "in_progress": in_progress,
            "in_review": in_review,
            "blocked": blocked,
        },
        "summary": {
            "available": len(available),
            "not_ready": len(not_ready),
            "in_progress": len(in_progress),
            "in_review": len(in_review),
            "blocked": len(blocked),
        },
    }


@router.get("/burndown")
def api_burndown(store: Store = Depends(get_store)) -> dict:
    """Burndown data: total vs completed points."""
    index = build_index(store)
    remaining = index.total_points - index.completed_points
    return {
        "project": store.config.name,
        "total_points": index.total_points,
        "completed_points": index.completed_points,
        "remaining_points": remaining,
        "completion": f"{round(index.completed_points / max(index.total_points, 1) * 100)}%",
    }


@router.get("/audit")
def api_audit(root: Path = Depends(get_root)) -> dict:
    """Run project audit and return findings."""
    from projectman.audit import run_audit

    import yaml
    result_str = run_audit(root)
    # run_audit returns YAML string; parse it back to dict
    try:
        return yaml.safe_load(result_str) or {}
    except Exception:
        return {"raw": result_str}


@router.get("/search")
def api_search(
    q: str = Query(..., min_length=1),
    proj_dir: Path = Depends(get_project_dir),
) -> list[dict]:
    """Search stories and tasks by keyword."""
    try:
        from projectman.embeddings import EmbeddingStore
        emb_store = EmbeddingStore(proj_dir)
        results = emb_store.search(q, top_k=10)
        if results:
            return [{"id": r.id, "title": r.title, "type": r.type, "score": round(r.score, 3)} for r in results]
    except (ImportError, Exception):
        pass

    from projectman.search import keyword_search
    results = keyword_search(q, proj_dir)
    return [{"id": r.id, "title": r.title, "type": r.type, "score": r.score, "snippet": r.snippet} for r in results]


# ─── Documentation ───────────────────────────────────────────────

_DOC_MAP = {
    "project": "PROJECT.md",
    "infrastructure": "INFRASTRUCTURE.md",
    "security": "SECURITY.md",
    "vision": "VISION.md",
    "architecture": "ARCHITECTURE.md",
    "decisions": "DECISIONS.md",
}


@router.get("/docs")
def list_docs(proj_dir: Path = Depends(get_project_dir)) -> dict:
    """Summary of all project docs with staleness indicators."""
    import os
    from datetime import date as _date

    summary = {}
    for key, filename in _DOC_MAP.items():
        path = proj_dir / filename
        if path.exists():
            mtime = _date.fromtimestamp(os.path.getmtime(path))
            age = (_date.today() - mtime).days
            content = path.read_text()
            lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("<!--")]
            summary[key] = {
                "file": filename,
                "last_modified": str(mtime),
                "age_days": age,
                "content_lines": len(lines),
                "status": "stale" if age > 30 else "current",
            }
        else:
            summary[key] = {"file": filename, "status": "missing"}
    return summary


@router.get("/docs/{name}")
def get_doc(name: str, proj_dir: Path = Depends(get_project_dir)) -> dict:
    """Get full content of a specific project doc."""
    filename = _DOC_MAP.get(name.lower())
    if not filename:
        raise HTTPException(status_code=404, detail=f"Unknown doc: {name}. Use: {', '.join(_DOC_MAP)}")
    path = proj_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    return {"name": name, "file": filename, "content": path.read_text()}


@router.put("/docs/{name}")
def update_doc(
    name: str,
    body: UpdateDocRequest,
    proj_dir: Path = Depends(get_project_dir),
) -> dict:
    """Update a project doc's content."""
    filename = _DOC_MAP.get(name.lower())
    if not filename:
        raise HTTPException(status_code=404, detail=f"Unknown doc: {name}. Use: {', '.join(_DOC_MAP)}")
    path = proj_dir / filename
    path.write_text(body.content)
    return {"updated": filename}
