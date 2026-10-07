---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-57-6
- US-PM-56-9
id: US-PM-57-7
points: 2
status: todo
story_id: US-PM-57
tags: []
title: Remove per-project pm-context hook copies, warn about the global one
updated: '2026-10-07'
---

Extend migrate-to-plugin: remove .claude/hooks/pm-context.sh and its SessionStart entry from the project's .claude/settings.json when present. Leave ClaudeDefaultSetup's global ~/.claude/hooks/session-start.sh alone and print a note that it duplicates the plugin's hook.