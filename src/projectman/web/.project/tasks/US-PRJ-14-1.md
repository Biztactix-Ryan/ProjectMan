---
assignee: null
created: '2026-02-15'
id: US-PRJ-14-1
points: 2
status: done
story_id: US-PRJ-14
title: Add project switcher dropdown to nav (hub mode only)
updated: '2026-02-15'
---

Enhance nav in `templates/base.html`:
- Detect hub mode from config (multiple projects configured)
- Show project switcher dropdown only when hub mode is active
- Selecting a project adds `?project=` to all API calls / navigation links
- Current project name shown in dropdown trigger
- Non-hub projects unaffected (no switcher shown)
- Data from `config.projects` list