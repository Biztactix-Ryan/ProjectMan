---
acceptance_criteria:
- depends_on field added to TaskFrontmatter with [] default
- Field validator checks task ID format
- Topological sort produces correct ordering for chains and diamonds
- Cycle detection catches self-refs and multi-node cycles
- Backward compatible with existing tasks lacking depends_on
- All deps.py functions have unit tests
created: '2026-02-23'
epic_id: EPIC-PRJ-4
id: US-PRJ-21
points: 5
priority: must
status: done
tags: []
title: Core dependency model and graph algorithms
updated: '2026-03-01'
---

As a developer, I want task frontmatter to support a `depends_on` field and have core graph utilities so that dependencies can be stored, validated, and topologically sorted.

Covers: adding `depends_on: list[str]` to TaskFrontmatter in models.py, creating the new deps.py module with build_dep_graph, detect_cycle, topological_sort, incomplete_dependencies, and validate_dependencies functions.