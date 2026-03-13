"""Orchestrator-facing REST API and SSE event stream.

Mounted alongside the MCP SSE server when running in SSE transport mode.
"""

import asyncio
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .event_bus import EventBus

# Module-level state set by register_routes()
_event_bus: EventBus | None = None
_start_time: float = 0.0
_get_store: Any = None  # callable returning Store


def register_routes(mcp_instance: Any, event_bus: EventBus, get_store: Any) -> None:
    """Register REST and SSE routes on the FastMCP instance.

    Args:
        mcp_instance: The FastMCP server object (has .custom_route decorator)
        event_bus: The active EventBus for SSE streaming
        get_store: Callable that returns a Store instance
    """
    global _event_bus, _start_time, _get_store
    _event_bus = event_bus
    _start_time = time.time()
    _get_store = get_store

    @mcp_instance.custom_route("/api/health", methods=["GET"])
    async def api_health(request: Request) -> JSONResponse:
        store = _get_store()
        return JSONResponse({
            "status": "ok",
            "projectId": store.config.name,
            "uptime": round(time.time() - _start_time, 1),
        })

    @mcp_instance.custom_route("/api/project", methods=["GET"])
    async def api_project(request: Request) -> JSONResponse:
        from .indexer import build_index
        store = _get_store()
        index = build_index(store)
        pct = 0
        if index.total_points > 0:
            pct = round(index.completed_points / index.total_points * 100)

        status_groups: dict[str, int] = {}
        for entry in index.entries:
            status_groups[entry.status] = status_groups.get(entry.status, 0) + 1

        changesets = store.list_changesets()
        cs_by_status: dict[str, int] = {}
        for cs in changesets:
            cs_by_status[cs.status.value] = cs_by_status.get(cs.status.value, 0) + 1

        return JSONResponse({
            "project": store.config.name,
            "epics": index.epic_count,
            "stories": index.story_count,
            "tasks": index.task_count,
            "totalPoints": index.total_points,
            "completedPoints": index.completed_points,
            "completion": f"{pct}%",
            "byStatus": status_groups,
            "changesets": len(changesets),
            "changesetsByStatus": cs_by_status,
        })

    @mcp_instance.custom_route("/api/tasks/current", methods=["GET"])
    async def api_tasks_current(request: Request) -> JSONResponse:
        store = _get_store()
        active_tasks = store.list_tasks(status="in-progress")
        queued_tasks = store.list_tasks(status="todo")

        active = None
        if active_tasks:
            t = active_tasks[0]
            active = _task_to_dict(store, t)

        queued = [_task_to_dict(store, t) for t in queued_tasks]
        return JSONResponse({"active": active, "queued": queued})

    @mcp_instance.custom_route("/api/tasks/{task_id:path}", methods=["GET"])
    async def api_task_detail(request: Request) -> JSONResponse:
        task_id = request.path_params["task_id"]
        store = _get_store()
        try:
            meta, body = store.get_task(task_id)
        except FileNotFoundError:
            return JSONResponse({"error": f"Task not found: {task_id}"}, status_code=404)
        result = meta.model_dump(mode="json")
        result["body"] = body
        return JSONResponse(result, status_code=200)

    @mcp_instance.custom_route("/events", methods=["GET"])
    async def events_stream(request: Request) -> StreamingResponse:
        assert _event_bus is not None
        queue = _event_bus.subscribe()
        last_event_id = request.headers.get("Last-Event-ID")
        last_id = int(last_event_id) if last_event_id else 0

        async def generate():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue

                    if event.id <= last_id:
                        continue

                    import json
                    yield f"id: {event.id}\n"
                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(event.data)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                _event_bus.unsubscribe(queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def _task_to_dict(store: Any, task: Any) -> dict[str, Any]:
    """Convert a task frontmatter to a JSON-friendly dict."""
    result = task.model_dump(mode="json")
    try:
        _, body = store.get_task(task.id)
        result["body"] = body
    except FileNotFoundError:
        result["body"] = ""
    return result
