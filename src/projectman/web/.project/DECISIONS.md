# ProjectMan Web — Decision Log

| # | Decision | Choice | Rationale | Date |
|---|----------|--------|-----------|------|
| 1 | HTTP framework | FastAPI | Pydantic models plug in as request/response schemas; auto-generates OpenAPI docs; async support; already in the Python ecosystem | 2026-02 |
| 2 | Frontend approach (Phase 1) | Jinja2 + HTMX | Minimal JS, server-rendered, fast to build; Jinja2 already a dependency; doesn't block SPA upgrade later | 2026-02 |
| 3 | Authentication (Phase 1) | Optional token | Single-user local tool; add proper auth later for team/network use | 2026-02 |
| 4 | State management | File-backed (existing `.project/`) | No database to add; files are the source of truth; git provides versioning for free | 2026-02 |
| 5 | API design | REST wrapping existing Store methods | 1:1 mapping to MCP tools; no new business logic; reuse Pydantic models from `models.py` | 2026-02 |
| 6 | Drag-drop on board | HTMX + Sortable.js | Lightweight; no JS build step; sufficient for kanban status transitions | 2026-02 |

## Open Questions

- **Real-time updates**: WebSocket/SSE for live board updates, or polling sufficient for v1?
- **Markdown editor**: Plain textarea vs CodeMirror/Monaco for syntax highlighting?
- **Git auto-commit**: Should web server auto-commit after each write, or leave to user?
- **Auth scope**: For team use, per-user auth + per-project permissions, or always behind VPN/localhost?

---
*Last reviewed: 2026-02-15*