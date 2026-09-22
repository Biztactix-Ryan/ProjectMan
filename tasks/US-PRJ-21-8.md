---
assignee: claude
created: '2026-02-23'
id: US-PRJ-21-8
points: 5
status: done
story_id: US-PRJ-21
title: Create deps.py with graph algorithms
updated: '2026-03-01'
---

Create new module `src/projectman/deps.py` with core dependency graph utilities:

## Implementation
- `CycleError(ValueError)` — exception with cycle path
- `build_dep_graph(tasks: list[TaskFrontmatter]) -> dict[str, list[str]]` — adjacency list, drops unknown IDs
- `detect_cycle(graph) -> list[str] | None` — DFS with WHITE/GRAY/BLACK coloring
- `topological_sort(tasks) -> list[TaskFrontmatter]` — Kahn's algorithm, stable by task ID within depth levels, raises CycleError
- `incomplete_dependencies(task, siblings) -> list[str]` — returns depends_on IDs not done
- `validate_dependencies(task_id, depends_on, story_id, siblings) -> list[str]` — returns error strings for self-ref, non-sibling, would-create-cycle

## Testing
- Unit tests in tests/test_deps.py covering:
  - Empty tasks, no deps, simple chain (A->B->C), diamond, drops unknown IDs
  - No cycle, self-cycle, 2-node cycle, 3-node cycle
  - Linear chain ordering, diamond ordering, cycle raises
  - All done, some incomplete, unknown dep
  - Valid deps, self-reference, non-sibling, would-create-cycle

## Definition of Done
- [ ] All 6 functions implemented
- [ ] CycleError exception class
- [ ] test_deps.py with full coverage