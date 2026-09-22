---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-31-6
id: US-PM-31-7
points: 3
status: done
story_id: US-PM-31
tags: []
title: add-project attaches or creates the submodule's projectman branch worktree
updated: '2026-09-06'
---

In hub/registry.add_project, after the submodule is added: if origin/projectman exists on the submodule, call worktree.attach_worktree(submodule_root, branch='projectman') so projects/{name}/.project is mounted; otherwise create the orphan branch with worktree._create_orphan_branch, mount it, and scaffold the store with _init_subproject into the mounted path, then commit on the branch. Stop writing to .project/projects/{name}. Ensure .project/ is gitignored on the submodule's main branch via worktree.ensure_gitignore_entry. Files: src/projectman/hub/registry.py, src/projectman/worktree.py.