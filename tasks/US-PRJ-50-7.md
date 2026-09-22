---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-50-6
id: US-PRJ-50-7
points: 1
status: done
story_id: US-PRJ-50
tags: []
title: Survey fixtures and tests for IDs the strict patterns reject and fix them
updated: '2026-09-05'
---

Run the full suite after the regex change and fix what breaks. Known offenders: tests/test_deps.py uses US-1-1 / US-1 (pure graph tests — if they build models, switch to US-TST-N-N; if they only pass strings to deps.py, no change needed); tests/test_usage_telemetry_report.py uses US-X-1 (valid under the new pattern, confirm); tests/golden fixtures; every ID in .project (all currently match US-PM-N, US-PM-N-N, US-PRJ-N, US-PRJ-N-N, EPIC-*, SPRINT-*). Also run 'projectman audit' against this repo's .project to prove every existing ID passes. Record any exemption made and why in the run-log note.