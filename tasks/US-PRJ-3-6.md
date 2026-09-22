---
assignee: claude
created: '2026-02-17'
id: US-PRJ-3-6
points: 2
status: done
story_id: US-PRJ-3
title: Implement pm_push() with scope and validation
updated: '2026-02-19'
---

Add `pm_push(scope, root)` to `hub/registry.py`.

Scope options:
- `"hub"` — pushes hub repo (always on main)
- `"project:{name}"` — pushes a specific subproject (on its current branch)
- `"all"` — delegates to `coordinated_push()` from US-PRJ-4

Before pushing:
1. Run `validate_branches()` (US-PRJ-2) for the scoped projects
2. Run `validate_conventions()` (US-PRJ-9) for push operation
3. Abort with clear message if any validation fails

This is the simple, single-scope push. For multi-project coordination, `pm_push(scope='all')` delegates to US-PRJ-4's `coordinated_push()`.

Files: src/projectman/hub/registry.py