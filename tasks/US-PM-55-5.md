---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on: []
id: US-PM-55-5
points: 2
status: done
story_id: US-PM-55
tags: []
title: Build a throwaway plugin with candidate MCP launch commands
updated: '2026-10-07'
---

In the scratchpad (not the repo), build a minimal plugin whose .mcp.json launches `projectman serve` from the plugin's own copy: candidates `uvx --from ${CLAUDE_PLUGIN_ROOT} projectman[all] serve` and `uv run --project ${CLAUDE_PLUGIN_ROOT} projectman serve`. Load it with `claude --plugin-dir` and confirm the pm MCP tools list. Also install it through a local marketplace to learn what an installed plugin's cache actually holds: does a plugin folder below the repo root carry the Python source, or must the plugin root be the repo root (or point at a git source)? Record findings in the task log.