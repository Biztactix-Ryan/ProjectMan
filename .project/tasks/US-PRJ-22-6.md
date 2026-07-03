---
assignee: claude
created: '2026-02-23'
id: US-PRJ-22-6
points: 2
status: done
story_id: US-PRJ-22
title: Wire depends_on through create_task
updated: '2026-03-01'
---

Add `depends_on: Optional[list[str]] = None` parameter to `store.create_task()`. Before creating the TaskFrontmatter, validate with `deps.validate_dependencies()` if depends_on is provided. Pass to TaskFrontmatter constructor.

## Implementation
- Edit `src/projectman/store.py` create_task() (~line 289)
- Add param, import validate_dependencies, call validation, pass to constructor

## Testing
- Test create_task with valid depends_on
- Test create_task with invalid depends_on (self-ref, non-sibling) raises ValueError

## Definition of Done
- [ ] Parameter added
- [ ] Validation integrated
- [ ] Tests pass