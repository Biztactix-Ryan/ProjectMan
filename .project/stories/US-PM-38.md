---
acceptance_criteria:
- tests/test_orchestrate_design_doc.py and tests/test_orchestrate_skill_size.py read
  the pre-rewrite template from the pinned commit 1061084 rather than HEAD and skip
  with a reason when git cannot show it
- test_report_is_the_default_at_every_entry_point proves --apply is off by default
  in a way that passes on the installed click and on click 8.1
- The full unit suite passes with zero failures outside tests/integration and the
  environment-blocked telemetry baseline test
created: '2026-09-06'
depends_on: []
epic_id: null
id: US-PM-38
points: 2
priority: must
status: backlog
tags:
- testing
- quality
title: 'The full suite is green: template-history tests pin a commit and the click
  flag assertion matches the installed click'
updated: '2026-09-06'
---

As a maintainer, I want every unit test to pass on a clean checkout of main so that "full suite green" means something at the next sprint close. Two test files, tests/test_orchestrate_design_doc.py and tests/test_orchestrate_skill_size.py, read the pre-rewrite orchestrate skill template with `git show HEAD:src/projectman/templates/skill_pm_orchestrate.md.j2`. That was true while Sprint 8 sat uncommitted; since 9dc6379 landed, HEAD holds the 9,074-byte rewritten template and 15 tests fail (14 parametrised rationale-migration cases, one absorbed-map case, one size falsification guard). The pre-rewrite template (31,731 bytes) lives at commit 1061084, the parent of 9dc6379, and this history is post-rewrite so the SHA is stable. Pin that commit instead of HEAD, and skip with a reason when git cannot show it (source tarball, shallow checkout). Separately, tests/test_migrate_archived_as_done.py::TestTheDocstringMatchesTheCode::test_report_is_the_default_at_every_entry_point asserts a click boolean flag's `.default is False`; the installed click reports `Sentinel.UNSET` for an is_flag option, so the assertion must prove "--apply is off by default" a way that holds across click versions (call the command without --apply and check apply_changes is falsy, or accept the sentinel alongside False). Known environment-blocked failures (tests/integration and the one telemetry-baseline provenance test) stay out of scope.