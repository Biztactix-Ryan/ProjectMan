---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-32-4
points: 1
status: todo
story_id: US-PM-32
tags: []
title: baseline capture --since filters sessions by start time and records the window
  in provenance
updated: '2026-09-06'
---

In tools/usage_telemetry/baseline.py add --since <ISO-8601> to the capture subcommand. A session is included only when its first transcript timestamp is at or after the cutoff; the provenance block gains window_since and the count of sessions excluded. Add a helper that finds the earliest session in the corpus whose pm_update result carries note_truncated (the post-US-PM-1 signature) so the cutoff can be derived rather than guessed, exposed as --since auto. Unit test with a small fixture corpus.