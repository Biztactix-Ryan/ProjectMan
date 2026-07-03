---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-8
points: 1
status: done
story_id: US-PRJ-26
title: 'Test: Store holds parsed frontmatter in memory after first load'
updated: '2026-03-05'
---

Verify that after the first call to list_tasks/list_stories, subsequent calls do not trigger disk reads. Mock or patch file I/O to confirm cache hits.