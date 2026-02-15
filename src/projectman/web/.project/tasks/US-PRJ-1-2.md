---
assignee: claude
created: '2026-02-15'
id: US-PRJ-1-2
points: 3
status: done
story_id: US-PRJ-1
title: Implement app.py with FastAPI core
updated: '2026-02-15'
---

Create the main FastAPI application in `web/app.py`:

**Implementation:**
- FastAPI app instance with title="ProjectMan Web", version from `projectman.__init__`
- CORS middleware (allow all origins for local dev; configurable later)
- Jinja2 `Jinja2Templates` pointing to `web/templates/`
- Static files mount: `app.mount("/static", StaticFiles(directory=...))` 
- Project root resolution: use `config.find_project_root()` at startup
- Store instantiation: create `Store(root)` available to routes (via app.state or dependency injection)
- Include routers from `routes/api.py` and `routes/pages.py`
- `if __name__ == "__main__"` block running `uvicorn.run(app, host="127.0.0.1", port=8000)`

**Key dependency pattern:**
```python
def get_store() -> Store:
    return app.state.store
```

**Acceptance criteria:**
- `python -m projectman.web.app` starts Uvicorn on localhost:8000
- `/docs` shows FastAPI OpenAPI UI
- App discovers `.project/` root and initializes Store
- Templates and static files directories configured correctly