---
acceptance_criteria:
- pm_batch_archive accepts comma-separated or list of IDs
- Archives all items with single commit
- Reports per-item success/failure
- Proper destructive=true annotation
created: '2026-03-09'
epic_id: EPIC-PRJ-8
id: US-PRJ-45
points: 3
priority: should
status: backlog
tags:
- batch
- mcp
title: Implement pm_batch_archive MCP tool
updated: '2026-03-09'
---

As a project manager, I want to archive multiple items in a single call so that sprint cleanup is efficient. Add pm_batch_archive that accepts a list of IDs and archives them all with a single commit. Should handle cascading (archiving a story archives its tasks).