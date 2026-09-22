---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-23-4
points: 1
status: done
story_id: US-PM-23
tags: []
title: Write the Upgrading section in docs/installation.md
updated: '2026-09-05'
---

Add an `## Upgrading` section after the install instructions. Contents: (1) how to tell the install is stale — the MCP server or CLI behaves like an older version than the tree, e.g. a tool argument the code accepts is rejected; (2) `pipx install --force "/path/to/ProjectMan[all]"` reinstalling from the local checkout, with the note that a plain `pipx upgrade` does not pick up local changes; (3) `projectman refresh-skills --keep-local` to re-render the skill files; (4) that ProjectMan pins `mcp<2` because mcp 2.x renamed FastMCP, and a venv holding mcp 2.x fails with 'MCP extras not installed'. Keep it under 40 lines. Also add a short 'Upgrading' pointer in docs/reference/cli.md next to refresh-skills if that page lists it.