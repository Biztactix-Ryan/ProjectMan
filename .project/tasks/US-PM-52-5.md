---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-52-5
points: 3
status: done
story_id: US-PM-52
tags: []
title: Implement orch_cost.py transcript analysis
updated: '2026-09-09'
---

New module src/projectman/orch_cost.py: find_transcripts(run_id, root=~/.claude/projects) returns the .jsonl files containing the run id; analyze(path, run_id) streams the file, dedupes assistant records by message.id, reads usage (input + cache_read + cache_creation as context per call, output_tokens), counts Agent tool_use as dispatches and pm_accept/pm_done_next as accepts, sums tool_result bytes by tool name, pairs each Agent launch with the next task-notification user message for worker wait minutes, and flags a full cache miss when cache_creation plus input exceeds half the context, recording the gap in minutes since the previous call. Returns a plain dict: base, peak, growth, per_dispatch, per_task, calls_per_dispatch, output_per_call, tool_bytes, waits {p50,p90,max}, misses [{at, gap_min, tokens}].