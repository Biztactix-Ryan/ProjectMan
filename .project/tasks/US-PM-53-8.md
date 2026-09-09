---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-53-7
id: US-PM-53-8
points: 3
status: done
story_id: US-PM-53
tags: []
title: Validate and merge one lane while the other runs, with the merge-order rule
updated: '2026-09-09'
---

skill_pm_orchestrate.md.j2: on a lane's task notification the orchestrator runs the validator subagent and, on accept, merges that branch onto the run branch immediately; the other lane keeps running. Merge order is acceptance order. Because the second branch was cut before the first merge, a conflict on it is expected occasionally: pm_retry once with the conflicting paths in evidence and a rebase instruction, pm_park on the second conflict. Refill the freed lane with the next lane-compatible task judged against the lane still in flight.