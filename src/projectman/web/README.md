# ProjectMan Web UI

Web interface for ProjectMan — view and edit projects, epics, user stories, tasks, and documentation through the browser.

## Why this works

ProjectMan already has clean separation between data models, storage, and API:

- **`models.py`** — Pydantic models (Story, Task, Epic, Config, Index) with validation
- **`store.py`** — CRUD operations decoupled from any transport layer
- **`server.py`** — 30+ MCP tools that already act as a structured API surface
- **Business logic modules** — readiness, audit, scoping, estimation, search, burndown

The web layer is a thin HTTP adapter over the same functions the MCP server already calls. No business logic needs to be rewritten.

---

## Architecture

```
Browser (SPA or HTMX)
    |
    | HTTP / JSON
    v
FastAPI app  (src/projectman/web/app.py)
    |
    | Python calls
    v
Store + business logic  (existing modules)
    |
    | reads/writes
    v
.project/  (git-backed markdown + YAML frontmatter)
```

### Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| HTTP framework | **FastAPI** | Pydantic models plug straight in as request/response schemas; auto-generates OpenAPI docs; async support; already in the Python ecosystem |
| Frontend | **Jinja2 + HTMX** (Phase 1) | Minimal JS, server-rendered, fast to build; Jinja2 is already a dependency; upgrade to SPA later if needed |
| Auth | **Optional token** (Phase 1) | Single-user local tool; add proper auth later for team use |
| State | **File-backed (existing)** | No database to add — `.project/` files are the source of truth |

---

## REST API Design

Thin wrappers around existing `Store` methods and MCP tool functions.

### Project

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/status` | `pm_status()` |
| GET | `/api/config` | `load_config()` |

### Epics

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/epics` | `store.list_epics()` |
| POST | `/api/epics` | `store.create_epic()` |
| GET | `/api/epics/{id}` | `pm_epic()` (includes rollup) |
| PATCH | `/api/epics/{id}` | `store.update()` |
| DELETE | `/api/epics/{id}` | `store.archive()` |

### Stories

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/stories` | `store.list_stories(?status=)` |
| POST | `/api/stories` | `store.create_story()` |
| GET | `/api/stories/{id}` | `store.get_story()` |
| PATCH | `/api/stories/{id}` | `store.update()` |
| DELETE | `/api/stories/{id}` | `store.archive()` |

### Tasks

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/tasks` | `store.list_tasks(?story_id=&status=)` |
| POST | `/api/tasks` | `store.create_task()` |
| GET | `/api/tasks/{id}` | `store.get_task()` |
| PATCH | `/api/tasks/{id}` | `store.update()` |
| POST | `/api/tasks/{id}/grab` | `pm_grab()` |
| DELETE | `/api/tasks/{id}` | `store.archive()` |

### Board & Intelligence

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/board` | `pm_board()` |
| GET | `/api/burndown` | `pm_burndown()` |
| GET | `/api/audit` | `pm_audit()` |
| GET | `/api/search?q=` | `pm_search()` |

### Documentation

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/docs` | `pm_docs()` (summary) |
| GET | `/api/docs/{name}` | `pm_docs(doc=name)` |
| PUT | `/api/docs/{name}` | `pm_update_doc()` |

### Hub mode (multi-project)

All endpoints accept an optional `?project=` query parameter, matching the existing MCP tool pattern. Hub-level endpoints:

| Method | Endpoint | Maps to |
|---|---|---|
| GET | `/api/hub/projects` | `config.projects` list |
| GET | `/api/hub/rollup` | `hub.rollup.rollup()` |
| GET | `/api/hub/context` | `pm_context()` |

---

## UI Views

### Phase 1 — Server-rendered with HTMX

Built with Jinja2 templates + HTMX for interactivity without a JS build step.

| View | Route | Description |
|---|---|---|
| **Dashboard** | `/` | Project status, completion %, counts by status, quick links |
| **Board** | `/board` | Kanban columns (Available / In Progress / Review / Blocked / Done); drag-drop via HTMX + Sortable.js |
| **Epics list** | `/epics` | Table with status badges, progress bars, story counts |
| **Epic detail** | `/epics/{id}` | Epic info + linked stories + rollup stats; inline edit |
| **Stories list** | `/stories` | Filterable table (status, priority, epic); sortable columns |
| **Story detail** | `/stories/{id}` | Story frontmatter + rendered markdown body + child tasks; inline edit |
| **Task detail** | `/tasks/{id}` | Task info + parent story context; status transitions via buttons |
| **Docs** | `/docs` | List of project docs with staleness indicators |
| **Doc editor** | `/docs/{name}` | Markdown editor (textarea or CodeMirror) with live preview |
| **Audit** | `/audit` | Audit findings grouped by severity |
| **Burndown** | `/burndown` | Simple chart (Chart.js or similar) |
| **Search** | `/search` | Search box with results |

