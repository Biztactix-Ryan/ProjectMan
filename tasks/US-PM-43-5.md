---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-43-5
points: 1
status: done
story_id: US-PM-43
tags: []
title: criteria-without-test-task skips done and archived stories
updated: '2026-09-08'
---

In audit.py the criteria drift loop skips only archived stories. A done story's criteria were verified some other way and re-applying them would create todo test tasks under a done story. Skip stories whose status is done as well, keep firing for backlog, ready and active stories, and say why in the comment. Add a test with one done story and one backlog story in the same drifted state: only the backlog one warns.