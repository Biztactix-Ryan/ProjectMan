---
acceptance_criteria:
- List-type params accepted alongside comma-separated strings for backwards compat
- pm_create_story acceptance_criteria accepts list
- pm_changeset_create projects accepts list
- All affected tools documented with both input formats
created: '2026-03-09'
epic_id: EPIC-PRJ-11
id: US-PRJ-58
points: 3
priority: should
status: backlog
tags:
- mcp
- api
title: Convert comma-separated string params to list types
updated: '2026-03-09'
---

As an MCP client developer, I want proper list parameters so that I don't have to manually join/split strings. Several tools accept comma-separated strings where lists would be more appropriate: pm_create_story acceptance_criteria and tags, pm_create_task tags and depends_on, pm_update acceptance_criteria/tags/depends_on, pm_changeset_create projects.