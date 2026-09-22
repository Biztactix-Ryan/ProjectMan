---
assignee: claude
created: '2026-08-22'
depends_on: []
id: US-PRJ-43-8
points: 1
status: done
story_id: US-PRJ-43
tags: []
title: Batch the pm_search tag filter and drop the redundant list_stories in pm_active
updated: '2026-08-22'
---

Two smaller N+1 sites in src/projectman/server.py.

1. pm_search: when a tag filter is given, the embeddings branch calls store.get(r.id) for each result. Replace with one store.list_stories() + one store.list_tasks() to build an {id: tags} map and filter results against it. Keep the behaviour that an id which no longer exists is silently dropped.

2. pm_active: the tag branch builds story_cache from a second store.list_stories() after already calling store.list_stories(status='active'). Fetch the full list once and derive the active subset from it (the acceptance criterion's 'line 252' is the pre-refactor location of this call).

Acceptance: existing pm_search and pm_active tests pass with identical output; no per-result store.get in pm_search tag filtering; a single list_stories call in pm_active.

Files: src/projectman/server.py (pm_search, pm_active).