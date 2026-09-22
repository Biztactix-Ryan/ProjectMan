---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PRJ-52-9
id: US-PRJ-52-10
points: 2
status: done
story_id: US-PRJ-52
tags: []
title: Rotate activity.jsonl on append past a configured size or age bound
updated: '2026-09-08'
---

Add a config key (for example activity_log_max_bytes and activity_log_max_days) read through the cached config. On append, before writing, if the live file exceeds the bound rename it to a dated sibling (activity-YYYYMMDD-HHMMSS.jsonl) and start a fresh activity.jsonl. Rotation must never drop the entry being appended. Extend the reader from the previous task so pm_activity reads rotated siblings oldest-first followed by the live file. Default: no rotation unless a bound is configured, so existing projects behave as before. Document the key in docs/reference/file-formats.md.