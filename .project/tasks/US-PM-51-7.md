---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-51-6
id: US-PM-51-7
points: 3
status: done
story_id: US-PM-51
tags: []
title: Dispatch workers into worktrees on per-task branches
updated: '2026-09-09'
---

skill_pm_orchestrate.md.j2: Phase 0 creates the run branch `orch/<run-id>` from HEAD (fail the run if the working tree is dirty outside .project, since the branch must start from a known point; report the dirty list). Step 15 spawns the worker Agent with `isolation: "worktree"` and instructs it to work on branch orch/<run-id>/<task-id> cut from the run branch. Worker prompt: at the end, `git add -A` of code paths only, never .project, one commit titled with the task id, and report the branch name and commit sha in the fixed report shape. Retries reuse the same branch.