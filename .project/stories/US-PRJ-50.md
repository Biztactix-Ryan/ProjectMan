---
acceptance_criteria:
- Story ID regex enforces US-PREFIX-N pattern
- Task ID regex enforces US-PREFIX-N-N pattern
- Epic ID regex enforces EPIC-PREFIX-N pattern
- Changeset ID regex enforces CS-PREFIX-N pattern
- Existing valid IDs all pass new validation
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-50
points: 3
priority: should
status: backlog
tags:
- quality
- models
title: Enforce strict ID format patterns in models
updated: '2026-03-09'
---

As a developer, I want ID format validation to enforce the actual patterns used so that invalid IDs are caught at creation time. Currently models.py uses a permissive regex ^[A-Za-z][\\w-]*$ that accepts anything. Stories should match US-PREFIX-N, tasks US-PREFIX-N-N, epics EPIC-PREFIX-N, changesets CS-PREFIX-N.