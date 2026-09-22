---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-52-5
- US-PM-52-6
id: US-PM-52-7
points: 1
status: done
story_id: US-PM-52
tags: []
title: Add a synthetic transcript fixture and CLI test
updated: '2026-09-09'
---

tests/test_orch_cost.py builds a small .jsonl transcript in tmp_path with: duplicated assistant records sharing a message id, two Agent dispatches with their task notifications 8 and 70 minutes later, one call whose cache_creation exceeds half the context, and a few pm tool results. Asserts dedupe, growth per dispatch, wait percentiles, the miss with its gap, and that the CLI command runs against --transcripts tmp_path.