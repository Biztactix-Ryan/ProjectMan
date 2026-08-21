---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-8-6
points: 2
status: done
story_id: US-PM-8
tags: []
title: Specify the four verdict verbs
updated: '2026-08-21'
---

Map each of SKILL.md step 19's verdicts to a verb and fix its status and outcome:
- Accept → done + success
- Retry → todo + failed
- Park → review + blocked
- Accept-as-review → review + partial

Decide whether pm_accept absorbs pm_done_next's next-task return or whether the two stay separate. Note pm_done_next already returns next: null in 22% of calls (Study B), so the composed verb must handle exhaustion cleanly.