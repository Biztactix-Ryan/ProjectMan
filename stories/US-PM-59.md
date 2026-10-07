---
acceptance_criteria:
- The plugin carries a hooks module that `claude plugin validate` and `claude plugin
  test` both pass
- Bash calls running git checkout, git restore or git stash are refused with a reason
  naming the rule, including inside subagents
- Write and Edit calls targeting the real .project/ store are refused while pm MCP
  tools keep working
- Guards apply only to subagent/worker calls or when explicitly enabled, so the interactive
  user is not blocked
- The orchestrator and pm-do skills drop the prose those guards now enforce, and the
  skill character budget shrinks accordingly
created: '2026-10-07'
depends_on:
- US-PM-56
epic_id: EPIC-PM-8
id: US-PM-59
points: 5
priority: should
status: backlog
tags:
- plugin
- mod
- orchestration
title: 'Mod: orchestration guards enforce worker rules on tool calls'
updated: '2026-10-07'
---

As the orchestrator owner, I want a tool.call hook in the plugin's mod to refuse worker actions that have caused incidents (git checkout/restore/stash, writes to the real .project/ outside temp fixtures and MCP tools), so that the rules are enforced in-process instead of spending skill characters on them. Sets up the plugin's hooks module, type contract and `claude plugin test` suite that the later mod stories build on.