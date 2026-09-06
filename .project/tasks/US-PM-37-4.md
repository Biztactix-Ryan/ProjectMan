---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-35-7
- US-PM-35-8
- US-PM-36-7
- US-PM-36-8
id: US-PM-37-4
points: 2
status: done
story_id: US-PM-37
tags: []
title: Rewrite docs/hub-mode for the projects/{name}/.project layout and retire the
  audit-era documents
updated: '2026-09-06'
---

Rewrite docs/hub-mode/setup.md (structure diagram showing projects/{name}/.project as a worktree of each submodule's projectman branch, add-project attach-or-create, migrate-hub, attach on clone, no mention of .project/projects), git-workflow.md (pm_commit and pm_push with prefix land on the subproject's projectman branch, projectman sync as the one hub-wide verb, no coordinated push or repair), epics.md (hub-level epics, pm_create_epic writes to the hub, pm_epic rollup grouped by project, the migrate-hub epics step) and dashboards.md and cron.md where they mention the old layout or commands. Delete workflow-audit.md, hub-workflow-audit.md, workflow-pain-points.md, submodule-drift.md and multi-developer-conflicts.md and replace them with a short History section at the end of setup.md (or one history.md) that says what the old design was and links the ADR. Update docs/README or the docs index if it lists the removed files. Grep docs/hub-mode afterwards for 'project=', '.project/projects', push-all, repair, validate-branches and coordinated: zero hits.