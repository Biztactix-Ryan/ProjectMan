---
assignee: claude
created: '2026-02-15'
id: US-PRJ-6-1
points: 2
status: done
story_id: US-PRJ-6
title: Create base.html layout with nav, CSS framework, and active highlighting
updated: '2026-02-15'
---

Create `templates/base.html`:
- HTML5 boilerplate with `{% block content %}` for child templates
- Nav bar with links: Dashboard, Board, Epics, Stories, Docs, Audit
- Active nav item highlighting based on current route (pass `active_page` to template context)
- Include a classless/utility CSS framework (e.g., Pico CSS via CDN) for clean defaults
- `static/style.css` for custom overrides
- Footer with project name