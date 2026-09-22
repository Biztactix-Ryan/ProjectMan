---
assignee: claude
created: 2026-02-17
id: US-PRJ-10-10
points: 2
status: done
story_id: US-PRJ-10
title: Register changeset MCP tools and CLI commands
updated: '2026-02-17'
---

Expose changeset operations through MCP and CLI.

**CLI** (src/projectman/cli.py):
- `projectman changeset create "name" --projects api,web,worker`
- `projectman changeset add-project CS-PRJ-1 docs`
- `projectman changeset create-prs CS-PRJ-1`
- `projectman changeset status [CS-PRJ-1]`
- `projectman changeset push CS-PRJ-1` (update hub refs after all merged)

**MCP tools** (src/projectman/server.py):
- `pm_changeset_create`, `pm_changeset_status`, `pm_changeset_create_prs`, `pm_changeset_push`

**Skill routing** (.claude/skills/pm/pm.md):
- `changeset create/status/push` → appropriate tool
- "group these changes" → changeset create

Files: src/projectman/cli.py, src/projectman/server.py, .claude/skills/pm/pm.md