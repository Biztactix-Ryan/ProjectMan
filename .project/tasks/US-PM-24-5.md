---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-24-5
points: 1
status: done
story_id: US-PM-24
tags: []
title: Story and epic ID allocation takes the max of the config counter and what is
  on disk
updated: '2026-09-05'
---

In src/projectman/store.py `_next_story_id` (~line 553) and `_next_epic_id`: scan the stories (epics) directory for `US-<prefix>-<n>.md` / `EPIC-<prefix>-<n>.md`, take the highest n, and allocate max(config.next_story_id, highest+1). Persist the new counter as today. Re-read config.yaml from disk before computing so a second live Store sees the first one's increment. Add a unit test in tests/test_store.py that constructs two Stores on the same tmp project, creates a story with each, and asserts two files with distinct IDs exist.