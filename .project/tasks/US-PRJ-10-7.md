---
assignee: claude
created: '2026-02-17'
id: US-PRJ-10-7
points: 3
status: done
story_id: US-PRJ-10
title: Implement changeset PR creation with cross-references
updated: '2026-02-19'
---

Add `changeset_create_prs(changeset_id, root)` that creates PRs for all projects in a changeset with cross-references.

For each project in the changeset:
1. Push the feature branch: `git push -u origin {branch}`
2. Build PR body with cross-references:
   ```
   Part of changeset: {changeset.name}
   
   Related PRs:
   - org/api#42 (this PR)
   - org/web#18
   - org/worker#7
   ```
3. Create PR via `gh pr create --base {deploy_branch} --head {branch} --title ... --body ...`
4. Record PR number and URL back into the changeset
5. After all PRs created, update each PR body with the final cross-reference list (since PR numbers aren't known until created)

Use `gh pr edit {number} --body ...` to update cross-references after all PRs exist.

Handle: one PR creation fails → continue creating others, report partial result.

Files: src/projectman/changesets.py, src/projectman/hub/registry.py