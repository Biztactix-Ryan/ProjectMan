---
acceptance_criteria:
- pm_next or pm_board can return the next ready task that is lane-compatible with
  a named in-flight task, judged from depends_on and story membership in the store
- The orchestrate skill accepts --lanes 2 and keeps at most two claims in flight,
  each in its own worktree branch
- While one lane's worker runs, the orchestrator validates and merges the other lane's
  returned work
- A merge conflict on the second lane's branch produces pm_retry with the conflict
  as evidence and pm_park on the second failure
- orchestrate-design.md explains lane compatibility and the merge-order rule
created: '2026-09-09'
depends_on:
- US-PM-48
- US-PM-51
epic_id: EPIC-PM-7
id: US-PM-53
points: 8
priority: should
status: done
tags:
- orchestrator
- isolation
- throughput
title: 'Two-lane dispatch: orchestrator keeps two independent tasks in flight'
updated: '2026-09-09'
---

As the sprint orchestrator, I want to run up to two independent tasks at once in separate worktrees and validate one while the other's worker is still running, so that the orchestrator is active during worker waits instead of idle for the 20 to 100 minutes a long task takes, and a sprint finishes in roughly half the wall-clock time.

Independence is decided from the store, not from memory: two tasks are lane-compatible when neither depends on the other or on the other's story, they belong to different stories, and their stories are not connected by depends_on. The claim primitive already serialises grabs per task, and worker isolation (US-PM-51) keeps the two edit sets on separate branches, so the remaining work is scheduling and the merge order.

Changes: (1) pm_next accepts an exclude_conflicting_with=<task-id> argument (or pm_board exposes lane_compatible_with) that returns the next ready task independent of the given in-flight one; (2) the skill gains --lanes <1|2>, default 1, dispatching background Agents with the lane's worktree and tracking two in-flight claims by run id and lane; (3) while lane B runs, the orchestrator runs the validator subagent (US-PM-48) for lane A's returned work and merges the accepted branch; the second lane never dispatches a task whose dependency is still in flight; (4) merge conflicts on the second merge send that task to pm_retry with the conflict listed as evidence, once, then pm_park; (5) health check and --max count dispatches across both lanes; (6) orchestrate-design.md gets a section on lanes, why two and not more, and the merge-order rule.