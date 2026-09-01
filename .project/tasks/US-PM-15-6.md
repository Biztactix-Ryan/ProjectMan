---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-15-6
points: 1
status: done
story_id: US-PM-15
tags: []
title: Move repair and restore tooling off the agent tool list
updated: '2026-08-22'
---

pm_repair, pm_restore, pm_validate_branches, pm_fix_malformed, pm_push_all are human break-glass tools. Keep them reachable via CLI; hide them from the agent-facing tool list.

Do not gate pm_activity, pm_context or pm_estimate — US-PM-13 and US-PM-14 put all three to work. Their zero usage is a wiring gap, not a signal they are unwanted.