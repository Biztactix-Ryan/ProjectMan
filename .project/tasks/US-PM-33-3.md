---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-33-3
points: 1
status: done
story_id: US-PM-33
tags: []
title: Reorder agent.md token discipline so pm_status comes first and pm_context is
  a pointer
updated: '2026-09-06'
---

In docs/reference/agent.md the Token Discipline list puts 'Fetch context via pm_context' as rule 1 ahead of 'Always start with pm_status'. Since US-PM-26 pm_context is mandatory only under the orchestrator. Rewrite the list to say what src/projectman/templates/agent_pm.md.j2 says: pm_status first, one item at a time via pm_get, pm_search for discovery, and pm_context described as an optional bounded brief (max_doc_chars, limit, prefix for one subproject) that pm_grab and pm_get usually make unnecessary. Check the rest of agent.md for any other sentence that calls pm_context mandatory and align it. Files: docs/reference/agent.md only.