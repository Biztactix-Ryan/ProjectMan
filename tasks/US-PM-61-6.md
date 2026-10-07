---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-60-6
id: US-PM-61-6
points: 3
status: todo
story_id: US-PM-61
tags: []
title: Record per-request token usage per orchestrator run and task
updated: '2026-10-07'
---

Hook the turn/request events to capture input, cache-read and cache-write tokens; attribute requests to the run and task from pm tool calls (pm_grab/pm_accept run ids). Keep live values in $.state and per-run summaries in $.store.