### Phase 2 — Optional SPA upgrade

If richer interactivity is needed later, the JSON API is already there. A React/Vue/Svelte frontend could consume `/api/*` endpoints directly. Phase 1 doesn't block Phase 2.

---

## File Structure

```
src/projectman/web/
    __init__.py          # Package init
    app.py               # FastAPI app, middleware, startup
    routes/
        __init__.py
        api.py           # JSON API endpoints (all /api/* routes)
        pages.py         # HTML page routes (Jinja2 rendered)
    templates/
        base.html        # Layout: nav, sidebar, footer
        dashboard.html
        board.html
        epics.html
        epic_detail.html
        stories.html
        story_detail.html
        task_detail.html
        docs.html
        doc_editor.html
        audit.html
        burndown.html
        search.html
        _partials/       # HTMX fragments for partial updates
            story_row.html
            task_card.html
            status_badge.html
    static/
        style.css        # Minimal custom CSS (use a classless/utility framework)
        app.js           # HTMX init + any small helpers
```

---

## Implementation Plan

### Phase 1: API layer

1. **`app.py`** — FastAPI app with CORS, static files mount, Jinja2 templates, project root resolution
2. **`routes/api.py`** — All `/api/*` endpoints wrapping `Store` and business logic modules
3. **Request/response schemas** — Reuse Pydantic models from `models.py`; add thin API-specific schemas where needed (e.g., `CreateStoryRequest`, `UpdateItemRequest`)
4. **CLI integration** — Add `projectman serve-web` command (or `--web` flag) to `cli.py`
5. **Tests** — FastAPI TestClient tests against the API endpoints

### Phase 2: HTML views

6. **`base.html`** — Layout with nav (Dashboard, Board, Epics, Stories, Docs, Audit)
7. **Dashboard** — Status summary, counts, completion chart
8. **Board view** — Kanban with HTMX-powered drag-drop status transitions
9. **List views** — Epics, Stories with filtering/sorting
10. **Detail views** — Epic, Story, Task with inline editing
11. **Doc editor** — Markdown editing with preview
12. **Audit + Burndown** — Read-only views

### Phase 3: Polish

13. **Search** — Search bar in nav, results page
14. **Hub mode** — Project switcher in nav, rollup dashboard
15. **Notifications** — Toast messages for create/update/error feedback
16. **Mobile** — Responsive layout

---

## Dependencies to add

```toml
# In pyproject.toml [project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "htmx",  # or just include htmx.min.js in static/
]
```

Jinja2 is already a dependency. No database needed.

---

## CLI Entry Point

```
projectman web              # Start web server on http://localhost:8000
projectman web --port 3000  # Custom port
projectman web --host 0.0.0.0  # Expose on network
```

---

## What we get for free

Because the existing codebase is well-structured:

- **Validation** — Pydantic models enforce fibonacci points, valid IDs, status enums on every write
- **Readiness checks** — Board view can show ready/not-ready badges using existing `check_readiness()`
- **Audit** — One-click project health check using existing `run_audit()`
- **Search** — Semantic search (if sentence-transformers installed) or keyword fallback
- **Hub mode** — Multi-project support already handled by `_resolve_root(project)`
- **Git integration** — Every edit through the web UI modifies files that git tracks, giving full history
- **OpenAPI docs** — FastAPI auto-generates interactive API docs at `/docs`

---

## Open questions

- **Real-time updates**: If multiple users edit simultaneously, should we add WebSocket/SSE for live board updates, or is polling sufficient for v1?
- **Body editing**: Stories/tasks have markdown bodies. Should the editor be a plain textarea, or invest in CodeMirror/Monaco for syntax highlighting?
- **Git auto-commit**: Should the web server auto-commit after each write operation, or leave that to the user?
- **Auth scope**: For team use, do we need per-user auth and per-project permissions, or is this always behind a VPN/localhost?
