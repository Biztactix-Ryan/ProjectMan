---
assignee: claude
created: '2026-08-20'
depends_on:
- US-PM-19-7
id: US-PM-20-5
points: 3
status: done
story_id: US-PM-20
tags: []
title: Implement projectman attach command
updated: '2026-09-01'
---

Add `projectman attach` (src/projectman/cli.py): on a clone with origin/projectman, run `git worktree add .project projectman` creating the local branch from the remote. Idempotent: friendly no-op message when the worktree is already mounted. Clobber-safe: when .project exists as a plain directory with content (e.g. an unmigrated store), fail with an actionable message (suggest migrate-worktree or manual cleanup) — never overwrite. Depends cross-story on the migration layout from US-PM-19-7.