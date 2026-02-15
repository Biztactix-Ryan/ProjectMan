---
created: '2026-02-15'
epic_id: EPIC-PRJ-3
id: US-PRJ-14
points: 5
priority: could
status: done
tags: []
title: Hub mode UI
updated: '2026-02-15'
---

As a hub user, I want a project switcher and cross-project rollup dashboard so that I can manage multiple projects from one interface.

**Features:**
- Project switcher dropdown in nav (visible when hub mode detected)
- Selecting a project adds `?project=` to all API calls
- Hub dashboard at `/hub` showing:
  - Project cards with per-project status/completion
  - Aggregate rollup (total points, completion across all projects)
  - Links to per-project views
- Hub context view from `pm_context()`

**Data sources:** `config.projects`, `hub.rollup.rollup()`, `pm_context()`

**Acceptance criteria:**
- Project switcher only appears in hub mode
- Switching projects filters all views to that project
- Hub dashboard shows cross-project rollup
- Non-hub projects are unaffected (no switcher shown)