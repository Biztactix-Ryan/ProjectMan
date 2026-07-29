---
acceptance_criteria:
- Warnings that would fire on every item in a project are suppressed
- Determine whether the templates or the checks are at fault before removing
- Payload size for pm_grab drops measurably
- Test asserts no warning has a 100 percent hit rate across a sample project
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-4
points: 2
priority: should
status: done
tags:
- context-cost
- quick-win
title: Remove the always-on readiness warnings
updated: '2026-07-29'
---

As an agent reading a task payload, I want warnings to mean something, so that I do not skip a block that is identical on every item.

`readiness.py:66-70` appends three warnings unconditionally:
- no Implementation section in description
- no Testing section in description
- no Definition of Done checklist

Study B measured every payload carrying a warnings block carrying exactly these three, with a 100% hit rate across 758 occurrences. At ~130 chars per block that is ~98,500 chars / ~25k tokens of pure noise in that sample alone.

A warning that fires on every item carries zero information, and the corpus shows it is being correctly ignored: only 45 pm_update calls in the entire Study B sample ever set `body` or `acceptance_criteria`, and most of those were scoping work rather than warning-driven remediation.

Options: drop them entirely, emit only when they deviate from the project default, or fold into a single readiness score. Note the warnings may be firing because the project templates do not produce these sections — worth checking whether the template or the check is wrong before deleting.