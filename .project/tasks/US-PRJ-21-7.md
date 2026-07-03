---
assignee: claude
created: '2026-02-23'
id: US-PRJ-21-7
points: 1
status: done
story_id: US-PRJ-21
title: Add depends_on field to TaskFrontmatter
updated: '2026-03-01'
---

Add `depends_on: list[str] = []` field to TaskFrontmatter in models.py after the `tags` field. Add a `@field_validator('depends_on')` that checks each entry matches the existing task ID regex `^[A-Za-z][\w-]*$`. The empty list default ensures backward compatibility with existing task files (same pattern as `tags`).

## Implementation
- Edit `src/projectman/models.py` TaskFrontmatter class (~line 109)
- Add field: `depends_on: list[str] = []`
- Add validator matching the existing `validate_id` pattern

## Testing
- Verify existing tests still pass (backward compat)
- Test that invalid IDs in depends_on raise ValidationError

## Definition of Done
- [ ] Field added with default
- [ ] Validator added
- [ ] Existing tests pass