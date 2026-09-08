---
acceptance_criteria:
- docs/hub-mode is deleted and no doc or README or skill template describes hub mode
  or a prefix argument or migrate-hub
- DECISIONS.md carries ADR-004 superseding ADR-003 with the usage evidence and the
  date
- A docs test asserts no hub mention outside CHANGELOG.md and DECISIONS.md and history-marked
  reference docs and it passes
created: '2026-09-08'
depends_on:
- US-PM-46
epic_id: EPIC-PM-6
id: US-PM-47
points: 3
priority: must
status: done
tags:
- subtraction
- hub
- docs
title: Docs and templates and the decision record say hub mode is gone
updated: '2026-09-08'
---

As someone reading the docs or the generated pm agent and skills, I want no page to describe hub mode, the prefix argument, migrate-hub or projects/{name}/.project so that a new user is never led into a mode the package does not have, and the decision is on record.

State on 2026-09-08: docs/hub-mode holds cron.md, epics.md, git-workflow.md, setup.md, troubleshooting.md. Hub is mentioned in docs/reference/agent.md, cli.md, mcp-tools.md, file-formats.md, skills.md, error-paths-inventory.md, readiness-warnings-determination.md, docs/user-guide/auditing.md, daily-workflow.md and README.md. Templates: src/projectman/templates/agent_pm.md.j2 (9 hub mentions), skill_pm.md.j2 (11), config.yaml.j2 (2; the keys go in US-PM-46), architecture_hub.md.j2 (deleted in US-PM-46). DECISIONS.md carries ADR-003 (hub is a read-only rollup, Accepted) which ADR-004 must supersede, citing the evidence: 9 uses in 484 sessions, 71 of 97 error sites with zero traffic mostly hub and web, and no user of the redesign. The two historical reference docs (error-paths-inventory, readiness-warnings-determination) may keep hub mentions as history if marked as such; judge per page. tests/test_docs_after_subtraction.py is the existing doc-sweep test to extend; the sweep must exempt CHANGELOG.md and DECISIONS.md, which record history. Refresh the generated skills after editing templates is the user's step (projectman refresh-skills --keep-local), not the worker's.

Depends on US-PM-46 so the docs describe the code that exists.