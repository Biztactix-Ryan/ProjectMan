---
acceptance_criteria:
- Story ID regex enforces US-PREFIX-N pattern
- Task ID regex enforces US-PREFIX-N-N pattern
- Epic ID regex enforces EPIC-PREFIX-N pattern
- Existing valid IDs all pass new validation
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-50
points: 3
priority: should
status: done
tags:
- quality
- models
title: Enforce strict ID format patterns in models
updated: '2026-09-05'
---

As a developer, I want ID format validation to enforce the actual patterns used so that invalid IDs are caught at creation time. Currently models.py uses a permissive regex ^[A-Za-z][\w-]*$ that accepts anything. Stories should match US-PREFIX-N, tasks US-PREFIX-N-N, epics EPIC-PREFIX-N.

Planning note (2026-09-05): the changeset ID criterion was dropped because US-PM-27 removed changesets from the package in Sprint 8. models.py now has six permissive-regex sites (lines 91, 99, 129, 199, 209, 239) covering story, task, epic ids and depends_on entries.