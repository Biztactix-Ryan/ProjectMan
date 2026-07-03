---
assignee: claude
created: '2026-02-23'
id: US-PRJ-25-7
points: 2
status: done
story_id: US-PRJ-25
title: Add dependency audit checks
updated: '2026-03-01'
---

Add two new audit checks to audit.py: dependency cycle detection (error) and orphaned dependency references (warning).

## Implementation
- Edit `src/projectman/audit.py` run_audit()
- Import build_dep_graph, detect_cycle from deps
- Check each story's tasks for cycles (error severity)
- Check each task's depends_on for IDs not in sibling set (warning severity)

## Definition of Done
- [ ] Cycle check added (error)
- [ ] Orphan check added (warning)
- [ ] Tests pass