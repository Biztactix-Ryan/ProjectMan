---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-56-4
points: 1
status: done
story_id: US-PRJ-56
tags: []
title: Rewrite the routing section of docs/reference/skills.md with a CLI / MCP /
  skill quick-reference table
updated: '2026-09-07'
---

docs/reference/skills.md line 13 still shows `/pm scope US-PRJ-1` as if standalone. State once that every /pm-* entry routes through the /pm skill and the pm agent, then add one table: operation (status, board, create story, scope, estimate, commit, push, sprint plan, orchestrate, next note) against how you reach it (CLI command, MCP tool name, skill invocation). Take the tool names from docs/reference/mcp-tools.md and the CLI names from docs/reference/cli.md so the three agree; the existing docs tests will catch a name that does not exist.