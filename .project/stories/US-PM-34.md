---
acceptance_criteria:
- No tool in the MCP tool list has a project parameter and the tools/list schema byte
  count drops from the 88441 recorded in the post-subtraction baseline
- In a hub pm_get and pm_update and the verdict verbs find the store named by the
  ID prefix with no other argument and an unknown prefix is a coded not_found error
  listing the known prefixes
- Multi-ID tools accept IDs from several stores in one call and return them grouped
  correctly
- ID-less verbs take an optional prefix and pm_create_story without one in a hub is
  a coded invalid error while pm_status without one reports the hub store
- Single-project mode behaviour and responses are unchanged and the full unit suite
  passes
created: '2026-09-06'
depends_on:
- US-PM-31
epic_id: EPIC-PM-5
id: US-PM-34
points: 8
priority: should
status: ready
tags:
- hub
- mcp
- api
title: 'The ID prefix names the store: the project argument is dropped from every
  tool'
updated: '2026-09-06'
---

As an agent working in a hub, I want `pm_get("US-API-3")` to find the API project's store on its own, so that no call has to carry a `project` argument the ID already implies and the tool list stops advertising 44 optional parameters that single-project users never need.

Today `_store(project)` in server.py takes an optional project name, 44 tools expose it, and nothing checks that the ID's prefix and the named project agree. models.py already validates STORY_ID, TASK_ID, EPIC_ID and SPRINT_ID with an uppercase prefix group.

Direction: a `_store_for_id(id)` resolver parses the prefix from the ID, looks it up in the hub store map from US-PM-31, and raises the coded not_found error with the known prefixes listed when nothing matches; in single-project mode it returns the one store regardless of prefix, so behaviour there is unchanged. Every ID-taking tool routes through it; multi-ID tools (pm_get, pm_batch_get, pm_update_many, pm_archive_many) group IDs by store. The ID-less verbs (pm_create_story, pm_create_epic, pm_create_sprint, pm_status, pm_board, pm_active, pm_list_sprints, pm_search, pm_context, pm_audit, pm_reindex, pm_commit, pm_push, pm_docs) take an optional `prefix`; omitted in a hub it means the hub's own store for status-type reads and is an error for creates. pm_create_task and pm_create_tasks resolve through their story_id. The MCP docs, skill templates and the pm agent template lose every mention of `project`.