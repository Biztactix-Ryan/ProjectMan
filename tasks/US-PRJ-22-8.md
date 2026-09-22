---
assignee: claude
created: '2026-02-23'
id: US-PRJ-22-8
points: 2
status: done
story_id: US-PRJ-22
title: Wire depends_on through update
updated: '2026-03-01'
---

In `store.update()`, when the item is a task and `depends_on` is in kwargs, validate the proposed deps with `validate_dependencies()` before writing to disk.

## Implementation
- Edit `src/projectman/store.py` update() (~line 401)
- After applying kwargs to post.metadata, check if is_task and depends_on present
- Run validate_dependencies, raise ValueError if errors

## Testing
- Test updating task depends_on to valid sibling
- Test updating task depends_on that would create cycle raises ValueError

## Definition of Done
- [ ] Validation added for task depends_on updates
- [ ] Tests pass