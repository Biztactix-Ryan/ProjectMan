---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-50-6
- US-PM-50-7
id: US-PM-50-9
points: 2
status: done
story_id: US-PM-50
tags: []
title: List long_task_risk on pm_get_sprint
updated: '2026-09-09'
---

pm_get_sprint adds `long_task_risk`: the sprint's open tasks whose points band has p90 above orchestrate.max_task_minutes, each with id, points, band p50 and p90. Bands with fewer than three samples are skipped. Empty list when nothing is flagged, so the key is always present. Test with a tmp_path store seeded with a synthetic activity log.