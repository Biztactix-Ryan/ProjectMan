---
acceptance_criteria:
- ChangesetEntry.status is a ChangesetEntryStatus enum rather than a raw string
- All status assignments validated against enum values
- Serialization/deserialization handles enum correctly
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-51
points: 2
priority: should
status: archived
tags:
- quality
- models
title: Fix ChangesetEntry status type inconsistency
updated: '2026-09-05'
---

As a developer, I want consistent type usage so that status values are always validated. ChangesetEntry.status is a raw string while ChangesetFrontmatter.status uses an enum.

Archived at Sprint 9 planning (2026-09-05): obsolete. US-PM-27 removed changesets from the package in Sprint 8; ChangesetEntry, ChangesetStatus and changesets.py no longer exist in src/, so there is nothing to fix.