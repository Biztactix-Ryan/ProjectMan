---
assignee: claude
created: '2026-02-17'
id: US-PRJ-4-9
points: 3
status: done
story_id: US-PRJ-4
title: Implement coordinated_push() orchestrator and CLI command
updated: '2026-02-20'
---

Add `coordinated_push(projects=None, dry_run=False, root)` that orchestrates the full workflow and expose via CLI.

**Orchestration** (hub/registry.py):
1. Discover dirty projects (or use explicit list if provided)
2. Run `push_preflight()` — abort if can_proceed=False, show all blockers
3. If `dry_run=True`: print what WOULD happen and exit
4. Run `push_subprojects()` — stop on first failure
5. If all subprojects pushed: run `push_hub()`
6. Print final report:
```
Coordinated Push Results

  Preflight:  5 ready, 0 blocked
  Subprojects:
    api       pm/US-1/auth  → origin  a1b2c3d  ✓
    web       pm/US-2/dash  → origin  d4e5f6g  ✓
    worker    (clean, skipped)
  Hub:
    main  → origin  h7i8j9k  ✓  (updated api, web refs)

  Result: 2 projects pushed, hub updated.
```

**CLI** (cli.py):
- `projectman push [--dry-run] [--projects api,web]`
- `--dry-run` shows plan without executing
- `--projects` limits to specific subprojects (default: all dirty)

**MCP** (server.py):
- Register `pm_push_all` tool
- Include dry_run parameter

Files: src/projectman/hub/registry.py, src/projectman/cli.py, src/projectman/server.py