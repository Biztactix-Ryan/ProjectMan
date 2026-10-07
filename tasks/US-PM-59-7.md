---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-59-6
id: US-PM-59-7
points: 3
status: todo
story_id: US-PM-59
tags: []
title: Guard Bash against git checkout, restore and stash
updated: '2026-10-07'
---

tool.call hook on Bash refusing git checkout/restore/stash (incl. `git -C`, chained commands) with a deny reason naming the worker rule. Applies to subagent calls (event agentId set) by default; a userConfig option enables it for the main session. Tests cover subagent vs main session.