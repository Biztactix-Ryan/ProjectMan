---
acceptance_criteria:
- pm_board, pm_batch_get and pm_list_sprints accept a brief or fields projection and
  the orchestrate skill uses it in pre-flight and planning
- The worker prompt template carries no inline project context excerpt and caps the
  worker report at a fixed shape of about 1500 characters
- The orchestrate skill Phase 1 warns when the working tree has more than 200 dirty
  entries and names commit or clean as the fix
- The orchestrate skill forbids reading memory files or session transcripts during
  a run
created: '2026-09-09'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-49
points: 5
priority: should
status: done
tags:
- orchestrator
- context
title: Slim the orchestrator's own pre-flight, prompt and report traffic
updated: '2026-09-09'
---

As the sprint orchestrator, I want every read I make and every byte I exchange with a worker to be the projected minimum, so that the fixed per-run and per-dispatch overhead stops dominating context on projects with large boards.

Measured on the Kura runs: pm_board 13KB, pm_batch_get 16KB, pm_list_sprints 6.6KB, pm_context 7KB, memory files read with cat at 15KB and 7KB, worker prompts averaging 6.2KB (the inline 2000-char project context excerpt is most of it) and worker reports averaging 5.6KB. The pre-dispatch git status snapshot also scales with the dirty tree (Kura: 1050 entries, 55KB).

Changes: (1) pm_board, pm_batch_get and pm_list_sprints accept a brief/fields projection and the skill uses it in Phase 1 and 2; (2) the worker prompt drops the inline context excerpt and tells the worker to call pm_context itself, keeping only ids, criteria, DoD and the rules; (3) the worker prompt caps the report at about 1500 characters with a fixed shape; (4) the skill forbids reading memory or transcript files during a run; (5) Phase 1 warns when git status --short exceeds a threshold (say 200 entries) and suggests committing or cleaning before the run, since the snapshot and diff steps walk that list every dispatch.