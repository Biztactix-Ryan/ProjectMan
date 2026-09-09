---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-49-8
points: 1
status: done
story_id: US-PM-49
tags: []
title: Add the dirty-tree warning and the no-memory-reads rule to the skill
updated: '2026-09-09'
---

Phase 1 step 4 of skill_pm_orchestrate.md.j2: after `git status --short`, if the entry count exceeds 200, warn that the snapshot and diff steps walk this list on every dispatch and suggest committing or cleaning first; under --auto continue and carry the warning into the Phase 4 report. Operating Model gains one rule: the orchestrator reads only store tools and the repo files a verdict needs, never memory files under ~/.claude or session transcripts.