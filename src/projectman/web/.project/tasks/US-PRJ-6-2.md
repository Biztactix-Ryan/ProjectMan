---
assignee: null
created: '2026-02-15'
id: US-PRJ-6-2
points: 1
status: done
story_id: US-PRJ-6
title: Add HTMX script, app.js initialization, and static asset serving
updated: '2026-02-15'
---

- Add HTMX script tag to base.html (CDN or bundled in static/)
- Create `static/app.js` with HTMX initialization and any small helpers needed
- Verify FastAPI static files mount serves CSS and JS correctly
- Test that HTMX is loaded and working by adding a simple test partial swap