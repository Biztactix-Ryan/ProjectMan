---
assignee: claude
created: '2026-02-17'
id: US-PRJ-3-8
points: 2
status: done
story_id: US-PRJ-3
title: Write tests for pm_commit and pm_push
updated: '2026-02-19'
---

Test both tools across scopes and edge cases.

1. **Hub commit**: modify .project/stories/US-PRJ-1.md → pm_commit(scope='hub') → only that file committed, auto-generated message
2. **Subproject commit**: modify .project/projects/api/stories/ → pm_commit(scope='project:api') → only api PM files committed
3. **All commit**: changes in hub + 2 subprojects → pm_commit(scope='all') → all committed in one commit
4. **Custom message**: pm_commit(message='manual update') → uses provided message
5. **Nothing to commit**: no PM changes → returns early, no empty commit
6. **Non-.project files ignored**: changes to src/ files exist → pm_commit never touches them
7. **Push with validation**: pm_push on misaligned branch → blocked
8. **Push hub**: pm_push(scope='hub') → pushes to main
9. **Push delegates**: pm_push(scope='all') → calls coordinated_push

Files: tests/test_hub.py or tests/test_pm_git_tools.py