---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-49-5
points: 2
status: done
story_id: US-PM-49
tags: []
title: Add brief and fields projections to pm_board
updated: '2026-09-09'
---

pm_board in server.py gains `brief: bool = False` and `fields: Optional[str] = None`, reusing _brief_item, _field_names and _reject_unknown_fields the way pm_batch_get and pm_list_sprints already do. brief keeps id, title, status, assignee, points, depends_on, claimed_by_run, claim_age and stale for each row, drops bodies and criteria. Add cases to tests/test_brief_mode.py and tests/test_field_projection.py. pm_batch_get and pm_list_sprints already project; this task only adds the board.