---
acceptance_criteria:
- pm_board accepts optional tag filter and only shows matching items
- pm_search supports tag-based filtering
- pm_active accepts optional tag filter
- Tags are included in search embedding text for semantic relevance
created: '2026-02-17'
epic_id: EPIC-PRJ-2
id: US-PRJ-14
points: 5
priority: should
status: done
tags: []
title: Add tag filtering to board search and active queries
updated: '2026-03-01'
---

As a user working in a large hub project, I want to filter the board, search results, and active items by tag so I can focus on work related to a specific system (e.g. show only API1 tasks). Add an optional `tag` filter parameter to pm_board, pm_search, and pm_active.