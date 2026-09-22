---
acceptance_criteria:
- Changeset and web tool families are hidden unless enabled by config
- Repair and restore tooling is hidden from the agent tool list but reachable via
  CLI
- pm_activity and pm_context and pm_estimate remain exposed
- Tool-list payload size drops measurably with default config
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-15
points: 3
priority: could
status: done
tags:
- context-cost
- config
- api-surface
title: Gate the unused tool families behind config flags
updated: '2026-08-22'
---

As an agent loading the ProjectMan tool list, I want only the tools this project actually uses, so that schema tokens are not spent on dead surface in every request.

46 tools are registered. Intersecting the never-called lists from all four studies gives 14 tools that were called zero times across ~14,200 calls, ~1,500 sessions, 4 machines and ~13 consumer repos:

    pm_activity, pm_changeset_create, pm_changeset_status,
    pm_changeset_add_project, pm_changeset_create_prs, pm_changeset_push,
    pm_web_start, pm_web_stop, pm_web_status,
    pm_fix_malformed, pm_push_all, pm_restore, pm_validate_branches, pm_repair

That is roughly 30% of the API surface. Whole families are dark: all changeset tools and all web tools.

Two important carve-outs:
- pm_activity should NOT be gated — US-PM-14 puts it to work. Its zero usage is a wiring gap, not a signal it is unwanted. Same reasoning applies to pm_context and pm_estimate in US-PM-13.
- The repair/restore/validate cluster is human break-glass tooling. Gate it from the agent-facing tool list, do not delete it.

Gate by config flag or hub-mode check rather than removal, so opting in is a one-line change.