---
acceptance_criteria:
- Running the migration leaves .project mounted as a worktree on an orphan projectman
  branch
- main stops tracking .project and gains a .gitignore entry for it
- All existing PM files survive the migration intact
- Migration refuses to run on a dirty working tree
- Migration refuses when a projectman branch already exists and points at attach
- The projectman branch is pushed to origin when a remote exists
created: '2026-08-20'
depends_on: []
epic_id: EPIC-PM-3
id: US-PM-19
points: 8
priority: should
status: done
tags:
- git
- storage
- cli
title: 'Migration command: move .project onto an orphan projectman branch worktree'
updated: '2026-09-01'
---

As a ProjectMan user, I want a one-time `projectman migrate-worktree` command so that .project/ moves onto a dedicated orphan branch mounted as a worktree without me hand-running the git incantation.

Steps it automates (from EPIC-PM-3): create empty orphan branch `projectman` (empty root commit, push -u when a remote exists), untrack .project on main (`git rm -r --cached`), append `.project/` to .gitignore, commit on main, `git worktree add .project projectman`, restore the PM files, commit and push on the projectman branch. Snapshot import is the default; note in help text that `git filter-repo --subdirectory-filter .project` is the history-preserving alternative for those who want it.

Safety: refuse on a dirty working tree; refuse if a `projectman` branch already exists (point at `projectman attach` instead); never delete the stashed copy until the worktree commit succeeds.