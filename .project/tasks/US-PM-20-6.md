---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-20-5
id: US-PM-20-6
points: 2
status: todo
story_id: US-PM-20
tags: []
title: Teach projectman init to detect origin/projectman and attach
updated: '2026-08-20'
---

In `projectman init`, before scaffolding a fresh store, check for an origin/projectman branch; when present, run the attach flow instead of creating new files, and say so in the output. Scaffolding behaviour is unchanged when the branch is absent.