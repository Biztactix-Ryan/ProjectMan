---
acceptance_criteria:
- docs/telemetry/baseline-post-subtraction.json and .md exist and were produced by
  the same extractor as the pre-fix baseline
- The baseline provenance test passes on any checkout because it pins a commit and
  a relative path
- The post-subtraction markdown compares calls per task and context per worker against
  the pre-fix numbers
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-30
points: 2
priority: should
status: done
tags:
- telemetry
- subtraction
title: Post-subtraction telemetry baseline
updated: '2026-09-05'
---

As a maintainer, I want a fresh usage-telemetry baseline captured after the Sprint 8 changes so that the claims made for Sprints 1-7 (fewer calls per task, less context per worker) are finally measured against something instead of asserted.

docs/telemetry/baseline-pre-fix.{json,md} is the only baseline and it predates every sprint. The provenance test tests/test_usage_telemetry_baseline.py::test_the_committed_baseline_pins_the_code_that_produced_it fails on any checkout other than the original author's because the baseline pins an absolute repo path; that should pin a commit SHA and a relative path instead.

Must run after the subtraction stories land so the baseline reflects the new tool surface. Left out of the subtraction sprint for capacity; goes first in the next one.