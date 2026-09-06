---
acceptance_criteria:
- docs/hub-mode/setup.md shows the projects/{name}/.project layout and the add-project
  and migrate-hub and attach flows with no mention of .project/projects
- No doc under docs/ describes a project tool argument or the coordinated push or
  repair commands
- ADR-003 in .project/DECISIONS.md records the hub redesign decision and the alternatives
  considered
created: '2026-09-06'
depends_on:
- US-PM-35
- US-PM-36
epic_id: EPIC-PM-5
id: US-PM-37
points: 3
priority: should
status: done
tags:
- hub
- docs
title: Hub-mode docs describe the projects/{name}/.project layout and the prefix-routed
  tool surface
updated: '2026-09-06'
---

As someone setting up or maintaining a hub, I want docs/hub-mode and the reference docs to describe the layout that exists after EPIC-PM-5, so that nobody follows setup.md into creating .project/projects/{name} or passes a project argument that no longer exists.

Scope: rewrite docs/hub-mode/setup.md (structure diagram, add-project, migrate-hub, attach on clone), git-workflow.md (per-store commit and push, sync), epics.md (hub-level epics and the rollup), dashboards.md and cron.md as needed; sweep docs/reference/mcp-tools.md, cli.md, file-formats.md and skills.md for `project` and `.project/projects`; retire or fold the four audit-era documents (workflow-audit.md, hub-workflow-audit.md, workflow-pain-points.md, submodule-drift.md, multi-developer-conflicts.md) into a short "history" section rather than leaving them describing a design that no longer exists. Record the redesign as ADR-003 in .project/DECISIONS.md.