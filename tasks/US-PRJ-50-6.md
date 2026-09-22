---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on: []
id: US-PRJ-50-6
points: 2
status: done
story_id: US-PRJ-50
tags: []
title: Define strict ID regex constants and wire them into the six model validators
updated: '2026-09-05'
---

In src/projectman/models.py replace the permissive ^[A-Za-z][\w-]*$ used at seven sites (story id ~L91, story depends_on ~L99, epic id ~L129, task id ~L199, task depends_on ~L209, sprint id ~L239, changeset id ~L273) with module-level compiled constants. Prefix charset is uppercase alphanumeric (cli.py:123 default PRJ, hub/registry.py:199 derives clean[:3].upper()): PREFIX = r'[A-Z][A-Z0-9]*'. STORY_ID ^US-PREFIX-\d+$, TASK_ID ^US-PREFIX-\d+-\d+$, EPIC_ID ^EPIC-PREFIX-\d+$, SPRINT_ID ^SPRINT-PREFIX-\d+$, CHANGESET_ID ^CS-PREFIX-\d+$. Story depends_on accepts STORY_ID or TASK_ID (the pm_create_story docstring says stories or tasks); task depends_on accepts TASK_ID only. Keep error messages descriptive and show the expected pattern. Export the constants so store.py/_resolve_id can reuse them.