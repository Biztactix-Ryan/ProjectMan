# ProjectMan Web

Web interface for ProjectMan — view and edit projects, epics, user stories, tasks, and documentation through the browser. A thin HTTP adapter over the same functions the MCP server already calls.

## Architecture

### Tech Stack

- **Language**: Python 3.10+
- **Framework**: FastAPI (HTTP) + Jinja2 (templates) + HTMX (interactivity)
- **Database**: None — file-backed `.project/` directory (git-native markdown + YAML frontmatter)
- **Key Libraries**: Pydantic (validation/schemas), Uvicorn (ASGI server), HTMX (partial page updates)

### Components

- **`app.py`** — FastAPI app with CORS, static files mount, Jinja2 templates, project root resolution
- **`routes/api.py`** — JSON API endpoints (`/api/*`) wrapping Store and business logic modules
- **`routes/pages.py`** — HTML page routes (Jinja2 server-rendered views)
- **`templates/`** — Jinja2 templates for dashboard, board, epics, stories, tasks, docs, audit, burndown, search
- **`static/`** — CSS + JS (HTMX init, helpers)

### Data Flow

```
Browser (Jinja2 + HTMX)
    |
    | HTTP / JSON
    v
FastAPI app  (app.py + routes/)
    |
    | Python calls
    v
Store + business logic  (projectman core: store.py, audit.py, readiness.py, etc.)
    |
    | reads/writes
    v
.project/  (git-backed markdown + YAML frontmatter)
```

## Key Decisions

- **FastAPI over Flask/Django** — Pydantic models plug straight in as request/response schemas; auto-generates OpenAPI docs; async support — 2026-02
- **Jinja2 + HTMX for Phase 1** — Minimal JS, server-rendered, fast to build; Jinja2 already a dependency; upgrade to SPA later if needed — 2026-02
- **Optional token auth for Phase 1** — Single-user local tool; add proper auth later for team use — 2026-02
- **File-backed storage (existing)** — No database to add; `.project/` files are the source of truth, git provides version history — 2026-02
- **No business logic rewrite** — Web layer wraps existing Store + MCP tool functions; all validation handled by Pydantic models in `models.py` — 2026-02

## Dependencies

```toml
# In pyproject.toml [project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
]
```

Core dependencies inherited from parent projectman package:
- `click>=8.0` (CLI)
- `pyyaml>=6.0` (YAML parsing)
- `pydantic>=2.0` (data validation)
- `jinja2>=3.0` (templates — already a dep)
- `python-frontmatter>=1.0` (frontmatter parsing)

## Development Setup

### Prerequisites
- Python 3.10+
- ProjectMan installed (`pip install -e ".[web]"` from repo root)

### Running
```bash
projectman web              # Start on http://localhost:8000
projectman web --port 3000  # Custom port
projectman web --host 0.0.0.0  # Expose on network
```

### Testing
```bash
pytest tests/  # From repo root
```

### API Docs
FastAPI auto-generates interactive docs at `/docs` (Swagger) and `/redoc`.

---
*Last reviewed: 2026-02-15*
*Update this document when architecture changes. The daily audit checks for staleness.*