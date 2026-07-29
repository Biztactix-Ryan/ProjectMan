---
assignee: null
created: '2026-07-29'
depends_on:
- US-PM-12-6
- US-PM-12-7
id: US-PM-12-8
points: null
status: todo
story_id: US-PM-12
tags: []
title: Define partial-failure semantics
updated: '2026-07-29'
---

A bulk call touching 50 items where 3 fail must report which succeeded and which did not, without rolling back the successes or hiding the failures. Applies to both new verbs.