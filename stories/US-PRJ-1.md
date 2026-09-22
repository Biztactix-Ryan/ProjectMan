---
acceptance_criteria:
- Pain points documented with concrete scenarios
- Current workflow steps listed end-to-end
- Failure modes catalogued with severity
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-1
points: 3
priority: must
status: done
tags: []
title: Audit & document current hub git workflow pain points
updated: '2026-02-17'
---

As a developer, I want a clear document of the current hub workflow (commit, push, sync across submodules) and its failure modes so that we have a shared understanding of what needs fixing.

Investigate and document:
- Current manual steps required after PM operations (commit/push)
- Submodule branch tracking drift scenarios
- Multi-project simultaneous update failure modes
- Hub-on-main vs subproject branching tension
- What happens when two people push conflicting submodule refs