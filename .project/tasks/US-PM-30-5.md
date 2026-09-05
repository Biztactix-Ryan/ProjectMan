---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-30-4
id: US-PM-30-5
points: 2
status: done
story_id: US-PM-30
tags: []
title: Capture baseline-post-subtraction and write the comparison against pre-fix
updated: '2026-09-05'
---

Run `python -m tools.usage_telemetry.baseline capture --name baseline-post-subtraction` with label post-subtraction and a note naming the Sprint 8 commit it follows, from a clean tree so provenance.git.dirty is false. Then `python -m tools.usage_telemetry.baseline compare docs/telemetry/baseline-pre-fix.json docs/telemetry/baseline-post-subtraction.json` and put the comparison into docs/telemetry/baseline-post-subtraction.md: calls per task, context per worker, and the BULK_RUN_TOOLS longest-run metrics (pm_update_longest_run feeds US-PM-12-5). Add the new pair to the table in docs/telemetry/README.md, and parametrize the committed-baseline tests over both baselines so the post-subtraction file is held to the same provenance and rate-format checks. Acceptance criteria of US-PM-30 one and three.