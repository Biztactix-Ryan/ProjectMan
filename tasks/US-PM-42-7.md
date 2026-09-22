---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-42-5
- US-PM-42-6
- US-PM-42-8
- US-PRJ-52-10
- US-PM-43-7
id: US-PM-42-7
points: 1
status: done
story_id: US-PM-42
tags: []
title: Cut the 0.9.0 section and bump the version
updated: '2026-09-08'
---

Depends on the Sprint 13 code stories so the release notes can include them. Add entries for US-PRJ-34 (parallel hub rollup), US-PRJ-52 (activity log reader and rotation with its config key) and US-PM-43 (audit warning rules) to the Unreleased section, then rename Unreleased to [0.9.0] dated the day the task runs and open a fresh empty Unreleased heading above it. Bump the version to 0.9.0 in pyproject.toml and every place the previous task listed. Run the full suite. Tagging and pushing are the user's step and are noted in NEXT.md, not done here.