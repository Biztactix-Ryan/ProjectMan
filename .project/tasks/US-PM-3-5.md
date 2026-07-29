---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-3-5
points: 2
status: done
story_id: US-PM-3
tags: []
title: Add a shared ID-alias resolver
updated: '2026-07-29'
---

One helper that accepts the generic id plus an optional typed alias (task_id, sprint_id), returns the resolved value, and raises a clear error when both are supplied with conflicting values. Applying it per tool should be close to one line each.