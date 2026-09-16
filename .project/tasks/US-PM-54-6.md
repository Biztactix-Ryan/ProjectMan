---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-17'
depends_on: []
id: US-PM-54-6
points: 1
status: done
story_id: US-PM-54
tags: []
title: Document the heartbeat in orchestrate-design.md and cli.md
updated: '2026-09-17'
---

New ## Heartbeat section in docs/reference/orchestrate-design.md: the cachebeat prior art, the measured regime table (1h as today, 1h + 30-min heartbeat, 5m + 4-min ping-pong, 5m no pings), why cron cadence is 30 minutes, why the job is session-only and self-deleting, and the promptCacheTtl setting that pins the one-hour cache through usage-credit overage. Add the row to the Sizes and numbers table and the TTL/heartbeat rows to the orch-cost section of cli.md. Register the section in tests/test_orchestrate_design_doc.py.