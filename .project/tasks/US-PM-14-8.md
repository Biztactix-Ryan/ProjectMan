---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-14-6
id: US-PM-14-8
points: 1
status: done
story_id: US-PM-14
tags: []
title: Document a resume path in pm-orchestrate
updated: '2026-08-22'
---

There is currently no crash-recovery path. A run that dies mid-loop leaves tasks claimed by claude with no way to determine intent. Define what a resuming run does with claims it finds.