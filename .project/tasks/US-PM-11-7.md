---
assignee: null
created: '2026-07-29'
depends_on:
- US-PM-11-6
id: US-PM-11-7
points: null
status: todo
story_id: US-PM-11
tags: []
title: Pass the previous digest from the orchestrator health check
updated: '2026-07-29'
---

SKILL.md step 21 re-runs pm_audit every 3 accepted tasks. Thread the previous digest through so unchanged health checks are nearly free.

Note for reviewers: the repeated pm_audit calls the studies flagged as waste (Study D 92 of 139 byte-identical; Study C up to 6 per session) are this health check working as designed. Caching per session, as Study D recommends, would disable it.