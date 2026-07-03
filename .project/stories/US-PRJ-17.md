---
acceptance_criteria:
- Log entry schema defined with all required fields
- Append-only writer function that atomically appends entries
- Storage format is JSONL (one JSON object per line) for easy parsing
- Entries include ISO 8601 timestamps
- File created automatically on first write
created: '2026-02-17'
epic_id: EPIC-PRJ-3
id: US-PRJ-17
points: 3
priority: must
status: done
tags: []
title: Activity log data model and storage layer
updated: '2026-03-01'
---

As a developer, I want a well-defined activity log entry format and append-only file storage so that all project mutations are durably recorded in a git-friendly format.

The log should live at `.project/activity.log` (or `.project/activity.jsonl` for structured querying). Each entry should capture: event type, item ID, item type, changed fields (before/after), timestamp (ISO 8601), actor (GitHub ID or "claude"), and source (mcp/web/cli). The file must be append-only — never rewrite or truncate past entries.