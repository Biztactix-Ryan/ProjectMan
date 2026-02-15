---
assignee: null
created: '2026-02-15'
id: US-PRJ-11-1
points: 2
status: done
story_id: US-PRJ-11
title: Create docs list page with staleness indicators
updated: '2026-02-15'
---

Create `templates/docs.html` extending base.html:
- Page route at `/docs` in `routes/pages.py`
- List all project docs (PROJECT.md, INFRASTRUCTURE.md, SECURITY.md, VISION.md, ARCHITECTURE.md, DECISIONS.md)
- Show staleness indicator (current/stale based on age or last_modified)
- Content line count for each doc
- Click to open editor at `/docs/{name}`
- Data from `pm_docs()` summary endpoint