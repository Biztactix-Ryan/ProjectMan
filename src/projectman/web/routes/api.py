"""JSON API endpoints (/api/*).

Every route acts on the one store this app serves — ``{root}/.project``,
found from the project root the app started in (US-PM-45).  No route takes a
project or routing argument of any kind: a route with an item ID checks the
ID's shape and reads that store, and an ID-less route reads the same one.  An
ID this project has no file for is a plain 404, exactly as it always was.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from projectman.config import find_project_root, load_config
from projectman.errors import ValidationError
from projectman.indexer import build_index, ensure_fresh
from projectman.models import EPIC_ID, SPRINT_ID, STORY_ID, TASK_ID
from projectman.store import Store
from projectman.web.errors import coded_errors, http_error, require_id_shape
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
    """Return the project root directory."""
    return find_project_root()


def get_project_dir(root: Path = Depends(get_root)) -> Path:
    """The one store directory this app serves: ``{root}/.project``.

    The dependency for the routes that read files inside the store directory
    (the docs, the activity log, the search index) rather than through the
    Store API.
    """
    return Path(root) / ".project"


#: One Store per store directory, for the life of the process — the web twin
#: of ``server._store_cache``.  There is exactly one store per root, so this
#: holds one object outside tests and one per ``tmp_path`` root inside them.
_store_cache: dict[Path, Store] = {}


def get_store() -> Store:
    """The Store every route acts on: the one over ``{root}/.project``.

    ``app.state.store`` when startup built it for this root — the object the
    app has always used — and a cached Store over the root otherwise, so a
    route still answers in a test that never ran startup and never hands back
    a Store built over some other root.
    """
    root = find_project_root()
    store_dir = Path(root) / ".project"

    from projectman.web.app import app

    existing = getattr(app.state, "store", None)
    if existing is not None and Path(existing.project_dir) == store_dir:
        return existing
    if store_dir not in _store_cache:
        _store_cache[store_dir] = Store(root)
    return _store_cache[store_dir]


#: The four ID shapes :func:`store_for_id` accepts, in the order it tries them.
_ID_PATTERNS = (TASK_ID, STORY_ID, EPIC_ID, SPRINT_ID)


def store_for_id(item_id: str) -> Store:
    """The Store that owns *item_id* — there is one, so it is :func:`get_store`.

    The shape is still checked first, the way ``server._store_for_id`` checks
    it: the store only ever asks whether a file exists, so a malformed ID
    would come back as "not found" alongside a well-formed one that simply is
    not here.  A well-formed ID whose middle segment is not this project's own
    is *not* refused — it just has no file, and that is the 404 the route
    already raises (US-PM-34-5, US-PM-44).
    """
    if not any(pattern.match(item_id or "") for pattern in _ID_PATTERNS):
        raise http_error(
            ValidationError(
                f"malformed id {item_id!r} — expected US-<PREFIX>-<n>, "
                f"US-<PREFIX>-<n>-<m>, EPIC-<PREFIX>-<n> or "
                f"SPRINT-<PREFIX>-<n> with an uppercase prefix"
            )
        )
    return get_store()


# ─── Project ─────────────────────────────────────────────────────


@router.get("/status")
def api_status(store: Store = Depends(get_store)) -> dict:
    """Project status summary: counts, points, completion."""
    # Writes no longer rebuild the indexes (US-PM-29), so the read side is
    # what keeps them honest: bring the derived files up to date if any item
    # has been written since, then report from the Store.
    ensure_fresh(store)
    index = build_index(store)
    pct = 0
    if index.total_points > 0:
        pct = round(index.completed_points / index.total_points * 100)

    # An archived task keeps its last real status, so group it under
    # "archived" rather than reporting abandoned work as todo or done.
    status_groups: dict[str, int] = {}
    for entry in index.entries:
        key = "archived" if entry.archived else entry.status
        status_groups[key] = status_groups.get(key, 0) + 1

    result = {
        "project": store.config.name,
        "epics": index.epic_count,
        "stories": index.story_count,
        "tasks": index.task_count,
        "total_points": index.total_points,
        "completed_points": index.completed_points,
        "completion": f"{pct}%",
        "by_status": status_groups,
    }

    return result


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
def create_epic(
    body: CreateEpicRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Create a new epic.

    A refusal from the store (a taken ID, a malformed field) becomes a coded
    HTTP error rather than a 500 — see :mod:`projectman.web.errors`.
    """
    with coded_errors():
        meta = store.create_epic(
            title=body.title,
            description=body.description,
            priority=body.priority,
            target_date=body.target_date,
            tags=body.tags,
        )
    return meta.model_dump(mode="json")


@router.get("/epics/{epic_id}")
def get_epic(epic_id: str) -> dict:
    """Get epic detail with linked stories and rollup."""
    store = store_for_id(epic_id)
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
        # Archived tasks are abandoned, not delivered and not outstanding —
        # they leave both sides of the rollup.
        counted = [t for t in tasks if not t.archived]
        task_points = sum(t.points or 0 for t in counted)
        done_points = sum(t.points or 0 for t in counted if t.status.value == "done")
        total_points += task_points
        completed_points += done_points
        story_data.append(
            {
                "id": story.id,
                "title": story.title,
                "status": story.status.value,
                "points": story.points,
                "task_points": task_points,
                "done_points": done_points,
            }
        )

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
def update_epic(epic_id: str, body: UpdateItemRequest) -> dict:
    """Update epic fields."""
    store = store_for_id(epic_id)
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(epic_id, **kwargs)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Epic not found: {epic_id}")


