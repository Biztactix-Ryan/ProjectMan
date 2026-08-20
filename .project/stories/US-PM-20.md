---
acceptance_criteria:
- projectman attach mounts the projectman branch as the .project worktree on a fresh
  clone
- projectman init detects origin/projectman and attaches instead of scaffolding a
  new store
- Attach is a friendly no-op when the worktree is already mounted
- Attach fails with an actionable message when .project holds untracked content instead
  of clobbering it
created: '2026-08-20'
depends_on:
- US-PM-19
epic_id: EPIC-PM-3
id: US-PM-20
points: 5
priority: should
status: backlog
tags:
- git
- storage
- cli
- dx
title: 'Attach on clone: auto-mount the projectman branch in init plus an attach command'
updated: '2026-08-20'
---

As a developer on a fresh clone, I want the PM data to appear without manual git worktree commands so that clones stay zero-friction.

A fresh clone of a migrated repo has origin/projectman but an empty .project. Add a `projectman attach` command that runs `git worktree add .project projectman` (creating the local branch from origin/projectman), and teach `projectman init` to detect origin/projectman and attach automatically instead of scaffolding a fresh store. Attach must be idempotent: a no-op with a friendly message when the worktree is already mounted, and a clear actionable error when .project exists as a plain directory with content (e.g. an unmigrated store) rather than silently clobbering it.