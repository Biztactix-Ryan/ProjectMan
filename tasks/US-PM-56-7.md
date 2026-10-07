---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-55-7
id: US-PM-56-7
points: 2
status: done
story_id: US-PM-56
tags: []
title: Add the marketplace manifest and plugin skeleton
updated: '2026-10-07'
---

Per ADR-006: add .claude-plugin/marketplace.json at the repo root and the plugin folder with .claude-plugin/plugin.json (name projectman, version from pyproject) and .mcp.json using the ADR's launch command. `claude plugin validate` passes on it.