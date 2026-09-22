---
assignee: claude
created: '2026-02-17'
id: US-PRJ-10-8
points: 3
status: done
story_id: US-PRJ-10
title: Implement changeset merge tracking and hub ref gating
updated: '2026-02-19'
---

Add `changeset_check_status(changeset_id, root)` and integrate with hub ref updates.

`changeset_check_status()`:
1. For each project in the changeset, query PR state: `gh pr view {number} --json state,mergedAt`
2. Update changeset status:
   - All PRs merged → status="merged"
   - Some merged, some open → status="partial"
   - Any closed (not merged) → flag for review
3. Return detailed status per project

Hub ref gating — integrate with `update_hub_refs()` (US-PRJ-7-9):
- If a project is part of an open changeset, its hub ref should NOT be updated until all changeset PRs are merged
- When changeset status becomes "merged", update all hub refs for the changeset's projects in a single commit
- Commit message: `hub: changeset {name} merged — update {project1}, {project2}, ...`

Files: src/projectman/changesets.py, src/projectman/hub/registry.py