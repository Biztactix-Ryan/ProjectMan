---
acceptance_criteria:
- The rendered pm-orchestrate skill arms one session-only CronCreate heartbeat in
  Phase 0 whose prompt tells the orchestrator to reply in a few words while a worker
  is out and to CronDelete the job when no run is in flight, and deletes it in Phase
  4 and the stop conditions
- orchestrate-design.md has a Heartbeat section with the measured regime comparison
  and why 30 minutes on the one-hour cache beats a 4-minute ping-pong on the five-minute
  cache
- projectman orch-cost reports the cache TTL mix of a run (calls writing ephemeral_5m
  versus ephemeral_1h entries) and the number of heartbeat turns, in both text and
  --json output, and the reference transcript fixture covers both
- The rendered skill stays within the size cap pinned by tests/test_orchestrate_skill_size.py
created: '2026-09-17'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-54
points: 5
priority: should
status: done
tags:
- orchestrator
- cost
- cache
title: Orchestrator keeps the prompt cache warm through worker waits
updated: '2026-09-17'
---

As the person paying for orchestrated sprint runs, I want the orchestrator to send a cheap heartbeat while it idles on a worker so that a wait longer than the one-hour prompt-cache TTL no longer re-sends the whole context at full write price, and I want orch-cost to show which cache TTL a run used so a silent drop to the five-minute cache is visible in the run metrics rather than the bill.

Measured 2026-09-17 on the three largest Kura sessions (Fable 5.1, 535-603k peak context, every write an ephemeral_1h entry): 1-3 full misses per run, each after a 60-112 minute worker wait, re-writing 194-469k tokens at the 2x one-hour write rate. Replaying the real call timelines under an ideal cache model (calibrated within 5% of observed usage): one-hour TTL as run today $45-56 per session; one-hour TTL plus a 30-minute heartbeat $32-39; five-minute TTL plus a 4-minute ping-pong $49-59 (175-200 pings over 8-14 idle hours); five-minute TTL with no pings $180-240. So the heartbeat stays on the one-hour cache and fires every 30 minutes, which is what a session-only CronCreate job gives for free: cron prompts fire only while the REPL is idle, which is exactly the worker-wait window. Claude Code drops the main conversation to the five-minute TTL once a subscription draws on usage credits; promptCacheTtl=1h in user settings pins it (set 2026-09-17, outside this repo).