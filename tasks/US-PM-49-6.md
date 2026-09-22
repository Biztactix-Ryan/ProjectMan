---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-49-5
id: US-PM-49-6
points: 2
status: done
story_id: US-PM-49
tags: []
title: Use projections in the orchestrate skill's pre-flight and plan phases
updated: '2026-09-09'
---

In skill_pm_orchestrate.md.j2 Phase 1 uses pm_list_sprints(status="active", brief=True) and pm_board(brief=True); Phase 2 replaces the per-story unprojected pm_get with one pm_batch_get(type="story", ids=<sprint stories>, fields="id,status,assignee,depends_on,points,acceptance_criteria,definition_of_done") (confirm the exact field names pm_batch_get accepts) and pm_context(max_doc_chars=2000, limit=5) is dropped from the run entirely (see the worker prompt task). Mention the projections in docs/reference/skills.md.