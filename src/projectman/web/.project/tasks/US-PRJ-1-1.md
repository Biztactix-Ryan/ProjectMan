---
assignee: claude
created: '2026-02-15'
id: US-PRJ-1-1
points: 1
status: done
story_id: US-PRJ-1
title: Create package structure and __init__.py
updated: '2026-02-15'
---

Create the Python package structure for the web module:

**Files to create:**
- `web/__init__.py` — package init, can be empty or export app
- `web/routes/__init__.py` — routes sub-package init
- `web/templates/` — empty directory (create `.gitkeep` or a placeholder)
- `web/static/` — empty directory (create `.gitkeep` or a placeholder)

**Acceptance criteria:**
- `from projectman.web import app` doesn't error (once app.py exists)
- `from projectman.web.routes import api, pages` doesn't error (once route files exist)
- Directory structure matches the README spec