---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PRJ-52-9
points: 2
status: done
story_id: US-PRJ-52
tags: []
title: One tolerant activity-log reader in activity_log.py used by server.py and migrations.py
updated: '2026-09-08'
---

activity_log.py currently holds only append_log_entry. Add a read function (iterate LogEntry records from a path, tolerating a missing file and skipping bad lines, optionally newest-first with a limit) and make the two hand-rolled readers use it: server.py where pm_activity and the resume path read activity.jsonl by hand, and migrations.py's tolerant reader. Behaviour of pm_activity must not change. Cover the reader with unit tests for missing file, blank line, malformed JSON line and ordering.