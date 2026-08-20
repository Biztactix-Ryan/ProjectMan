---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-21-7
id: US-PM-21-8
points: 3
status: todo
story_id: US-PM-21
tags: []
title: Hub-mode regression check for worktree stores
updated: '2026-08-20'
---

Verify hub mode with worktree-mounted project stores introduces no submodule-pointer noise in the parent repo: task updates in a subproject's .project must not dirty the hub or parent working tree. Add a regression test; fix anything that fails.