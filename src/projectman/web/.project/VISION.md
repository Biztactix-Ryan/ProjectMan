# ProjectMan Web — Vision

## Purpose

Provide a browser-based interface for ProjectMan so users can view and manage projects, epics, stories, tasks, and documentation without needing Claude Code or the CLI.

## Goals

1. **Accessibility** — Make project data browsable and editable through any web browser
2. **Zero new infrastructure** — No database, no build step, no external services; runs locally on existing `.project/` files
3. **Reuse, don't rewrite** — Thin HTTP layer over existing Store and business logic; all validation handled by core Pydantic models
4. **Progressive enhancement** — Start with server-rendered HTML + HTMX; upgrade to SPA later if needed without rewriting the API

## Success Criteria

- All MCP tool operations are accessible via REST API
- Server-rendered views cover dashboard, board, CRUD for epics/stories/tasks, docs, audit, and burndown
- Single command to start: `projectman web`
- Hub mode works via `?project=` parameter on all endpoints
- No regressions to existing CLI or MCP server functionality

## Non-Goals (Phase 1)

- Multi-user collaboration / real-time sync
- Cloud deployment or hosted service
- SPA frontend with JS build toolchain
- Mobile-specific UI

---
*Last reviewed: 2026-02-15*