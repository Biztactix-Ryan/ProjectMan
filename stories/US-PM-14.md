---
acceptance_criteria:
- An interrupted run can identify which claims it owned
- Stale claims are identifiable without asking a human
- The final report is built from the activity log rather than from memory
- pm-orchestrate has a documented resume path
created: '2026-07-29'
depends_on:
- US-PM-7
epic_id: EPIC-PM-2
id: US-PM-14
points: 5
priority: could
status: done
tags:
- orchestrator
- recovery
- activity-log
title: Activity-backed resume and recovery for orchestrator runs
updated: '2026-08-22'
---

As an orchestrator restarting after a crash, I want to reconstruct what the previous run did, so that abandoned claims do not require a human to untangle.

pm_activity was called zero times across all four studies — ~14,200 calls, ~1,500 sessions, 4 machines. Yet it queries the authoritative append-only mutation log with filters for item_id, event_type, actor and date range, which is exactly what two parts of pm-orchestrate currently improvise:

- Phase 1 step 3 guesses whether in-progress tasks belong to a previous orchestrator run, and asks the human when unsure. That is a pm_activity query with actor and event_type filters.
- Phase 4 steps 22-23 reconstruct the final report from the orchestrator's own memory plus a git diff. The activity log is the record of what actually changed.

The gap this exposes: there is currently no crash-recovery path at all. A run that dies mid-loop leaves tasks claimed by "claude" with no way to determine intent, and the next run's only recourse is to ask. Combined with US-PM-7's atomic claim this closes the loop — claims become recoverable rather than merely detectable.

Consider a claim timestamp or lease so stale claims are identifiable without inference.