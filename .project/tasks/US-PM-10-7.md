---
assignee: null
created: '2026-07-29'
depends_on: []
id: US-PM-10-7
points: 2
status: todo
story_id: US-PM-10
tags: []
title: Add a brief mode to pm_batch_get and pm_list_sprints
updated: '2026-07-29'
---

Both are list-everything calls with no projection. Study D measured pm_batch_get(type=stories) at 37,593 chars and pm_list_sprints(status=completed) at 27,079 chars, both dumping full bodies and acceptance criteria.

Study D rates this the best byte-saved-per-line-of-code available, worth roughly 400 KB across her corpus.