---
created: '2026-02-23'
id: EPIC-PRJ-4
points: null
priority: must
status: done
tags:
- core
- v0.8
target_date: null
title: Task Dependency System
updated: '2026-03-01'
---

Add a `depends_on` field to task frontmatter enabling tasks within a story to declare execution-order dependencies on sibling tasks. This enables topological ordering on the board, dependency-aware readiness checks (blocking grab of tasks with incomplete prerequisites), cycle detection, and proper waterfall execution ordering.

## Success Criteria
- Tasks can declare `depends_on: [sibling-task-ids]` in frontmatter
- `pm_board` returns tasks in topological (dependency) order
- `pm_grab` blocks when prerequisite tasks aren't done
- Cycle detection prevents invalid dependency graphs
- Backward compatible — existing tasks without depends_on still work
- Scoping guidance teaches agents to use depends_on

## Scope
- Dependencies are within a story only (no cross-story deps)
- New `deps.py` module for graph algorithms (topo sort, cycle detection)
- Integrates with readiness, board, grab, create, update, audit, index, web API