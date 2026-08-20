---
assignee: claude
created: '2026-08-20'
depends_on: []
id: US-PM-18-6
points: 3
status: done
story_id: US-PM-18
tags: []
title: Switch acceptance_criteria params to list input in pm_create_story and pm_update
updated: '2026-08-20'
---

In src/projectman/server.py change the acceptance_criteria parameter on pm_create_story (line ~1029) and pm_update (line ~1412) from Optional[str] to accept a JSON list (list[str], matching web/schemas.py; optionally Union[str, list[str]] where a bare string is ONE criterion). Remove the .split(",") calls at lines ~1050 and ~1481-1483. Update both docstrings to stop instructing comma-separated criteria. Preserve the pm_update test-task reconciliation path unchanged (kwargs["acceptance_criteria"] still a list). Leave tags/depends_on comma-splitting as is — commas are never legitimate in IDs/slugs.