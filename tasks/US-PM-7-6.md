---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-7-6
points: 2
status: done
story_id: US-PM-7
tags: []
title: Design the claim and release contract
updated: '2026-07-30'
---

Decide the surface: a dedicated pm_release verb, an unassign boolean on pm_update, or both. Constraint from the evidence — whatever is chosen must have no malformed form. A boolean cannot be emitted as a bare key; an empty-string sentinel demonstrably can.

Also decide the clear affordance for depends_on and tags. Study C measured 17 malformed depends_on clears with no documented sentinel at all.