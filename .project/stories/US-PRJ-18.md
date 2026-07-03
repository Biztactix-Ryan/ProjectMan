---
acceptance_criteria:
- All Store.create_* methods emit "created" log entries
- Store.update() emits "updated" entries with before/after field diffs
- Store.archive() emits "archived" entries
- Logging does not break existing functionality (transparent)
- Actor field populated when available (e.g. from git config or env var)
created: '2026-02-17'
epic_id: EPIC-PRJ-3
id: US-PRJ-18
points: 5
priority: must
status: done
tags: []
title: Instrument Store mutations to emit activity log entries
updated: '2026-03-01'
---

As a project manager, I want all state changes (create, update, archive) to be automatically logged so that I have a complete audit trail without manual effort.

Hook into all Store mutation methods: create_story, create_task, create_tasks, create_epic, create_changeset, update, archive, add_changeset_entry. Each hook should capture the event type, the item ID, and relevant field changes. For updates, capture before/after values of changed fields. For creates, log the initial state. For archives, log the status transition.