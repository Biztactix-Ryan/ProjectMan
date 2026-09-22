---
assignee: claude
created: '2026-02-23'
id: US-PRJ-23-7
points: 3
status: done
story_id: US-PRJ-23
title: Add topological sort to pm_board ordering
updated: '2026-03-01'
---

In `server.py` pm_board(), replace the task ID component of the `_sort` key with a topological order position. Group all todo tasks by story, run `topological_sort()` per story group to build a position map, then use `(story_priority, story_id, topo_position, points)` as the sort key.

## Implementation
- Edit `src/projectman/server.py` pm_board() (~line 266)
- Import topological_sort, CycleError from deps
- Before the main loop, build topo_order: dict[task_id, int]
- Replace task.id in _sort tuple with topo_order.get(task.id, 99)
- Handle CycleError gracefully (fallback to original order)

## Testing
- Board with A->B->C returns in that order
- Board with no deps preserves ID order
- Board with cycle in one story doesn't crash

## Definition of Done
- [ ] Board uses topological ordering
- [ ] Graceful cycle fallback
- [ ] Tests pass