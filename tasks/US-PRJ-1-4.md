---
assignee: claude
created: '2026-02-17'
id: US-PRJ-1-4
points: 1
status: done
story_id: US-PRJ-1
title: Map current end-to-end hub git workflow steps
updated: '2026-02-17'
---

Trace and document the exact manual steps a developer currently takes from PM operation to remote push:

1. Review hub/registry.py sync(), add_project(), set_branch() to understand existing git automation
2. Review store.py mutations to confirm no git operations happen after PM writes
3. Document the full workflow: PM operation → file written → manual git add → commit → push (per subproject) → update hub refs → commit hub → push hub
4. Count the number of manual steps for common scenarios (update 1 project, update 5 projects simultaneously)

Output: Section in DECISIONS.md or a new HUB-WORKFLOW-AUDIT.md with the step-by-step current workflow.