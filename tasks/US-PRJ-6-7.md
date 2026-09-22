---
assignee: claude
created: '2026-02-17'
id: US-PRJ-6-7
points: 1
status: done
story_id: US-PRJ-6
title: Update /pm skill routing for git commands
updated: '2026-02-24'
---

Add git-related command routing to .claude/skills/pm/pm.md.

New routes to add:
- `commit [--scope ...] [--message ...]` → pm_commit
- `push [--scope ...] [--dry-run]` → pm_push / coordinated_push
- `git-status` / `git status` → pm_git_status
- `validate` / `check branches` → pm_validate_branches
- `check conventions` → validate_conventions
- `create-branch <task-id>` → create_feature_branch
- `create-pr` → create_pr
- `changeset create/status/push` → changeset operations

Natural language additions:
- "commit my changes" → pm_commit
- "push everything" → coordinated_push
- "am I on the right branch?" → pm_validate_branches
- "what branches are wrong?" → pm_git_status filtered to issues

Files: .claude/skills/pm/pm.md