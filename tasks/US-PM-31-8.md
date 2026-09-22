---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-31-7
id: US-PM-31-8
points: 3
status: done
story_id: US-PM-31
tags: []
title: projectman migrate-hub moves each .project/projects/{name} store onto its submodule's
  branch
updated: '2026-09-06'
---

New CLI command migrate-hub in cli.py backed by hub/migrate.py. For each name in config.projects with a .project/projects/{name} directory: refuse if the hub tree or the submodule tree is dirty (reuse worktree.dirty_paths); attach or create the submodule's projectman worktree as in the add-project task; copy the files across preserving bytes; commit on the projectman branch with a message naming the source; git rm the hub copy and commit on the hub. Print a per-project summary in the style of worktree.format_result. A run with nothing to migrate prints a friendly no-op. Push the branch when a remote exists unless --no-push.