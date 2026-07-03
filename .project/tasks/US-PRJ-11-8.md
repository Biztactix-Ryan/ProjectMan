---
assignee: claude
created: '2026-02-17'
id: US-PRJ-11-8
points: 3
status: done
story_id: US-PRJ-11
title: Implement fast-forward check for conflicting submodule refs
updated: '2026-02-19'
---

Add `check_ref_fast_forward(project_name, our_ref, their_ref, root)` to `hub/registry.py`.

When two developers update the same submodule ref:
1. Get both refs: ours (local) and theirs (from origin/main after fetch)
2. Check if one is an ancestor of the other: `git merge-base --is-ancestor {old} {new}` in the subproject
3. If their_ref is ancestor of our_ref → ours is newer, keep ours (fast-forward)
4. If our_ref is ancestor of their_ref → theirs is newer, take theirs
5. If neither is ancestor → diverged, cannot auto-resolve. Flag for manual resolution with message:
   ```
   Conflict: project 'api' ref diverged.
   Local:  a1b2c3d (from branch: pm/US-1/auth)
   Remote: x9y8z7w (from branch: pm/US-2/refactor)
   These branches diverged — resolve in the subproject first.
   ```

Integrate with auto-rebase (previous task): during rebase conflict resolution, if the conflict is a submodule ref, call this function to attempt auto-resolution.

Files: src/projectman/hub/registry.py