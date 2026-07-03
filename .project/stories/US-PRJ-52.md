---
acceptance_criteria:
- Update operations record old_value and new_value in changes dict
- Status transitions logged with from/to states
- Log rotation implemented (configurable max size or age)
- Activity log query functions moved to dedicated module
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-52
points: 5
priority: could
status: backlog
tags:
- quality
- logging
title: Improve activity log event coverage and change tracking
updated: '2026-03-09'
---

As a project manager, I want comprehensive activity logging so that I can audit all changes. Currently the changes dict is rarely populated (store.py lines 256, 427, 575 pass empty dicts). Missing log events for: status transitions, task assignment, dependency changes, tag updates, git operations, and failed operations. Add log rotation to prevent unbounded growth.