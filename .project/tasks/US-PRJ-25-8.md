---
assignee: claude
created: '2026-02-23'
id: US-PRJ-25-8
points: 1
status: done
story_id: US-PRJ-25
title: Add Depends On column to indexer
updated: '2026-03-01'
---

Add a Depends On column to the tasks markdown table in indexer.py.

## Implementation
- Edit `src/projectman/indexer.py` task table generation
- Add column header and data: comma-joined depends_on or '---'

## Definition of Done
- [ ] Column added to task table
- [ ] Shows deps or --- for none