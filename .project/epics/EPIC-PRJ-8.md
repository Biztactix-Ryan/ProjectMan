---
created: '2026-03-09'
id: EPIC-PRJ-8
points: null
priority: must
status: draft
tags:
- batch
- api
- v0.9
target_date: null
title: Batch Operations & Bulk Workflows
updated: '2026-03-09'
---

Extend batch capabilities beyond pm_batch_get. Add pm_batch_update and pm_batch_archive MCP tools. Fix N+1 patterns in pm_board, pm_epic, and pm_search that fetch items individually when batch data is available in cache. Enable efficient sprint-level operations like mass status changes, bulk archival, and batch tag updates.