---
assignee: claude
created: '2026-02-23'
id: US-PRJ-24-7
points: 2
status: done
story_id: US-PRJ-24
title: Add depends_on to MCP tool signatures
updated: '2026-03-01'
---

Add `depends_on: Optional[str] = None` (comma-separated task IDs) to pm_create_task and pm_update in server.py. Parse to list with `[d.strip() for d in depends_on.split(',') if d.strip()]`. Update pm_create_tasks docstring to document the optional depends_on key.

## Implementation
- Edit `src/projectman/server.py` pm_create_task() (~line 621)
- Edit `src/projectman/server.py` pm_update() (~line 673)
- Edit `src/projectman/server.py` pm_create_tasks() (~line 647) docstring only

## Testing
- Test pm_create_task with depends_on param
- Test pm_update with depends_on param

## Definition of Done
- [ ] pm_create_task accepts depends_on
- [ ] pm_update accepts depends_on
- [ ] pm_create_tasks docstring updated
- [ ] Tests pass