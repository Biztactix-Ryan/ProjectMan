---
acceptance_criteria:
- A migrate command removes ProjectMan-managed skills and agent from ~/.claude and
  the current project's .claude, leaving user-authored files untouched
- It removes the old projectman MCP server entry and the ProjectMan SessionStart settings
  hook, and lists every change it makes
- A dry-run flag shows the changes without writing
- setup-claude and refresh-skills point users to the plugin install and the migrate
  command
- README and INFRASTRUCTURE.md describe the plugin install as the supported path
created: '2026-10-07'
depends_on:
- US-PM-56
epic_id: EPIC-PM-8
id: US-PM-57
points: 3
priority: must
status: backlog
tags:
- plugin
- migration
title: Migrate existing machines off setup-claude and refresh-skills
updated: '2026-10-07'
---

As a user with ProjectMan already set up the old way, I want one command that removes the rendered skills/agent, the old MCP entry and the per-project SessionStart settings hook that the plugin now provides, so that nothing loads twice. setup-claude and refresh-skills are retired to this migration path.