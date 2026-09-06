---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-34-7
id: US-PM-34-8
points: 3
status: done
story_id: US-PM-34
tags: []
title: ID-less verbs take an optional prefix; docs and skill templates lose every
  mention of project
updated: '2026-09-06'
---

pm_create_story, pm_create_epic, pm_create_sprint, pm_status, pm_board, pm_active, pm_list_sprints, pm_search, pm_context, pm_audit, pm_reindex, pm_commit, pm_push and pm_docs replace project with prefix: Optional[str]. In a hub an omitted prefix means the hub's own store for reads and status verbs and raises errors.InvalidError for the create verbs; outside a hub the parameter is ignored. Then sweep docs/reference/mcp-tools.md, docs/reference/skills.md, src/projectman/templates/skill_*.j2 and the pm agent template for 'project' as a tool argument and the hub-mode paragraph in the /pm skill, replacing them with the prefix rule. Re-run refresh-skills and record the new tools/list byte count against the 88441 baseline in the run log.