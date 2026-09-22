---
assignee: claude
created: '2026-02-17'
id: US-PRJ-6-6
points: 2
status: done
story_id: US-PRJ-6
title: Update hub mode docs with coordinated push and PR workflow
updated: '2026-02-24'
---

Update hub mode documentation to cover the new git integration.

Files to update:
1. **docs/hub-mode/setup.md** — add conventions config section, deploy_branch setup per subproject
2. **docs/hub-mode/cron.md** — update nightly job to include `projectman commit --scope all` after sync/audit
3. **New: docs/hub-mode/git-workflow.md** — dedicated doc covering:
   - The opinionated workflow (feature branches → PR → deploy → hub ref update)
   - Coordinated push explained with diagrams
   - Handling conflicts (hub ref auto-rebase)
   - Cross-repo changesets
   - Convention reference (branch naming, commit messages)

Files: docs/hub-mode/setup.md, docs/hub-mode/cron.md, docs/hub-mode/git-workflow.md