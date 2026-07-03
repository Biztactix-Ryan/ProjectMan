---
assignee: claude
created: '2026-02-17'
id: US-PRJ-10-9
points: 2
status: done
story_id: US-PRJ-10
title: Add changeset status to git status dashboard
updated: '2026-02-19'
---

Extend `git_status_all()` (US-PRJ-8-5) to include changeset context.

For each subproject in the dashboard, if it's part of an active changeset:
- Show changeset name and overall status
- Show this project's PR state within the changeset
- Flag if this project's PR is merged but others aren't (hub ref blocked)

Dashboard output addition:
```
  Project  Branch         Deploy  PRs  Changeset
  api      pm/CS-1/auth   main    1    auth-v2 (2/3 merged, waiting on worker)
  web      pm/CS-1/auth   main    1    auth-v2 (2/3 merged, waiting on worker)
  worker   pm/CS-1/auth   main    1    auth-v2 (2/3 merged, THIS PR open)
```

Also add a standalone `projectman changeset-status [name]` CLI command.

Files: src/projectman/hub/registry.py, src/projectman/cli.py