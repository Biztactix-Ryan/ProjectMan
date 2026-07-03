---
assignee: null
created: '2026-02-17'
id: US-PRJ-9-9
points: 2
status: todo
story_id: US-PRJ-9
title: Wire convention checks into existing operations
updated: '2026-02-17'
---

Integrate validate_conventions() as guardrails into existing and planned operations.

1. `create_feature_branch()` (US-PRJ-7-7) — validate branch name matches convention before creating
2. `create_pr()` (US-PRJ-7-8) — validate not on deploy branch, branch name is conventional
3. `sync()` — exempt from branch convention (it operates on deploy branch by design)
4. `validate_branches()` (US-PRJ-2-4) — add convention compliance to its output (is branch named correctly?)

For each integration point:
- On violation with severity=error: abort with clear message
- On violation with severity=warning: log warning, continue

Also add a standalone CLI command: `projectman check-conventions` that runs all checks across all subprojects and reports a summary table.

Files: src/projectman/hub/registry.py, src/projectman/cli.py