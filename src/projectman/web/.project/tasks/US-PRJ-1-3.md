---
assignee: claude
created: '2026-02-15'
id: US-PRJ-1-3
points: 1
status: done
story_id: US-PRJ-1
title: Add stub routes and static assets
updated: '2026-02-15'
---

Create placeholder route files and minimal static assets to verify the scaffold works end-to-end.

**Files to create:**

`routes/api.py`:
- `router = APIRouter(prefix="/api")` 
- Placeholder: `GET /api/status` returning `{"status": "ok"}` (will be replaced by real endpoint in US-PRJ-2)

`routes/pages.py`:
- `router = APIRouter()`
- Placeholder: `GET /` returning a simple Jinja2-rendered page (or plain HTML) confirming the server is running

`static/style.css`:
- Minimal CSS reset or placeholder comment

`static/app.js`:
- Empty or placeholder comment (HTMX will be added in US-PRJ-6)

**Verification checklist:**
- `GET /` returns HTML page
- `GET /api/status` returns JSON `{"status": "ok"}`
- `GET /docs` shows both endpoints in OpenAPI
- `GET /static/style.css` serves the CSS file
- `GET /static/app.js` serves the JS file

**Acceptance criteria:**
- All 5 verification checks pass
- No import errors when starting the app