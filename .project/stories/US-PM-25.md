---
acceptance_criteria:
- Rendered pm-orchestrate skill is at most 9000 characters
- docs/reference/orchestrate-design.md holds the rationale and resume protocol and
  the skill links to it
- The worker prompt template contains the five worker safety rules verbatim
- Task point range and audit check count and skill count and the story-closing call
  agree with the other skill templates and with the code
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-25
points: 5
priority: must
status: done
tags:
- skills
- orchestrator
- subtraction
title: pm-orchestrate skill is under 9KB of instruction with its rationale in a reference
  doc
updated: '2026-09-05'
---

As an orchestrating agent, I want the pm-orchestrate skill to be a short set of true instructions so that I spend context on the sprint instead of on an essay and never act on two rules that contradict each other.

Today src/projectman/templates/skill_pm_orchestrate.md.j2 is 31,731 bytes. Most of it is rationale (why stage-only, why the resume protocol looks the way it does, the 48,588-char pm_context anecdote) rather than instruction. The audit also found it contradicting the other skills and itself: task points "1-3" in one place and "1-5" in another; the audit check count given as 13 and as 16; the skill count given as 5 and as 7; and both pm_done_next and pm_accept described as the call that closes a story.

Hard-won worker rules from Sprints 5-7 that must be in the worker prompt template (not just in someone's memory):
- Never run git checkout / restore / stash / reset — earlier tasks' uncommitted work lives in the working tree; undo a temporary edit with the same edit tool.
- Never call pm_create_* or Store writes outside a tmp_path-isolated fixture.
- Edit tracked files directly with the Edit tool; do not stage code through scratchpad files.
- If a task mutation-tests source files they must end byte-identical; the orchestrator checks md5s.
- Tasks touching git plumbing must not run the new command against the real repo.

Split: instruction stays in the template; the rationale and the resume-protocol essay move to docs/reference/orchestrate-design.md and the template links to it once. Tests in tests/test_skill_*.py assert on template contents and must keep passing (or be updated when the wording they pin is deliberately changed).