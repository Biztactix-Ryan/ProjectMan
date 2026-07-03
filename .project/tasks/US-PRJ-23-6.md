---
assignee: claude
created: '2026-02-23'
id: US-PRJ-23-6
points: 2
status: done
story_id: US-PRJ-23
title: Add dependency blocker to readiness checks
updated: '2026-03-01'
---

In `readiness.py` check_readiness(), after the parent story check (~line 36), call `deps.incomplete_dependencies(task_meta, siblings)` and if non-empty, append a hard blocker: `depends on incomplete task(s): ID1, ID2`.

## Implementation
- Edit `src/projectman/readiness.py` check_readiness()
- Import incomplete_dependencies from deps
- Get sibling tasks via store.list_tasks(story_id=task_meta.story_id)
- Check and append blocker

## Testing
- Task with all deps done passes readiness
- Task with incomplete dep fails readiness with correct blocker message

## Definition of Done
- [ ] Dependency check added as hard blocker
- [ ] Tests pass