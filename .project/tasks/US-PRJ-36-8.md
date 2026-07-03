---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-36-8
points: 1
status: todo
story_id: US-PRJ-36
tags: []
title: Add depends_on deduplication in TaskFrontmatter validator
updated: '2026-03-06'
---

In models.py validate_depends_on(), deduplicate entries before returning. E.g. depends_on=['A','A'] becomes ['A']. Add test confirming dedup behavior.