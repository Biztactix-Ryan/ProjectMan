---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-46-5
points: 2
status: done
story_id: US-PM-46
tags: []
title: Remove the hub commands and the --hub and --project options from the CLI
updated: '2026-09-08'
---

In src/projectman/cli.py delete add-project, set-branch, sync and migrate-hub, the --hub flag on init (and its projects/ scaffold, architecture_hub.md.j2 render and _init_attach hub argument), and the --project option on the two commands that carry it. Delete src/projectman/templates/architecture_hub.md.j2. Remove hub-only comments and the add-project and migrate-hub attach paths in src/projectman/worktree.py, and hub references in scoper.py, store.py and errors.py. Update docs/reference/cli.md for the removed commands. Run tests/test_cli.py tests/test_init_attach.py tests/test_worktree*.py tests/test_migrate_worktree.py.