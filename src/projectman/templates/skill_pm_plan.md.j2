---
name: pm-plan
description: Sprint planning workflow
user_invocable: true
---

# /pm-plan — Sprint Planning

Run the full sprint planning workflow:

1. Call `pm_status` for current state
2. Call `pm_audit` to check for drift issues
3. Call `pm_active` for in-flight work
4. Call `pm_burndown` for velocity data
5. Check `pm_list_sprints(status="active")` — warn if an active sprint already exists
6. Present findings and guide prioritization:
   - Show audit issues that need resolution
   - List backlog stories by priority
   - Recommend stories to scope next
7. **Implementation task validation**: For candidate stories, check audit findings for `missing-implementation-tasks`. For flagged stories, call `pm_auto_scope` to generate implementation task proposals. Present and create on approval. Stories still lacking implementation tasks should not enter the sprint.
8. For each selected story:
   - Call `pm_scope(story_id)` to get decomposition context
   - Propose task breakdown
   - Call `pm_estimate(id)` for each task
9. Create tasks on user approval
10. **Persist sprint**: Call `pm_create_sprint` with name, goal, dates, and planned story IDs
11. Summarize the sprint plan with sprint ID
