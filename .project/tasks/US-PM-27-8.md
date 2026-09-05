---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-27-7
id: US-PM-27-8
points: 2
status: done
story_id: US-PM-27
tags: []
title: 'Pass 3: docs and dead-import sweep with before and after counts'
updated: '2026-09-05'
---

Remove changeset and PR-workflow content from docs/hub-mode and docs/reference (CLI and MCP tool references), README feature lists, and CHANGELOG (add an 'Removed' entry for the next version). Run `ruff check` or `python -m pyflakes` on src/ to catch dead imports left by passes 1 and 2 and remove them. Record in the run log the line counts of src/projectman and tests before the story started (source 13,546 and tests total from `wc -l tests/*.py`) and after.