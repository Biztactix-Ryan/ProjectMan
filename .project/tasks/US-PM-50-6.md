---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-50-6
points: 3
status: done
story_id: US-PM-50
tags: []
title: Compute per-points duration history from the activity log
updated: '2026-09-09'
---

New function duration_history(store) (estimator.py or a new durations.py): iterate read_log_entries over all log paths, keep task update events whose run_id starts with `orch-`, pair each status after=in-progress with the next after=done or after=review for the same task, take the minutes between, and group by the task's points (read from the task file, archived tasks included). Return {points: {p50, p90, max, n}} sorted by points, plus total n. Unparseable or unpaired transitions are skipped, never raised. Unit tests with a synthetic activity log in tmp_path.