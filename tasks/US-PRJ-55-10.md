---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PRJ-55-9
id: US-PRJ-55-10
points: 1
status: done
story_id: US-PRJ-55
tags: []
title: Link the guide from setup.md and add the no-removed-commands check
updated: '2026-09-07'
---

Add a Troubleshooting link in docs/hub-mode/setup.md near the end. Extend tests/test_docs_after_subtraction.py (or the story's own test file) so the guide is scanned for the removed-command words: repair, coordinated push, validate-branches, changeset, auto-rebase. Run the docs tests.