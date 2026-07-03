---
assignee: claude
created: '2026-02-17'
id: US-PRJ-2-7
points: 2
status: done
story_id: US-PRJ-2
title: Write tests for validate_branches using tmp_hub fixture
updated: '2026-02-19'
---

Add tests to tests/test_hub.py (or new tests/test_hub_validation.py) covering:

1. All aligned — every submodule on its tracked branch → ok=True
2. One misaligned — submodule checked out to feature branch, .gitmodules says main → detected with expected vs actual
3. Detached HEAD — after `git checkout <sha>` in submodule → reported as detached
4. Missing submodule dir — registered in config but projects/{name} doesn't exist → reported as missing
5. No branch in .gitmodules — branch field absent (defaults to remote HEAD) → handled gracefully
6. Mixed state — combination of aligned, misaligned, detached → summary accurate
7. CLI exit code — 0 on all aligned, 1 on any mismatch

Use existing tmp_hub fixture pattern from test_hub.py. Create real git repos with branches to test against.

Files: tests/test_hub.py or tests/test_hub_validation.py