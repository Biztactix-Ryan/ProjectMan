---
archived: true
assignee: null
created: '2026-09-04'
depends_on: []
id: US-PRJ-51-4
points: 1
status: todo
story_id: US-PRJ-51
tags: []
title: Add ChangesetEntryStatus enum and type ChangesetEntry.status with it
updated: '2026-09-05'
---

In src/projectman/models.py add class ChangesetEntryStatus(str, Enum) with pending/open/merged/closed (the vocabulary actually used: default 'pending' at L259, assignments in changesets.py:229-233). Change ChangesetEntry.status to ChangesetEntryStatus = ChangesetEntryStatus.pending. In src/projectman/changesets.py replace the three bare-string assignments and the comparisons at L252-253 with the enum. Anything else that reads entry.status (web routes, cli) must compare against the enum or .value consistently. Do NOT merge it with ChangesetStatus: a changeset can be 'partial' and an entry can be 'pending'; the sets differ.