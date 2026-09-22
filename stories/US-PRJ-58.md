---
acceptance_criteria:
- List-type params accepted alongside comma-separated strings for backwards compat
- pm_create_story acceptance_criteria accepts list
- pm_create_sprint planned_stories accepts list
- All affected tools documented with both input formats
created: '2026-03-09'
epic_id: EPIC-PRJ-11
id: US-PRJ-58
points: 3
priority: should
status: done
tags:
- mcp
- api
title: Convert comma-separated string params to list types
updated: '2026-09-05'
---

As an MCP client developer, I want proper list parameters so that I don't have to manually join/split strings. Several tools accept comma-separated strings where lists would be more appropriate: pm_create_story acceptance_criteria and tags, pm_create_task tags and depends_on, pm_update acceptance_criteria/tags/depends_on, pm_create_sprint and pm_update_sprint planned_stories, pm_batch_get and pm_archive_many ids.

Planning note (2026-09-05): the pm_changeset_create criterion was replaced by pm_create_sprint planned_stories because US-PM-27 removed changesets in Sprint 8. acceptance_criteria already accepts a list on pm_update (US-PM-18); the remaining string-only params are the target.