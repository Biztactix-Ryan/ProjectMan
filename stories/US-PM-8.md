---
acceptance_criteria:
- Each of the four verdicts has a verb that sets status and outcome structurally
- Outcome cannot be omitted on a terminal verdict
- pm-orchestrate SKILL.md uses the verdict verbs throughout
- Existing pm_update status writes keep working for backwards compatibility
- Measured share of completions lacking a run-log entry drops to zero
created: '2026-07-29'
depends_on:
- US-PM-7
epic_id: EPIC-PM-2
id: US-PM-8
points: 8
priority: must
status: done
tags:
- workflow
- orchestrator
- api-design
title: Verdict verbs for the orchestrator state machine
updated: '2026-08-21'
---

As an orchestrator, I want each of my four verdicts to have its own verb, so that status and outcome cannot be spelled wrong or forgotten.

pm-orchestrate/SKILL.md step 19 defines exactly four terminal moves — Accept, Retry, Park, Accept-as-review — and each is currently expressed as a generic pm_update where the model must remember the correct status + outcome + note triple. The data shows it does not:

- 13% of status=done writes carry no note or outcome at all (Study C: 163 of 1,266). The run-log trail the schema exists to capture is silently missing on one completion in eight.
- The outcome vocabulary has collapsed to ~90% success (Study D: success 896, partial 89, info 42, blocked 5, failed 5). Five values exist; two are used.
- 512 pm_grab-then-pm_update(done) pairs still beat 387 pm_done_next calls, despite the docstring at server.py:1343 explicitly saying to use pm_done_next instead. Documentation has already measurably lost this argument.

Proposed: pm_accept / pm_retry / pm_park / pm_review, with pm_release from US-PM-7. Each sets status and outcome structurally, so neither can be omitted or mismatched. This subsumes the "strengthen pm_done_next's description" recommendation that three of the four studies reach for — naming the verb after the intent wins where wording the docstring did not.

Consider whether pm_accept absorbs pm_done_next's next-task return, or whether they stay separate.