@router.delete("/epics/{epic_id}")
def archive_epic(epic_id: str) -> dict:
    """Archive an epic."""
    store = store_for_id(epic_id)
    try:
        store.archive(epic_id)
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
def create_story(
    body: CreateStoryRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Create a new story, optionally linking it to an epic.

    ``epic_id`` is shape-checked before anything is written: linking is a
    second step, so a malformed one would otherwise leave a story on disk and
    report a failure.
    """
    with coded_errors():
        if body.epic_id:
            require_id_shape(body.epic_id, EPIC_ID, "epic")
        meta, test_tasks = store.create_story(
            title=body.title,
            description=body.description,
            priority=body.priority,
            points=body.points,
            acceptance_criteria=body.acceptance_criteria,
            tags=body.tags,
        )
        if body.epic_id:
            store.update(meta.id, epic_id=body.epic_id)
            meta, _ = store.get_story(meta.id)
    result = meta.model_dump(mode="json")
    if test_tasks:
        result["test_tasks"] = [t.model_dump(mode="json") for t in test_tasks]
    return result


@router.get("/stories/{story_id}")
def get_story(story_id: str) -> dict:
    """Get story detail with body and child tasks."""
    store = store_for_id(story_id)
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
def update_story(story_id: str, body: UpdateItemRequest) -> dict:
    """Update story fields."""
    store = store_for_id(story_id)
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(story_id, **kwargs)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")


@router.delete("/stories/{story_id}")
def archive_story(story_id: str) -> dict:
    """Archive a story."""
    store = store_for_id(story_id)
    try:
        store.archive(story_id)
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
def create_task(
    body: CreateTaskRequest,
    store: Store = Depends(get_store),
) -> dict:
    """Create a new task under a story.

    A well-formed ``story_id`` that names no story is still the existing 404;
    a malformed one is a 422, and a taken task ID a 409.
    """
    with coded_errors():
        require_id_shape(body.story_id, STORY_ID, "story")
        try:
            meta = store.create_task(
                story_id=body.story_id,
                title=body.title,
                description=body.description,
                points=body.points,
                tags=body.tags,
                depends_on=body.depends_on,
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Story not found: {body.story_id}"
            )
    return meta.model_dump(mode="json")


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    """Get task detail with body."""
    store = store_for_id(task_id)
    try:
        meta, body = store.get_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {**meta.model_dump(mode="json"), "body": body}


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: UpdateItemRequest) -> dict:
    """Update task fields."""
    store = store_for_id(task_id)
    try:
        kwargs = body.model_dump(exclude_none=True)
        meta = store.update(task_id, **kwargs)
        return meta.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")


@router.post("/tasks/{task_id}/grab")
def grab_task(
    task_id: str,
    body: GrabTaskRequest = GrabTaskRequest(),
) -> dict:
    """Claim a task — validates readiness, assigns, sets in-progress."""
    from projectman.readiness import check_readiness

    store = store_for_id(task_id)
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

    # Compare-and-swap, so this route cannot claim a task out from under a
    # worker that won it between the readiness check and here.
    won, current = store.claim_task(task_id, body.assignee)
    if not won:
        raise HTTPException(
            status_code=409,
            detail={"error": "task is already claimed", "holder": current.assignee},
        )
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
def archive_task(task_id: str) -> dict:
    """Archive a task."""
    store = store_for_id(task_id)
    try:
        store.archive(task_id)
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
    ensure_fresh(store)
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
) -> dict:
    """Search stories and tasks by keyword.

    Returns ``results`` (the ranked hits) and ``skipped`` -- the number of item
    files whose frontmatter would not parse, 0 when the whole store was read.
    """
    try:
        from projectman.embeddings import EmbeddingStore

        emb_store = EmbeddingStore(proj_dir)
        results = emb_store.search(q, top_k=10)
        if results:
            return {
                "results": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "type": r.type,
                        "score": round(r.score, 3),
                    }
                    for r in results
                ],
                # One index file, read whole: nothing to skip per item.
                "skipped": 0,
            }
    except (ImportError, Exception):
        pass

    from projectman.search import keyword_search_with_skipped

    outcome = keyword_search_with_skipped(q, proj_dir)
    return {
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "type": r.type,
                "score": r.score,
                "snippet": r.snippet,
            }
            for r in outcome.results
        ],
        "skipped": outcome.skipped,
    }


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
            lines = [
                l
                for l in content.splitlines()
                if l.strip() and not l.strip().startswith("<!--")
            ]
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
        raise HTTPException(
            status_code=404, detail=f"Unknown doc: {name}. Use: {', '.join(_DOC_MAP)}"
        )
    path = proj_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    return {"name": name, "file": filename, "content": path.read_text()}


# ─── Activity ─────────────────────────────────────────────────


@router.get("/activity")
def api_activity(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    proj_dir: Path = Depends(get_project_dir),
) -> dict:
    """Recent activity log entries (newest first)."""
    from projectman.activity_log import log_paths, read_log_entries

    # Rotated siblings first, then the live file, so the dashboard's page
    # count does not shrink the moment the log rotates (US-PRJ-52-10).
    entries = read_log_entries(log_paths(proj_dir))
    total = len(entries)
    entries = list(reversed(entries))[offset : offset + limit]

    return {"entries": entries, "total": total}


@router.put("/docs/{name}")
def update_doc(
    name: str,
    body: UpdateDocRequest,
    proj_dir: Path = Depends(get_project_dir),
) -> dict:
    """Update a project doc's content."""
    filename = _DOC_MAP.get(name.lower())
    if not filename:
        raise HTTPException(
            status_code=404, detail=f"Unknown doc: {name}. Use: {', '.join(_DOC_MAP)}"
        )
    path = proj_dir / filename
    path.write_text(body.content)
    return {"updated": filename}
