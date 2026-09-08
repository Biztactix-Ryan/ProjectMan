---
acceptance_criteria:
- Reading the activity log has one implementation in activity_log.py and server.py
  and migrations.py call it
- A config key bounds the activity log by size or age and appending past the bound
  rotates activity.jsonl to a dated sibling file
- pm_activity returns entries from rotated files as well as the live file
- Rotation loses no entry and the full suite passes
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-52
points: 3
priority: could
status: done
tags:
- quality
- logging
title: Activity log reads live in activity_log.py and the log rotates
updated: '2026-09-08'
---

As a project manager, I want the activity log to stay bounded and its read path to live in one module so that a long-lived project does not grow an unbounded activity.jsonl and every reader parses it the same way.

Re-scoped 2026-09-08 against the code that exists. Two of the four original criteria are already met: Store.update builds before/after diffs for every changed field (store.py, "Build before/after field diffs for activity log"), so field changes and status transitions are logged with from/to values. What remains:

1. activity_log.py is 21 lines and only appends. The read side is duplicated: server.py reads activity.jsonl by hand for pm_activity and the resume path, and migrations.py has its own tolerant reader. Move reading (tolerant of a missing file and bad lines) into activity_log.py and make those callers use it.
2. No rotation exists. This repo's activity.jsonl is 336 KB after six weeks. Add rotation controlled by a config key (max size in bytes or max age in days) that renames activity.jsonl to a dated sibling and starts a fresh file. pm_activity must still read across the rotated files so history is not lost to the caller.

Rotation must never lose an entry: rotate on append, before writing, under the same write discipline as the item files.