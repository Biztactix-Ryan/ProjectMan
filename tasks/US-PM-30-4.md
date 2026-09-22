---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-30-4
points: 2
status: done
story_id: US-PM-30
tags: []
title: Pin baseline provenance to a commit and a repo-relative path
updated: '2026-09-05'
---

tools/usage_telemetry/baseline.py git_provenance() records repo as an absolute path (str(repo)), so tests/test_usage_telemetry_baseline.py::test_the_committed_baseline_pins_the_code_that_produced_it (assert Path(git['repo']).resolve() == REPO_ROOT.resolve()) fails on every checkout except the original author's. Record the repo as a path relative to the repo root ("." for the root itself) alongside the 40-char commit SHA, keep branch and dirty, and change the test to assert the relative form plus that the commit object exists (skip when absent, as now). Update docs/telemetry/baseline-pre-fix.json provenance.git.repo to the relative form without touching any number in it, and note the field change in docs/telemetry/README.md. Acceptance: the provenance test passes from a fresh clone at any path.