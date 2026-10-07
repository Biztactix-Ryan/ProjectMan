---
acceptance_criteria:
- The repo root holds a marketplace manifest and a plugin folder with plugin.json,
  .mcp.json, skills, agents/pm.md and the SessionStart hook
- '`claude plugin validate` passes on the plugin folder'
- The plugin's skill and agent files are generated from src/projectman/templates and
  a test fails when they drift from the templates
- On a machine with no prior ProjectMan Claude setup, installing the plugin gives
  working pm skills, MCP tools and the SessionStart status block
- Updating the plugin and running /reload-plugins picks up changed skills without
  restarting Claude Code
- The plugin version is bumped with each release and matches pyproject.toml
created: '2026-10-07'
depends_on:
- US-PM-55
epic_id: EPIC-PM-8
id: US-PM-56
points: 5
priority: must
status: backlog
tags:
- plugin
- distribution
title: ProjectMan installs as a Claude Code plugin from this repo's marketplace
updated: '2026-10-07'
---

As a ProjectMan user on any machine, I want to run one `/plugin install` and get the pm skills, the pm agent, the MCP server and the SessionStart status hook together, so that setup is one step and a release is one update with no restart. The skill_*.j2 and agent_pm.md.j2 templates have no Jinja variables, so they ship as static plugin files generated from the templates at build time (one source, no hand-copied duplicates).