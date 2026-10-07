---
acceptance_criteria:
- A candidate launch command starts `projectman serve` from a plugin root with the
  [all] extras resolved and the MCP tools listed in a Claude Code session
- Cold and warm startup times are measured and recorded against today's pipx-launched
  server
- Behaviour without uv installed, and offline after first install, is recorded
- An ADR records the chosen launch command, or the reason pipx stays and how the plugin
  pins to a compatible server version
created: '2026-10-07'
depends_on: []
epic_id: EPIC-PM-8
id: US-PM-55
points: 3
priority: must
status: done
tags:
- plugin
- spike
title: 'Spike: the plugin can carry and launch its own MCP server'
updated: '2026-10-07'
---

As the maintainer running ProjectMan on many machines, I want the plugin's .mcp.json to launch the Python server from the plugin's own copy (e.g. `uvx --from ${CLAUDE_PLUGIN_ROOT} projectman serve`, or `uv run --project`), so that the server version moves with the skills and pipx drift goes away. Timeboxed spike: decide the launch command or record why pipx must stay, as an ADR.