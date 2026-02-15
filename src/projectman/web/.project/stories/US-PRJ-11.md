---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-11
points: 5
priority: should
status: done
tags: []
title: Documentation editor
updated: '2026-02-15'
---

As a user, I want to view and edit project documentation in the browser so that I can update docs without leaving the web UI.

**Docs list (`/docs`):**
- List all project docs (PROJECT.md, INFRASTRUCTURE.md, SECURITY.md, VISION.md, ARCHITECTURE.md, DECISIONS.md)
- Staleness indicators (current/stale based on last_modified age)
- Content line count
- Click to open editor

**Doc editor (`/docs/{name}`):**
- Markdown textarea (plain textarea for Phase 1; CodeMirror upgrade is Phase 3)
- Live preview panel (rendered markdown alongside editor)
- Save button → PUT `/api/docs/{name}`
- Success/error feedback

**Data sources:** `pm_docs()`, `pm_docs(doc=name)`, `pm_update_doc()`

**Acceptance criteria:**
- All docs listed with staleness status
- Editor loads current content
- Save persists changes to `.project/` files
- Preview updates on input (debounced)