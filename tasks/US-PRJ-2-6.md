---
assignee: claude
created: '2026-02-17'
id: US-PRJ-2-6
points: 2
status: done
story_id: US-PRJ-2
title: Integrate pre-push validation into sync() and coordinated push path
updated: '2026-02-19'
---

Wire validate_branches() as a pre-check into existing operations.

1. In `sync()`: call validate_branches() before pulling. If any submodule is on the wrong branch, warn but continue (sync should still work — it pulls from the tracked branch regardless of local checkout)

2. Add a `strict` parameter: `validate_branches(root, strict=True)` that returns error-level results (for use in push operations where misalignment must block)

3. Ensure the validation output clearly distinguishes:
   - Informational: dirty tree, detached HEAD (common during development)
   - Blocking: wrong branch when about to push (this is the dangerous one)

This prepares the validation for US-PRJ-4 (coordinated push) and US-PRJ-7 (PR workflow) to call it as a gate.

Files: src/projectman/hub/registry.py