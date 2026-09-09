---
acceptance_criteria:
- projectman orch-cost <run-id> finds the transcript containing that run id and prints
  growth per dispatch and per accepted task, calls per dispatch and output tokens
  per call
- The report lists tool result bytes by tool name and worker wait p50, p90 and max
- The report lists each full cache miss with the gap in minutes before it
- Records sharing a message id are counted once
created: '2026-09-09'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-52
points: 3
priority: could
status: done
tags:
- cost
- tooling
title: projectman orch-cost measures context per task from session transcripts
updated: '2026-09-09'
---

As the ProjectMan maintainer, I want a command that reports context growth per dispatch and per accepted task, cache misses and worker waits for a given orch- run id, so that the epic's success criteria are measured the same way every time instead of by ad hoc scripts.

Source is the Claude Code session transcript under ~/.claude/projects/<project>/<session>.jsonl: per assistant message, input_tokens + cache_read_input_tokens + cache_creation_input_tokens is the context at that call; dedupe by message id because the harness writes one record per content block with the same usage. Report: dispatches (Agent tool_use count), accepts, base context, peak, growth per dispatch and per accepted task, API calls per dispatch, output tokens per call, tool result bytes by tool name, worker wait percentiles (Agent launch to the matching task notification), and full cache misses (cache_creation plus input over half the context) with the preceding gap in minutes. The 2026-09-09 baseline numbers in the epic description were produced this way; the scratchpad scripts from that session are the seed.