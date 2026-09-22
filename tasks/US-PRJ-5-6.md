---
assignee: claude
created: '2026-02-17'
id: US-PRJ-5-6
points: 3
status: done
story_id: US-PRJ-5
title: Add auto-commit hook into store.py mutation methods
updated: '2026-02-20'
---

Wire auto-commit into the store layer so PM mutations trigger commits.

In `src/projectman/store.py`, after each mutation that writes files:
1. Check `config.auto_commit` — if False, return as normal
2. Collect the list of files that were just written/modified by the mutation
3. `git add` only those specific files (never `git add .`)
4. Generate commit message using convention helper from US-PRJ-9-8: `pm: {action} {id}` (e.g. `pm: create US-PRJ-5`, `pm: update US-PRJ-3-1 status=done`)
5. `git commit -m {message}`
6. Log the commit sha (debug level)

Mutations to hook into:
- `create_story()` / `update_story()`
- `create_task()` / `update_task()`
- `create_epic()` / `update_epic()`
- `archive()`
- Index rebuild (if it modifies index.yaml)

Do NOT auto-push. The commit is local only.

Handle: git not available (warn, skip), not a git repo (warn, skip), commit fails (warn, don't crash the mutation).

Files: src/projectman/store.py