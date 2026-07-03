---
acceptance_criteria:
- store.py _check_dependency_cycles uses deps.py detect_cycle()
- Cycle errors show full path (A -> B -> C -> A) everywhere
- validate_dependencies() either removed or integrated into store layer
- All existing tests pass
- No new test regressions
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-29
points: 3
priority: must
status: done
tags:
- tier-1
- dependencies
title: Consolidate cycle detection and clean up dead code in deps
updated: '2026-03-09'
---

As a developer, I want a single cycle detection implementation so that error messages are consistent and there's no redundant code to maintain. Currently deps.py and store.py both implement cycle detection with different error reporting (full path vs partial edge). Additionally, validate_dependencies() in deps.py is defined but never called in production.