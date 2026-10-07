---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-55-5
id: US-PM-55-6
points: 1
status: todo
story_id: US-PM-55
tags: []
title: Measure startup and failure modes against pipx
updated: '2026-10-07'
---

For each working candidate from US-PM-55-5: time cold start (empty uv cache) and warm start of the MCP server vs. today's pipx `projectman serve`; record behaviour with no uv on PATH, and offline after a first successful install. Results go in the task log as a table.