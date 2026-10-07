---
acceptance_criteria:
- Each request's input, cache-read and cache-write tokens are recorded per task while
  an orchestrator run is active
- A pane shows per-task totals and marks requests that followed a gap longer than
  the cache TTL
- Heartbeat requests are counted separately so their cost and the cache writes they
  avoided are visible
- Totals for a finished run match orch-cost on the same transcript within a stated
  tolerance
- The per-run summary is persisted so it survives a session restart
created: '2026-10-07'
depends_on:
- US-PM-60
epic_id: EPIC-PM-8
id: US-PM-61
points: 8
priority: could
status: backlog
tags:
- plugin
- mod
- orchestration
- cost
title: 'Mod: live cache-cost pane for orchestrator runs'
updated: '2026-10-07'
---

As the maintainer working on orchestrator context cost (EPIC-PM-7), I want the mod to record each request's token usage in-process and show cache reads vs. writes per task in a pane, flagging requests after a gap longer than the cache TTL, so that I can see live whether the US-PM-54 heartbeat earns its cost instead of parsing transcripts after the run with orch-cost.