---
assignee: null
created: '2026-02-17'
id: US-PRJ-9-8
points: 1
status: todo
story_id: US-PRJ-9
title: Add commit message formatting helpers
updated: '2026-02-17'
---

Implement helpers that generate convention-compliant commit messages.

1. `format_hub_ref_commit(project_name, sha, root)` — generates `hub: update {project} to {sha[:7]}` using the template from conventions config

2. `format_pm_commit(action, item_id, root)` — generates `pm: {action} {id}` (e.g. `pm: create US-PRJ-5`, `pm: update US-PRJ-3-1 status=done`)

3. `validate_commit_message(message, root)` — checks if a commit message matches one of the known convention templates. Returns warning (not error) for non-matching messages since users may have manual commits.

These are consumed by the future pm_commit tool (US-PRJ-3) and update_hub_refs (US-PRJ-7-9).

Files: src/projectman/hub/registry.py