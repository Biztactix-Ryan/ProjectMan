---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-56-8
id: US-PM-57-6
points: 3
status: todo
story_id: US-PM-57
tags: []
title: Add `projectman migrate-to-plugin` with --dry-run
updated: '2026-10-07'
---

New CLI command: removes ProjectMan-managed skills/agent from ~/.claude and ./.claude via _remove_claude_assets, removes the user-scope MCP entry (`claude mcp remove --scope user projectman`) and the projectman entry from ./.mcp.json (leaving other servers). Lists every change; --dry-run writes nothing. Only touches files ProjectMan wrote.