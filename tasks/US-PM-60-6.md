---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-59-6
id: US-PM-60-6
points: 3
status: todo
story_id: US-PM-60
tags: []
title: Register board, status and next commands that call MCP directly
updated: '2026-10-07'
---

$.command.register in session.start for the three commands (names chosen not to clash with the /pm skill, e.g. /pm-board); command.run hooks call $.mcp.call('projectman', 'pm_board'|'pm_status'|'pm_board') and format results. No model request is made.