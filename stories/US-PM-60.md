---
acceptance_criteria:
- Board, status and next commands return their view with no model request made
- The board opens as a pane in the terminal and the Desktop Code tab and refreshes
  on demand
- On surfaces that do not draw, the commands reply with a text summary
- Commands work while a Claude turn is in progress
- UI tests mount the pane on both the terminal and desktop surfaces
created: '2026-10-07'
depends_on:
- US-PM-59
epic_id: EPIC-PM-8
id: US-PM-60
points: 5
priority: should
status: backlog
tags:
- plugin
- mod
- ui
title: 'Mod: /pm board, status and next answer without a Claude turn'
updated: '2026-10-07'
---

As a user checking the project many times a day, I want the board, status and next-task views to run as mod commands that call the MCP server directly ($.mcp.call) and draw in a pane, so that checking costs no tokens and works while Claude is busy. Where nothing draws (VS Code chat, claude -p) the command answers with text.