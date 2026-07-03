---
assignee: claude
created: '2026-02-23'
id: US-PRJ-25-6
points: 1
status: done
story_id: US-PRJ-25
title: Update scoper guidance with depends_on
updated: '2026-03-01'
---

Add depends_on to decomposition guidance in scoper.py.

## Implementation
- Edit `src/projectman/scoper.py` scope() rules (~line 17): add rule about using depends_on
- Edit task_template (~line 24): add depends_on field
- Do the same in _auto_scope_full() and _auto_scope_incremental() guidance sections

## Definition of Done
- [ ] All three guidance sections updated
- [ ] Task template includes depends_on