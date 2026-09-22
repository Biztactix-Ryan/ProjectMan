---
assignee: claude
created: '2026-02-17'
id: US-PRJ-2-5
points: 2
status: done
story_id: US-PRJ-2
title: Add validate-branches CLI command and MCP tool
updated: '2026-02-19'
---

Expose `validate_branches()` through both CLI and MCP server.

**CLI** (src/projectman/cli.py):
- Add `projectman validate-branches` command
- Output a formatted table: project | expected branch | actual branch | status
- Use color/symbols for aligned (✓) vs misaligned (✗) vs detached (⚠)
- Exit code 0 if all aligned, 1 if any misaligned

**MCP tool** (src/projectman/server.py):
- Register `pm_validate_branches` tool
- Returns the structured dict from validate_branches()
- Include in /pm skill routing: `validate` or `check branches` → pm_validate_branches

Files: src/projectman/cli.py, src/projectman/server.py, .claude/skills/pm/pm.md