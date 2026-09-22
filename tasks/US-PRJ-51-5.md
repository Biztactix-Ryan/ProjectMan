---
archived: true
assignee: null
created: '2026-09-04'
depends_on:
- US-PRJ-51-4
id: US-PRJ-51-5
points: 1
status: todo
story_id: US-PRJ-51
tags: []
title: Verify YAML round-trip writes plain strings and rejects bad entry statuses
updated: '2026-09-05'
---

Check how Store saves ChangesetFrontmatter (store.py ~L2437 and ~L2487 construct entries; find the frontmatter dump) and make sure enum values serialise as plain strings ('merged', not 'ChangesetEntryStatus.merged') and load back into the enum. Loading a changeset file whose entry status is not in the enum must fail with a clear validation error rather than silently accepting the string. Add the fixtures to tests/test_changeset.py.