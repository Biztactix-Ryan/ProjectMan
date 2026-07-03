---
acceptance_criteria:
- TaskFrontmatter has tags field with default empty list
- IndexEntry includes optional tags field
- Existing task files without tags still load without errors
created: '2026-02-17'
epic_id: EPIC-PRJ-2
id: US-PRJ-12
points: 2
priority: must
status: done
tags: []
title: Add tags field to Task data model
updated: '2026-02-17'
---

As a developer, I want tasks to support tags so that I can categorize work items by system/domain (e.g. API1, Frontend). Currently TaskFrontmatter in models.py is the only item type missing a `tags: list[str] = []` field. Also add `tags` to IndexEntry so tags are available in indexes.