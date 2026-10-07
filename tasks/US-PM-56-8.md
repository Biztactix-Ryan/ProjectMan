---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-56-7
id: US-PM-56-8
points: 3
status: done
story_id: US-PM-56
tags: []
title: Add `projectman build-plugin` to render skills and agent into the plugin
updated: '2026-10-07'
---

New CLI command reusing the CLAUDE_SKILLS list and template rendering behind _write_claude_assets (src/projectman/cli.py) to write skills/<name>/SKILL.md and agents/pm.md into the plugin folder. Output is committed. Templates stay the single source.