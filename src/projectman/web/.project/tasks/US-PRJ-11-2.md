---
assignee: null
created: '2026-02-15'
id: US-PRJ-11-2
points: 2
status: done
story_id: US-PRJ-11
title: Build doc editor with textarea and save via PUT
updated: '2026-02-15'
---

Create `templates/doc_editor.html` extending base.html:
- Page route at `/docs/{name}` in `routes/pages.py`
- Load current doc content via `pm_docs(doc=name)`
- Markdown textarea (plain textarea for Phase 1)
- Save button fires PUT `/api/docs/{name}` with textarea content
- Success/error feedback after save
- Back link to docs list