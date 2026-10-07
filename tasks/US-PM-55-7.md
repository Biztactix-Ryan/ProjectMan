---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-55-6
id: US-PM-55-7
points: 1
status: done
story_id: US-PM-55
tags: []
title: Write ADR-006 for the plugin's server launch
updated: '2026-10-07'
---

Add ADR-006 to DECISIONS.md: the chosen launch command and plugin layout (plugin root = repo root vs subfolder), or the reason pipx stays and how the plugin pins to a compatible server version (e.g. a version check in the SessionStart hook). Cite the measurements from US-PM-55-6. US-PM-56-7 builds on this.