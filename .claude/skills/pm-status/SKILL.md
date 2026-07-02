---
name: pm-status
description: Project status dashboard — completion, active sprint progress, in-flight work, blockers, recent failures. Use when the user asks "how are we doing", "project status", or "where are we at".
---

# /pm-status — Status Dashboard

1. Call `pm_status` for the project overview and `pm_active` for in-flight work.
2. Call `pm_list_sprints(status="active")` — if a sprint is active, include its progress.
3. Present a clean dashboard:
   - Project name and completion percentage
   - **Active sprint**: goal, days remaining, points done vs. planned (flag a sprint past its end date — suggest closing it via `/pm-plan`)
   - Story/task counts by status; points completed vs. remaining
   - Active work items with assignees — flag stale in-progress tasks (assigned but untouched)
   - Blockers: blocked tasks, tasks waiting on cross-story dependencies, stories waiting on other stories
4. **Recent failures**: check `pm_activity` for recent failed/blocked run-log outcomes — surface tasks that agents attempted and couldn't complete; these need human attention before re-orchestrating.
5. Flag any dependency cycles detected.
6. End with the single most useful next action (plan, orchestrate, scope, or fix).
