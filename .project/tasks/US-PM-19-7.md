---
assignee: null
created: '2026-08-20'
depends_on: []
id: US-PM-19-7
points: 5
status: todo
story_id: US-PM-19
tags: []
title: Implement migrate-worktree command core
updated: '2026-08-20'
---

Add a `projectman migrate-worktree` CLI command (src/projectman/cli.py) that: creates an empty orphan `projectman` branch (empty root commit "ProjectMan root"), returns to the original branch, untracks .project on main (git rm -r --cached), appends `.project/` to .gitignore, commits on main, mounts the branch with `git worktree add .project projectman`, restores the stashed PM files, and commits them on the projectman branch. Stash the files to a temp location and never delete the stash until the worktree commit succeeds. Acceptance: .project ends mounted as a worktree on the orphan branch; main stops tracking it; all PM files survive intact.