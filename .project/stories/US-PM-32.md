---
acceptance_criteria:
- baseline capture accepts a --since timestamp and excludes sessions that started
  before it and the provenance block records the window
- docs/telemetry/baseline-windowed-post-fix.md and .json exist and compare against
  both the pre-fix and the post-subtraction baselines
- The windowed markdown states for each Sprint 1 to 9 claim whether it holds once
  sessions predating the note-length fix are excluded
created: '2026-09-06'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-32
points: 2
priority: should
status: done
tags:
- telemetry
- measurement
title: Telemetry re-capture windowed to sessions after the note-length fix
updated: '2026-09-06'
---

As the person judging whether Sprints 1 to 9 helped, I want a baseline comparison that only counts sessions run against code that has the US-PM-1 note-truncation fix, so that the verdict on calls per task and context per worker is not dominated by a defect that was fixed in Sprint 3.

The post-subtraction baseline (docs/telemetry/baseline-post-subtraction.md) found 906 of 941 soft errors were pm_update rejecting a run-log note over 1024 characters. That message no longer exists in the source or the installed server, yet the corpus mixes months of pre-fix sessions with post-fix ones, so calls per session, bytes per session and failure rate all read worse and the headline verdict says "not supported".

Direction: give `tools.usage_telemetry.baseline capture` a `--since <ISO timestamp>` filter on session start time, capture `baseline-windowed-post-fix` with the window starting at the first session whose transcript shows the note_truncated response rather than the rejection, write the comparison against both existing baselines, and state plainly in the markdown which claims hold once the defect is excluded.