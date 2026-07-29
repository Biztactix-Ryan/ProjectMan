---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-3-6
id: US-PM-3-7
points: 1
status: done
story_id: US-PM-3
tags: []
title: Sweep docstrings so the alias is discoverable
updated: '2026-07-29'
---

Each affected tool's Args block should mention both accepted spellings. Note the lesson from commit 2261a0d: a docstring alone does not change model behaviour, so this supports the schema change rather than substituting for it.