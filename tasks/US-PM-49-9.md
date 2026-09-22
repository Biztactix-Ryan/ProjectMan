---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-49-6
- US-PM-49-7
- US-PM-49-8
id: US-PM-49-9
points: 1
status: done
story_id: US-PM-49
tags: []
title: Update skill-content tests and regenerate rendered copies
updated: '2026-09-09'
---

Adjust tests that assert on pm-orchestrate and pm-do wording for the projection calls, the trimmed worker prompt, the report shape, the dirty-tree threshold and the no-memory-reads rule. Regenerate the tracked rendered copies under .claude/ via scratchpad + cp.