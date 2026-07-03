---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-9
points: 3
status: done
story_id: US-PRJ-7
title: Implement update_hub_refs_after_merge() for post-PR hub sync
updated: '2026-02-28'
---

Add a function that safely updates hub submodule refs only after PRs are merged.

`update_hub_refs(projects=None, root)` in `hub/registry.py`:
1. For each specified project (or all if None):
   a. Check PR status via `gh pr list --base {deploy_branch} --state merged`
   b. If merged PRs exist, update submodule to latest deploy branch: `git submodule update --remote projects/{name}`
   c. If open PRs still pending, skip (don't update ref to unmerged code)
2. Stage updated submodule refs in hub: `git add projects/{name}`
3. Return a report: which refs updated, which skipped (PRs still open), which had no changes

This is the key safety mechanism — hub refs ONLY move forward when code has been reviewed and merged. No more pushing to wrong branches because the hub only ever points at deploy branch HEAD.

Files: src/projectman/hub/registry.py