---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-43-6
points: 2
status: done
story_id: US-PM-43
tags: []
title: done-without-evidence counts only tasks that could have carried evidence
updated: '2026-09-08'
---

check_completions_without_evidence in audit.py counts every live done task with no evidence-bearing run-log entry, which on this repo is 447 legacy completions that can never shrink. Restrict the offenders to tasks that could have carried evidence: a task whose run log has at least one entry (so a verdict was recorded but no evidence attached) or whose done transition carries a run_id. A done task with no run log at all and no run_id is a pre-contract completion and is not counted. State the rule in the docstring and in the finding message. Update the existing tests for this check and add one showing a legacy done task is not counted while an orchestrator-accepted task without evidence still is. Do not edit any historical item.