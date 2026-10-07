---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-62-6
id: US-PM-62-7
points: 1
status: todo
story_id: US-PM-62
tags: []
title: Refresh the band after status-changing pm tool calls
updated: '2026-10-07'
---

tool.call hooks on mcp__projectman__ tools that change state (pm_update, pm_grab, pm_done_next, pm_accept, ...) refresh the band's state after next(e) resolves.