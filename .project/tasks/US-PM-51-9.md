---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-51-7
id: US-PM-51-9
points: 1
status: done
story_id: US-PM-51
tags: []
title: Update the pm-do worker rules for running inside a worktree
updated: '2026-09-09'
---

skill_pm_do.md.j2: the worker's cwd may be a worktree on a task branch; the rules against git checkout, restore, stash, reset and clean still hold; do not switch branches; commit only when the dispatch prompt says so and only code paths; the store is reached through the pm tools, never through a .project directory. Keep the file under its current size.