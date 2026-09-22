---
assignee: claude
created: 2026-02-17
id: US-PRJ-10-11
points: 3
status: done
story_id: US-PRJ-10
title: Write tests for changeset lifecycle
updated: '2026-02-19'
---

Test the full changeset lifecycle from creation to hub ref update.

1. **Create changeset**: create with 3 projects → stored in .project/changesets/, status=open
2. **Create PRs**: mock gh cli → 3 PRs created with cross-references, PR numbers stored
3. **Partial merge**: 2 of 3 PRs merged → status=partial, hub refs NOT updated
4. **All merged**: 3rd PR merged → status=merged, hub refs updated in single commit
5. **PR rejected**: one PR closed without merge → changeset flagged, other PRs get warning comment
6. **Dashboard integration**: changeset context appears in git_status_all output
7. **Add project to existing changeset**: add a 4th project mid-flight → changeset updated
8. **Multiple active changesets**: 2 changesets with overlapping projects → tracked independently

Files: tests/test_changesets.py