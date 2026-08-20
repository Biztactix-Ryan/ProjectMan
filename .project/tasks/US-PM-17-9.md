---
assignee: claude
created: '2026-07-30'
depends_on:
- US-PM-17-7
id: US-PM-17-9
points: 1
status: done
story_id: US-PM-17
tags: []
title: Resolve the four live candidates in this repo
updated: '2026-08-20'
---

US-PRJ-29-2 through US-PRJ-29-5 were closed straight from todo by a /pm audit pass and are currently migration candidates, so migrate-archived --apply would revert them. Once detection is fixed, confirm they are no longer candidates. If the chosen approach also drops the two genuine legacy archives (US-PM-1-1, US-PM-2-1), correct those two by hand and record it, so the metrics fix US-PM-16 delivered is not quietly lost. Satisfies US-PM-17-3.