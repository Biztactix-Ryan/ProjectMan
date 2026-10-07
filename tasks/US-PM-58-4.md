---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-56-8
id: US-PM-58-4
points: 2
status: done
story_id: US-PM-58
tags: []
title: Update skill and agent references for plugin namespacing
updated: '2026-10-07'
---

Confirm how namespaced plugin skills and agents are invoked (/projectman:pm-do vs /pm-do, subagent types projectman:pm). Update the ~40 /pm-* references across src/projectman/templates/*.j2 so they resolve under the plugin, then rebuild the plugin. Keep the orchestrate skill under the 9000-char cap.