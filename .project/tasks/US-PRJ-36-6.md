---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-36-6
points: 1
status: todo
story_id: US-PRJ-36
tags: []
title: Add changeset caching following stories/epics/tasks pattern
updated: '2026-03-06'
---

Add changeset cache to store.py following the same module-level dict pattern. Populate on list_changesets(), update on create/update, invalidate on archive. Include archived exclusion.