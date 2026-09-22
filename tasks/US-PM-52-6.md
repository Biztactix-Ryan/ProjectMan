---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-52-5
id: US-PM-52-6
points: 1
status: done
story_id: US-PM-52
tags: []
title: Add the projectman orch-cost CLI command
updated: '2026-09-09'
---

cli.py: `projectman orch-cost <run-id> [--transcripts DIR] [--json]` prints a short table of the analyze() result (one row per transcript when several match) or the dict as JSON. Document it in docs/reference/cli.md with the 2026-09-09 baseline numbers as an example of what to expect.