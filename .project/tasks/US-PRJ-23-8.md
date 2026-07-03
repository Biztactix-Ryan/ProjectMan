---
assignee: claude
created: '2026-02-23'
id: US-PRJ-23-8
points: 1
status: done
story_id: US-PRJ-23
title: Add dependency_status to pm_grab response
updated: '2026-03-01'
---

In `server.py` pm_grab(), after constructing sibling_list, add `dependency_status` to the response showing each dep's ID, title, and status.

## Implementation
- Edit `src/projectman/server.py` pm_grab() (~line 740)
- If task_meta.depends_on, build dep_status list from sibling_map
- Add to result dict

## Testing
- Grab task with deps includes dependency_status in response
- Grab task without deps has empty dependency_status

## Definition of Done
- [ ] dependency_status added to grab response
- [ ] Tests pass