---
acceptance_criteria:
- DECISIONS.md carries ADR-005 revising the stage-only model to per-task worktrees
  with commit-on-branch and no push
- The orchestrate skill dispatches each worker with worktree isolation on a branch
  named from the task id and run id
- The worker prompt has the worker commit its branch with code changes only and report
  the branch name
- On accept the orchestrator merges the task branch onto the run branch before the
  next dependent dispatch and the md5 snapshot steps are removed
- The Phase 4 report lists branches merged, unmerged and abandoned
created: '2026-09-09'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-51
points: 8
priority: should
status: done
tags:
- orchestrator
- isolation
title: 'ADR and worker isolation: each task in its own worktree with commit-on-branch'
updated: '2026-09-09'
---

As the sprint orchestrator, I want each worker to edit an isolated worktree on a per-task branch that it commits when done, so that two tasks' edits are physically separable and the orchestrator no longer relies on git status snapshots and md5 lists to tell one task's work from another's.

This revises the stage-only model in orchestrate-design.md, which chose one shared tree because sequential plus stage-only had no need for isolation. The trade-off to record in an ADR: a per-task branch means the run's product is a set of branches to merge rather than a diff to read, and a worker that starts from HEAD cannot see earlier tasks' uncommitted work, so the orchestrator must merge accepted work back onto the run branch before dispatching a dependent task. The Agent tool already offers isolation: worktree, and the pm-do skill's rules against checkout, restore, stash and reset still apply inside the worktree.

Changes: (1) ADR-005 in DECISIONS.md revising the stage-only model, keeping no-push and no pm_commit for the store; (2) the skill dispatches workers with isolation: worktree and a branch name carrying the task id and run id; (3) the worker prompt ends with committing its own branch (code only, never .project) and reporting the branch name; (4) the orchestrator's accept path merges the task branch onto the run branch (fast-forward or merge commit) and the step 14 snapshot and md5 list are dropped in favour of the branch diff; (5) the report lists branches merged, unmerged and abandoned. Sequential dispatch stays in this story; two lanes come in a later story that depends on it.