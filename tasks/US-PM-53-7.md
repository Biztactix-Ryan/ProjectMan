---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-53-6
- US-PM-51-11
id: US-PM-53-7
points: 3
status: done
story_id: US-PM-53
tags: []
title: Add --lanes to the orchestrate skill with two tracked claims
updated: '2026-09-09'
---

skill_pm_orchestrate.md.j2: flag `--lanes <1|2>` default 1. With two lanes the orchestrator keeps a small table of lane -> task id, branch, launch time. Dispatch is `Agent` in the background (run_in_background) so the notification arrives as a message; the second lane is filled only from pm_board(brief=True, lane_compatible_with=<lane 1 task>) and never with a task whose dependency is in flight. --max and the every-3-accepts health check count across both lanes. When nothing lane-compatible is ready, lane 2 idles and the loop says so in the report.