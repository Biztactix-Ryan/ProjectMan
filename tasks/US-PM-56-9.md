---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-56-7
id: US-PM-56-9
points: 3
status: done
story_id: US-PM-56
tags: []
title: Add `projectman session-context` and wire it as the plugin's SessionStart hook
updated: '2026-10-07'
---

Today's status block comes from ClaudeDefaultSetup's ~/.claude/hooks/session-start.sh (copied per project as .claude/hooks/pm-context.sh by /setup-project), not from ProjectMan. Add a `projectman session-context` command printing the same block (project counts, points, active sprint, in-flight work, NEXT.md note) and silent outside a store. Wire it in the plugin's hooks/hooks.json as a SessionStart command hook. Keep output shape compatible so the external script's dedupe still works.