---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-47-4
id: US-PM-47-5
points: 1
status: done
story_id: US-PM-47
tags: []
title: Record ADR-004 and add a hub-free docs sweep test
updated: '2026-09-08'
---

Append ADR-004 'Hub mode is removed (2026-09-08)' to .project/DECISIONS.md via pm_update_doc or a direct edit of the tracked file: status Accepted, supersedes ADR-003 (mark ADR-003 Superseded by ADR-004); context: the 2026-09-05 audit measured 9 hub/changeset uses in 484 sessions and 71 of 97 error sites with zero traffic mostly hub and web, the ADR-003 redesign (59 points, Sprints 10 to 11) gained no user, US-PRJ-34 archived as moot 2026-09-08; decision: single-project mode only, IDs keep their prefix, ADR-001 orphan-branch storage unchanged; consequences: existing hubs keep working on 0.8.x, a legacy config with hub keys loads with the keys ignored, no migration path is offered. Extend tests/test_docs_after_subtraction.py with a sweep asserting that no file under docs/, README.md or src/projectman/templates mentions 'hub mode', 'migrate-hub', 'add-project' or a prefix argument, exempting CHANGELOG.md, DECISIONS.md and the history-marked reference docs. Run the docs tests.