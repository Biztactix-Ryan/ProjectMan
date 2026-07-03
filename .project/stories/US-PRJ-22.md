---
acceptance_criteria:
- create_task accepts depends_on param and validates
- create_tasks batch supports depends_on per entry with cycle check
- update validates depends_on for tasks and rejects cycles
- Invalid deps (self-ref or non-sibling or cycle) raise ValueError
- Store tests cover all validation cases
created: '2026-02-23'
epic_id: EPIC-PRJ-4
id: US-PRJ-22
points: 5
priority: must
status: done
tags: []
title: Store layer dependency support
updated: '2026-03-01'
---

As a developer, I want create_task, create_tasks, and update to accept and validate depends_on so that dependencies are persisted to frontmatter and validated at write time.

Covers: wiring depends_on through store.create_task(), store.create_tasks() (with post-batch cycle check and rollback), and store.update() with validation.