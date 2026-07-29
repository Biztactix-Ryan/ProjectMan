---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-3-5
id: US-PM-3-6
points: 2
status: done
story_id: US-PM-3
tags: []
title: Apply the resolver across all ID-taking tools
updated: '2026-07-29'
---

Tools currently taking a typed name must also accept id: pm_grab, pm_done_next, pm_get_sprint, pm_update_sprint. Tools taking id should accept the typed alias where one exists: pm_update, pm_get, pm_archive.

Study B's census shows the traffic split for pm_grab alone: task_id 459, id 15.