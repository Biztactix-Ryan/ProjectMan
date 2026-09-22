---
assignee: claude
created: '2026-02-23'
id: US-PRJ-22-7
points: 2
status: done
story_id: US-PRJ-22
title: Wire depends_on through create_tasks batch
updated: '2026-03-01'
---

Update `store.create_tasks()` to read optional `depends_on` from each task dict. After all tasks are created, run a post-batch cycle check across all siblings. If cycle detected, delete the newly created files and raise ValueError.

## Implementation
- Edit `src/projectman/store.py` create_tasks() (~line 328)
- Read `entry.get('depends_on', [])` and pass to TaskFrontmatter
- After creation loop, build graph of all siblings, detect_cycle, rollback if found

## Testing
- Test batch creation with valid cross-deps between new tasks
- Test batch creation that would create a cycle rolls back

## Definition of Done
- [ ] depends_on read from each entry
- [ ] Post-batch cycle detection
- [ ] Rollback on cycle
- [ ] Tests pass