---
assignee: null
created: '2026-02-15'
id: US-PRJ-12-1
points: 2
status: done
story_id: US-PRJ-12
title: Create audit view with findings grouped by severity
updated: '2026-02-15'
---

Create `templates/audit.html` extending base.html:
- Page route at `/audit` in `routes/pages.py`
- Run audit on page load via GET `/api/audit`
- Group findings by severity (error, warning, info)
- Each finding shows: type, description, affected item ID (linked to detail view)
- Summary count at top (X errors, Y warnings, Z info)
- Handle empty state (no findings = healthy project)