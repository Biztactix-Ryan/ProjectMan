---
assignee: null
created: '2026-02-17'
id: US-PRJ-9-10
points: 2
status: todo
story_id: US-PRJ-9
title: Write tests for conventions config and validation
updated: '2026-02-17'
---

Test the full conventions system.

1. **Config inheritance**: Hub conventions loaded from config.yaml, subproject inherits deploy_branch_default, subproject overrides deploy_branch locally
2. **Branch naming validation**: `pm/US-PRJ-1-1/fix-auth` passes, `feature/my-thing` fails, deploy branch exempt for sync
3. **Commit message validation**: `hub: update api to a1b2c3d` passes, `pm: create US-PRJ-5` passes, arbitrary message gets warning not error
4. **Push protection**: validate_conventions(op='push') blocks when on deploy branch with changes, allows on feature branch
5. **Clear error messages**: Each violation includes the expected format and a suggested fix command
6. **No conventions config**: Graceful fallback to defaults when hub has no conventions block (backwards compatible)

Files: tests/test_hub.py or tests/test_conventions.py