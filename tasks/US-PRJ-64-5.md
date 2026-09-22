---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-64-5
points: 2
status: done
story_id: US-PRJ-64
tags: []
title: Write the estimator edge-case tests
updated: '2026-09-07'
---

src/projectman/estimator.py is 41 lines with one function, estimate(store, item_id), and tests/test_estimator.py has 2 tests. Add tests on a tmp store for: empty history (no done stories) still returns the calibration text without raising; 20+ done stories with mixed points give a distribution the guidance reflects; a mix of done, backlog and archived stories counts only what estimate() documents it counts; an unknown ID raises the store's coded not-found error; a task ID and a story ID both work. Read the function first and test what it does, not what the old story text guessed.