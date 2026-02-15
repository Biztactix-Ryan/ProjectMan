---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-6
points: 3
priority: must
status: done
tags: []
title: Base layout template
updated: '2026-02-15'
---

As a user, I want a consistent page layout with navigation so that I can move between views easily.

**Includes:**
- `templates/base.html` — main layout with nav bar, sidebar, content area, footer
- Navigation links: Dashboard, Board, Epics, Stories, Docs, Audit
- HTMX script tag and initialization in `static/app.js`
- Minimal CSS framework (classless or utility — e.g., Pico CSS or similar)
- `static/style.css` for custom overrides
- Active nav item highlighting based on current route

**Acceptance criteria:**
- All pages extend `base.html` and inherit consistent layout
- Nav highlights current page
- HTMX loaded and working for partial updates
- Clean, readable default styling without custom CSS heavy-lifting