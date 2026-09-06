---
created: '2026-09-06'
id: EPIC-PM-5
points: null
priority: should
status: done
tags:
- hub
- architecture
- subtraction
target_date: null
title: Hub redesign — PM data lives with its code
updated: '2026-09-06'
---

Follow-on to EPIC-PM-4 (subtraction), scoped from the 2026-09-05 audit and planned on 2026-09-06. The audit found the hub clunky for three structural reasons: per-project PM data lives in the hub repo under .project/projects/{name}/ rather than with the code it describes; every tool carries an optional `project` argument even though the ID prefix already names the store; and epics are documented as cross-project but stored per store.

Direction (agreed 2026-09-05): each subproject's PM data lives at projects/{name}/.project, mounted as a worktree of that repo's own `projectman` branch (the EPIC-PM-3 design, applied per submodule). The hub becomes a read-only rollup over those stores plus its own hub-level docs, epics and dashboards. The `project` argument is dropped from every tool: an ID's prefix names the store, and the few ID-less verbs take a `prefix`. Epics exist at hub level only and roll up stories from every subproject.

Success criteria: no tool in the MCP list has a `project` parameter; `pm_get("US-API-3")` in a hub finds the API store with no other argument; `.project/projects/` no longer exists after `projectman migrate-hub`; `hub/registry.py` no longer commits, pushes or repairs on behalf of subprojects; `pm_epic` on a hub epic rolls up stories from every subproject store; single-project mode is unchanged throughout.

Out of scope: any n8n or Forgejo issue sync; the private sibling-repo variant beyond what EPIC-PM-3 already documents.