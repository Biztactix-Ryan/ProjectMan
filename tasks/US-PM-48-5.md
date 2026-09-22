---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-48-5
points: 2
status: done
story_id: US-PM-48
tags: []
title: Add the validator prompt template to skill_pm_orchestrate.md.j2
updated: '2026-09-09'
---

Add a second fenced prompt block, after the worker prompt template, for the validator subagent. Inputs it receives: task id, run id, the DoD list and acceptance criteria, the step 14 snapshot path with its md5 list, and the worker's report. It runs `git status --short`, `git diff --stat` against the snapshot, the md5 comparison of files the task must not touch, and the tests the DoD names. It answers with exactly one JSON object: {verdict: accept|retry|park|review, files: [...], tests: [{command, passed, summary}], dod_met: [...], dod_unmet: [...], note: "<=200 chars"}, total under about 1500 characters, no prose before or after. Same rules as the worker: no git checkout/restore/stash/reset, no commits, no store writes.