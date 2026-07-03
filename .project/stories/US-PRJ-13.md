---
acceptance_criteria:
- pm_create_story accepts comma-separated tags parameter
- pm_create_task accepts comma-separated tags parameter
- pm_update exposes tags as explicit parameter for all item types
- store.create_story passes tags to frontmatter
- store.create_task and create_tasks pass tags to frontmatter
created: '2026-02-17'
epic_id: EPIC-PRJ-2
id: US-PRJ-13
points: 3
priority: must
status: done
tags: []
title: Wire tags through store and MCP create/update APIs
updated: '2026-03-01'
---

As a user, I want to set tags when creating or updating stories and tasks via the CLI/MCP tools. Currently pm_create_story and pm_create_task don't accept a tags parameter. The store methods for story/task creation also need the tags param wired through. pm_update should expose tags as an explicit parameter.