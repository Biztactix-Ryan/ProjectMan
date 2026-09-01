---
acceptance_criteria:
- A bulk update accepts either a uniform patch over an ID list or per-item patches
- Bulk archive accepts an explicit ID list
- Partial failure reports which IDs succeeded and which did not
- The four measured bulk patterns are each expressible in one call
- Longest consecutive-run length drops sharply in the next telemetry baseline
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-12
points: 5
priority: should
status: ready
tags:
- workflow
- api-design
- safety
title: Bulk write verbs for update and archive
updated: '2026-08-21'
---

As an agent doing multi-item work, I want to express it as one call, so that it reads as one reviewable intent instead of a runaway sweep.

pm_update and pm_archive are single-item only, so the model fires them in long uniform bursts. Longest observed runs: pm_update 109 (Study A), 54 (Study C), 27 (Study B and Study D); pm_archive 114 (Study C), with 266 of 269 archive calls occurring inside a run of 3 or more.

The bursts are genuine multi-item work, not retry churn — Study B checked: of 559 consecutive pm_update pairs, 406 target different IDs. Four bulk patterns recur: mark-done with run log, dependency wiring, estimation, bare status flip.

The safety argument matters more than the token argument. Study C recorded three pm_archive calls denied mid-sweep by Claude Code's permission classifier:
    "[External System Writes] The agent is mass-archiving 12 pre-existing PM items"
A long tail of identical destructive single-item calls reads as runaway behaviour. One declared bulk call with an explicit ID list reads as one reviewable intent. This is the only place where the missing bulk verb causes a correctness failure rather than only cost.

Precedent already exists in the codebase: pm_create_tasks and pm_batch_get ship working batch shapes, and pm_create_tasks has almost entirely displaced pm_create_task (64 vs 13 calls on Study A; 54 vs 1 on Study D). Follow that shape — accept either a uniform patch across an ID list or a list of per-item patches.