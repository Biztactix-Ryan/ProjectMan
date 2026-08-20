---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-7-6
id: US-PM-7-7
points: 3
status: done
story_id: US-PM-7
tags: []
title: Implement compare-and-swap claiming in the store
updated: '2026-08-20'
---

Claiming must be atomic so two concurrent workers cannot both win the same task. This is the primitive pm-orchestrate/SKILL.md names as its blocker for parallel workers.

Consider a claim timestamp or lease to make stale claims identifiable — US-PM-14 builds on this.