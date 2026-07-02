---
name: pm-plan
description: Plan the next sprint — close out the previous one, size to velocity, pick and scope stories, set a goal, and activate. Use when the user says "plan the sprint", "what should we do next", or wants to organize upcoming work.
---

# /pm-plan — Sprint Planning

A sprint is the unit of orchestrated work: `/pm-orchestrate` drives the *active* sprint, so planning well here is what makes autonomous execution work. Every sprint needs a goal, dates, a story list sized to velocity, and fully scoped stories.

## Phase 1 — Close out the previous sprint

1. `pm_list_sprints(status="active")`:
   - **Active sprint past its end date** → it must be closed before planning a new one. Show what completed vs. planned, then `pm_update_sprint(id, status="completed")`. Unfinished stories roll back to the backlog (note them — they're prime candidates for the new sprint).
   - **Active sprint still in-date** → stop and ask: continue it (suggest `/pm-orchestrate`) or close it early?
   - **No active sprint** → proceed.
2. Compute velocity from history: `pm_list_sprints(status="completed")` — average completed points over the last 2–3 sprints. No history → plan conservatively and say so.

## Phase 2 — Assess the backlog

3. `pm_status` for current state, `pm_audit` for drift (resolve ERROR-level findings before planning — especially dependency cycles), `pm_active` for in-flight work, `pm_burndown` for trend.
4. List backlog stories by priority. Order candidates by the dependency graph:
   - Stories others depend on come first; never plan a story without its dependency stories.
   - Visualize the chain when it matters: "US-PRJ-3 depends on US-PRJ-2 which depends on US-PRJ-1".

## Phase 3 — Select and scope to capacity

5. Propose a **sprint goal** — one sentence describing the outcome, not a list of tickets. Ask the user to confirm or edit it.
6. Select stories whose summed points fit the velocity from step 2. Say explicitly when you're leaving something out for capacity reasons — an honest sprint beats an aspirational one.
7. Scoping gate — every selected story must be executable:
   - Check audit findings for `missing-implementation-tasks`; for flagged stories call `pm_auto_scope` and create the proposed tasks on approval.
   - For each undecomposed story: `pm_scope(story_id)`, propose a task breakdown with `depends_on` (intra- and cross-story), `pm_estimate(id)` per task, create on approval.
   - A story still lacking tasks or estimates does not enter the sprint.

## Phase 4 — Persist and activate

8. `pm_create_sprint` with name, goal, start/end dates, and the planned story IDs.
9. Set it active (`pm_update_sprint(id, status="active")`) unless the user wants to start later.
10. Summarize: sprint ID, goal, stories with points vs. velocity, dependency order, and flagged risks (cross-sprint dependencies, unestimated leftovers).
11. Suggest the natural next step: "Run it with `/pm-orchestrate`" or "grab the first task with `/pm-do <id>`".

## Cross-Story Dependency Planning

- **Order stories by dependencies** — prerequisites first.
- **Flag cross-story task deps** — tasks depending on other stories' tasks constrain execution order inside the sprint.
- **Never plan a story whose dependency is neither done nor in the sprint** — under orchestration it can never become ready.

Example output:
```
Sprint 12 — "Agents can claim tasks safely" (2026-07-06 → 2026-07-17)
Velocity: 21 pts (avg of last 3) | Planned: 19 pts

1. US-PRJ-1 (5 pts, no deps) — Atomic claim in store
2. US-PRJ-2 (8 pts, depends on US-PRJ-1) — Grab uses claim API
3. US-PRJ-4 (6 pts, depends on US-PRJ-1) — Stale-claim reclamation
Left out for capacity: US-PRJ-7 (8 pts)
```
