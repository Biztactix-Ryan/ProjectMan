---
assignee: claude
created: '2026-02-17'
id: US-PRJ-3-7
points: 2
status: done
story_id: US-PRJ-3
title: Register pm_commit and pm_push as MCP tools and CLI commands
updated: '2026-02-19'
---

Expose both functions through MCP server and CLI.

**MCP tools** (src/projectman/server.py):
- `pm_commit` tool: params `scope` (required), `message` (optional)
- `pm_push` tool: params `scope` (required)
- Both return structured results (sha, files, errors)

**CLI** (src/projectman/cli.py):
- `projectman commit [--scope hub|project:name|all] [--message "..."]`
- `projectman push [--scope hub|project:name|all]`
- Default scope is `"hub"` (most common case — committing PM data)

**Skill routing** (.claude/skills/pm/pm.md):
- `commit` / `push` → route to pm_commit / pm_push
- `commit all` → pm_commit with scope=all
- `push api` → pm_push with scope=project:api

Files: src/projectman/server.py, src/projectman/cli.py, .claude/skills/pm/pm.md