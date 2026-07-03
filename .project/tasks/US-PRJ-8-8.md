---
assignee: claude
created: '2026-02-17'
id: US-PRJ-8-8
points: 2
status: done
story_id: US-PRJ-8
title: Add pm_git_status MCP tool and /pm routing
updated: '2026-02-28'
---

Expose git_status_all() as an MCP tool for Claude and route it from /pm skill.

**MCP tool** (src/projectman/server.py):
- Register `pm_git_status` tool
- Returns the structured list from git_status_all() including PR data
- Optional `project` parameter to check a single subproject

**Skill routing** (.claude/skills/pm/pm.md):
- `git status` / `git-status` → pm_git_status
- `what needs attention?` → pm_git_status (natural language)
- After displaying results, suggest next action based on issues found:
  - Misaligned branch → "Run `projectman create-branch` to fix"
  - Behind remote → "Run `projectman sync` to pull latest"
  - Open PRs → "Check PRs with `gh pr view`"

Files: src/projectman/server.py, .claude/skills/pm/pm.md