---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-51-6
points: 3
status: done
story_id: US-PM-51
tags: []
title: Write ADR-005 revising the stage-only model to per-task worktrees
updated: '2026-09-09'
---

Add ADR-005 at the top of .project/DECISIONS.md: each orchestrated task runs in its own git worktree on branch orch/<run-id>/<task-id>, the worker commits code there, the orchestrator merges accepted branches onto a run branch orch/<run-id> cut from HEAD, nothing is pushed, and the .project store is never committed by a run. Record the consequences: the run's product is a run branch to review and merge instead of a diff; a worker starts from the run branch and cannot see unmerged work, so dependent tasks wait for the merge; the worktree carries no .project mount (it is gitignored on main) so all store access goes through the MCP tools against the primary checkout; parked tasks leave their branch for a human. Rewrite the Stage-only model section of docs/reference/orchestrate-design.md to point at ADR-005 and replace the "no branches, no worktrees" bullets with an Isolation model section.