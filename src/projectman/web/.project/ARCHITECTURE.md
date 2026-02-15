# ProjectMan Web — Architecture

## Overview

The web UI is a thin HTTP adapter layered on top of ProjectMan's existing core. No business logic is rewritten — FastAPI routes call the same Store methods and business logic modules that the MCP server uses.

## System Architecture

```
┌─────────────────────────────────┐
│  Browser (Jinja2 + HTMX)       │
└──────────────┬──────────────────┘
               │ HTTP / JSON
┌──────────────▼──────────────────┐
│  FastAPI App                    │
│  ├── routes/api.py  (JSON API)  │
│  ├── routes/pages.py (HTML)     │
│  ├── templates/     (Jinja2)    │
│  └── static/        (CSS/JS)    │
└──────────────┬──────────────────┘
               │ Python calls
┌──────────────▼──────────────────┐
│  ProjectMan Core                │
│  ├── store.py      (CRUD)       │
│  ├── models.py     (Pydantic)   │
│  ├── audit.py      (drift)      │
│  ├── readiness.py  (DoR)        │
│  ├── search.py     (keyword)    │
│  ├── embeddings.py (semantic)   │
│  ├── scoper.py     (breakdown)  │
│  ├── estimator.py  (sizing)     │
│  └── indexer.py    (rollup)     │
└──────────────┬──────────────────┘
               │ reads/writes
┌──────────────▼──────────────────┐
│  .project/                      │
│  ├── config.yaml                │
│  ├── stories/*.md               │
│  ├── tasks/*.md                 │
│  ├── epics/*.md                 │
│  └── *.md (docs)                │
└─────────────────────────────────┘
```

## API Layer

REST API at `/api/*` maps 1:1 to Store methods and MCP tools:

- **Project**: GET `/api/status`, `/api/config`
- **Epics**: CRUD at `/api/epics[/{id}]`
- **Stories**: CRUD at `/api/stories[/{id}]`
- **Tasks**: CRUD at `/api/tasks[/{id}]`, POST `/api/tasks/{id}/grab`
- **Intelligence**: GET `/api/board`, `/api/burndown`, `/api/audit`, `/api/search`
- **Docs**: GET/PUT `/api/docs[/{name}]`
- **Hub**: GET `/api/hub/projects`, `/api/hub/rollup`, `/api/hub/context`

All endpoints accept optional `?project=` query param for hub mode.

## UI Views (Phase 1 — Server-Rendered)

| View | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Status summary, completion %, counts, quick links |
| Board | `/board` | Kanban columns via HTMX + Sortable.js |
| Epics | `/epics[/{id}]` | List + detail with progress bars |
| Stories | `/stories[/{id}]` | Filterable list + detail with child tasks |
| Tasks | `/tasks/{id}` | Task info + status transitions |
| Docs | `/docs[/{name}]` | List with staleness + markdown editor |
| Audit | `/audit` | Findings by severity |
| Burndown | `/burndown` | Chart.js visualization |
| Search | `/search` | Search bar + results |

## Phased Approach

- **Phase 1**: API layer + server-rendered HTML (Jinja2 + HTMX)
- **Phase 2**: Optional SPA upgrade — JSON API already exists for React/Vue/Svelte frontend
- **Phase 3**: Polish — search, hub project switcher, toast notifications, responsive layout

## Design Principles

- **No logic duplication** — Web layer delegates entirely to core modules
- **Progressive enhancement** — HTMX adds interactivity without JS build step
- **API-first** — JSON endpoints work independently of HTML views
- **Hub-compatible** — All endpoints support multi-project via `?project=` param

---
*Last reviewed: 2026-02-15*