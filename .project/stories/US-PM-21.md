---
acceptance_criteria:
- pm_commit lands commits on the projectman branch without dirtying main
- pm_push pushes only the projectman branch
- pm_git_status reports the .project worktree state distinctly from main
- Hub mode introduces no submodule-pointer noise in the parent repo
- Docs cover git clean behaviour and the ignored-but-precious nature of .project
- Docs describe the private sibling-repo variant for public repos
created: '2026-08-20'
depends_on:
- US-PM-19
epic_id: EPIC-PM-3
id: US-PM-21
points: 8
priority: should
status: backlog
tags:
- git
- storage
- mcp
- docs
title: 'Worktree compatibility: verify pm git ops against a worktree-mounted .project
  and document the rough edges'
updated: '2026-08-20'
---

As a ProjectMan maintainer, I want pm_commit / pm_push / pm_git_status proven correct when .project is a worktree so that the migration is safe to recommend.

The hypothesis from EPIC-PM-3 is that git commands run inside .project automatically target the projectman branch, so the existing shell-out code may need zero changes — but that must be verified with tests, not assumed. Cover: pm_commit commits land on the projectman branch and never dirty main; pm_push pushes only that branch; pm_git_status reports the worktree's branch/dirty/ahead-behind state sensibly rather than conflating it with main's; hub mode does not regress (and specifically, no submodule-pointer noise is introduced in the parent repo).

Documentation of the rough edges: `git clean -fdx` won't recurse into the worktree without -ff but .project is now ignored-but-precious; fresh clones need attach (US-PM-20); the projectman branch is visible on public repos, with the sibling <repo>-pm private-repo variant described for that case.