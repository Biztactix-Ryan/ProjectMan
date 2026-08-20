---
created: '2026-08-20'
id: EPIC-PM-3
points: null
priority: should
status: draft
tags:
- git
- storage
- architecture
target_date: null
title: Orphan-branch worktree storage for PM data
updated: '2026-08-20'
---

Move .project/ out of main's history onto a dedicated orphan branch ("projectman") mounted back into the repo root as a git worktree. Locally nothing changes: .project/ stays as plain files in the repo root and Claude Code / the MCP server read and write them exactly as now — but commits made inside that directory land on the projectman branch with its own history, so `git log main` never sees a task update again.

Design rationale (decided 2026-08-20):
- Local-first stays intact; files are where they've always been. Git commands run inside .project/ automatically target the projectman branch because it's a worktree, so pm_commit/pm_push that shell out to git in the store directory may work with zero code changes (must verify).
- Forgejo is the sync server for free: same remote, same permissions, same backups. The Forgejo UI can browse the branch, render the markdown, and show PM-only history separately from code history. Forgejo Actions can hang off the projectman branch later (e.g. regenerate burndown on push).
- Clean separation: `git clone --single-branch` and shallow CI clones never pull PM data; main's history is purely code.

One-time migration per repo:
1. `git switch --orphan projectman` → empty commit "ProjectMan root" → push -u → back to main
2. `git rm -r --cached .project`, stash the files aside, add `.project/` to .gitignore, commit on main
3. `git worktree add .project projectman`, restore files, commit + push on the projectman branch
(History-preserving variant: `git filter-repo --subdirectory-filter .project` into the orphan branch; a snapshot import is acceptable since the activity log rides along.)

Known rough edges to handle:
- Fresh clones need `git worktree add .project projectman` before data appears — build into projectman init: detect origin/projectman and attach automatically; add a `projectman attach` command.
- `git clean -fdx` won't recurse into the worktree unless -ff; .project is now ignored-but-precious. Document it.
- PM data lives in the same repo, so on public repos the branch is visible. Private-data variant: sibling <repo>-pm repository cloned into .project/ (still gitignored) — same local ergonomics, separate permissions, two repos per project.
- Avoid the hub-mode submodule approach for this: a submodule pointer in main means every task update dirties the parent repo — exactly the noise being eliminated.

Rejected alternatives: branch-switching (ugly), Forgejo wiki repo (flat naming + YAML frontmatter handling make it a poor fit). Future option: one-way n8n sync from .project frontmatter to Forgejo issues via API for board visibility, without moving the source of truth.