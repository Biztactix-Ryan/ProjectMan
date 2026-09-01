---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-12-6
points: 3
status: done
story_id: US-PM-12
tags: []
title: Add pm_update_many
updated: '2026-08-21'
---

Follow the shape already proven by pm_create_tasks. Accept either a uniform patch across a CSV ID list or a list of per-item patches for heterogeneous updates.

The four measured bulk patterns to support directly: mark-done with run log, dependency wiring, estimation, bare status flip.