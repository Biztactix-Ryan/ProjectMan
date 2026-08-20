---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-19-7
id: US-PM-21-7
points: 5
status: todo
story_id: US-PM-21
tags: []
title: 'Integration tests: pm git ops against a worktree-mounted .project'
updated: '2026-08-20'
---

Build a test fixture that sets up a repo with .project mounted as a worktree on an orphan projectman branch (reuse migrate-worktree from US-PM-19-7 or replicate its layout directly). Prove: pm_commit lands commits on the projectman branch and leaves main clean; pm_push pushes only the projectman branch; pm_git_status reports the worktree's branch/dirty/ahead-behind state distinctly from main's. Fix any code that fails — the zero-code-change hypothesis from ADR-001 is verified here, not assumed.