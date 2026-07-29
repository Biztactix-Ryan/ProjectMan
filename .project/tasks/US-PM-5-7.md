---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-5-5
id: US-PM-5-7
points: 2
status: done
story_id: US-PM-5
tags: []
title: Add an audit check for criteria and test-task drift
updated: '2026-07-29'
---

pm_audit reported 'Errors: 0 | Warnings: 0 | Info: 0 — No issues found. Project is clean.' while this drift was live. Add a check for stories whose acceptance criteria have no matching test task, and for test tasks quoting criteria that no longer exist.

This matters for the orchestrator: pm-orchestrate uses pm_audit as its systemic health check and stops on ERROR-level findings, so blind spots here are blind spots in the safety net.