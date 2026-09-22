---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-58-5
id: US-PRJ-58-6
points: 1
status: done
story_id: US-PRJ-58
tags: []
title: Widen sprint planned_stories and the ids params to lists and document both
  formats
updated: '2026-09-05'
---

Extend the _as_list normaliser from US-PRJ-58-5 to pm_create_sprint and pm_update_sprint planned_stories and to the ids params on pm_batch_get, pm_update_many and pm_archive_many. Document both accepted forms in each docstring and in docs/reference/mcp-tools.md. Changeset tools no longer exist; do not add them back.