---
acceptance_criteria:
- Scoper guidance includes depends_on in rules and template
- Audit detects dependency cycles as error
- Audit detects orphaned dependency references as warning
- Index task table includes Depends On column
- All three modules updated with minimal changes
created: '2026-02-23'
epic_id: EPIC-PRJ-4
id: US-PRJ-25
points: 3
priority: should
status: done
tags: []
title: Scoper guidance and audit and indexer updates
updated: '2026-03-01'
---

As a user, I want scoping guidance to teach about depends_on, audits to catch dependency issues, and the index to show deps so that the full system is dependency-aware.

Covers: updating scoper.py guidance rules and task_template, adding cycle and orphan audit checks in audit.py, and adding Depends On column to indexer.py task table.