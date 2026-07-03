---
acceptance_criteria:
- Pre-push check validates submodule branch matches .gitmodules tracking
- Clear error message on branch mismatch showing expected vs actual
- Can be run standalone as a validation command
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-2
points: 5
priority: must
status: done
tags: []
title: Add pre-push validation for submodule branch alignment
updated: '2026-02-19'
---

As a developer, I want the system to validate that each submodule is on its expected tracked branch before pushing so that I never accidentally push to the wrong branch.

Before any push operation, check:
- Each submodule's current HEAD branch matches the branch configured in .gitmodules
- Warn/abort if a submodule has drifted to a different branch
- Report which submodules are misaligned and what the expected vs actual branches are