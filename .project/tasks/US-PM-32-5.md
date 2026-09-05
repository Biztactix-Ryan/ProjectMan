---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-32-4
id: US-PM-32-5
points: 1
status: todo
story_id: US-PM-32
tags: []
title: Capture baseline-windowed-post-fix and write the three-way comparison
updated: '2026-09-06'
---

Run: python -m tools.usage_telemetry.baseline capture --out-dir docs/telemetry --name baseline-windowed-post-fix --label windowed-post-fix --since auto from a clean tree, then compare against baseline-pre-fix.json and baseline-post-subtraction.json. Write docs/telemetry/baseline-windowed-post-fix.md with provenance, the window, the headline table, and a verdict row per Sprint 1 to 9 claim (fewer calls per task, less context per worker, shorter pm_update and pm_archive runs, fewer failures) stating whether it holds once pre-fix sessions are excluded. Link it from docs/telemetry/README.md. Do not overwrite the two existing baselines.