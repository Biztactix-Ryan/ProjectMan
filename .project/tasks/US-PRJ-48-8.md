---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-48-7
id: US-PRJ-48-8
points: 1
status: done
story_id: US-PRJ-48
tags: []
title: Document the error code taxonomy
updated: '2026-09-05'
---

Add an 'Error codes' section to docs/reference/error-paths-inventory.md and a short table to docs/reference/mcp-tools.md: code, meaning, which tools raise it, example wire text. State the backwards-compat guarantee: message text unchanged, code appended, is_error still set for every failure.