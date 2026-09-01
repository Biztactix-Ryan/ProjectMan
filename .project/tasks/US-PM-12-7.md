---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-12-7
points: 2
status: done
story_id: US-PM-12
tags: []
title: Add bulk archive with an explicit ID list
updated: '2026-08-21'
---

pm_archive is 99% burst usage on Study C (266 of 269 calls inside runs of 3 or more, longest run 114).

This is the safety-relevant one: three archive calls were denied mid-sweep by Claude Code's permission classifier because a long tail of identical destructive single-item calls reads as runaway behaviour. One declared bulk call with an explicit ID list reads as one reviewable intent.