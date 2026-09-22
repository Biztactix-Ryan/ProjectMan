---
assignee: claude
created: '2026-02-17'
id: US-PRJ-6-5
points: 2
status: done
story_id: US-PRJ-6
title: Update daily-workflow.md with git integration steps
updated: '2026-02-24'
---

Rewrite docs/user-guide/daily-workflow.md to include git operations as part of the standard flow.

Current doc covers PM operations only. Add:
1. **Start of day**: `projectman git-status` to see what needs attention across all repos
2. **Grab a task**: `projectman grab US-X-Y` → auto-creates feature branch `pm/US-X-Y/description`
3. **During work**: changes auto-committed if enabled, or manual `projectman commit`
4. **Ready for review**: `projectman create-pr` → opens PR against deploy branch
5. **After merge**: `projectman push` → updates hub refs
6. **End of day**: `projectman git-status` to confirm nothing left dangling

Include a quick-reference table mapping old manual workflow → new automated workflow.

Files: docs/user-guide/daily-workflow.md