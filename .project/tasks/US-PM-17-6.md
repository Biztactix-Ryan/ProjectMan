---
assignee: null
created: '2026-07-30'
depends_on: []
id: US-PM-17-6
points: 2
status: todo
story_id: US-PM-17
tags: []
title: Decide and document how an archive is positively identified
updated: '2026-07-30'
---

The root cause is that the old archive left no distinguishing signal, so detection relies on a shape that genuine completion also produces. Settle the approach before touching code, and write it into the migrations module docstring.

Options to weigh:
1. Require a positive signal (e.g. an activity-log event whose source was Store.archive, or a recorded archive marker) and accept that pre-signal archives are unrecoverable by machine — consistent with the existing stance on in-progress archives.
2. Narrow rule 3 further using evidence genuine completion tends to leave (a run-log entry on the task, an assignee, a points value) and treat anything ambiguous as needs_review rather than a candidate.
3. Make the migration report-only for the ambiguous shape and require an explicit per-task confirmation to write.

Deliverable is the decision plus the docstring rewrite, since the current text makes a safety guarantee the code does not honour.