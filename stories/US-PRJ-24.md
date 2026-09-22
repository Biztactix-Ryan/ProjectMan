---
acceptance_criteria:
- pm_create_task accepts comma-separated depends_on
- pm_update accepts comma-separated depends_on for tasks
- pm_create_tasks docstring documents depends_on key
- Web CreateTaskRequest and UpdateItemRequest include depends_on
- Web TaskResponse includes depends_on
- Server tests cover MCP tool parameter parsing
created: '2026-02-23'
epic_id: EPIC-PRJ-4
id: US-PRJ-24
points: 3
priority: must
status: done
tags: []
title: MCP and Web API dependency exposure
updated: '2026-03-01'
---

As a user, I want to set depends_on through pm_create_task, pm_create_tasks, pm_update MCP tools and the web API so that dependencies can be managed through all interfaces.

Covers: adding depends_on param to pm_create_task (comma-separated), pm_update (comma-separated), updating pm_create_tasks docstring, and updating web schemas (CreateTaskRequest, UpdateItemRequest, TaskResponse) and routes.