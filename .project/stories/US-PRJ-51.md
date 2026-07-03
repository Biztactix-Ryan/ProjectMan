---
acceptance_criteria:
- ChangesetEntry.status uses same enum as ChangesetFrontmatter
- All status assignments validated against enum values
- Serialization/deserialization handles enum correctly
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-51
points: 2
priority: should
status: backlog
tags:
- quality
- models
title: Fix ChangesetEntry status type inconsistency
updated: '2026-03-09'
---

As a developer, I want consistent type usage so that status values are always validated. ChangesetEntry.status is a raw string while ChangesetFrontmatter.status uses an enum. This inconsistency can cause validation errors when saving. Unify to use enum throughout.