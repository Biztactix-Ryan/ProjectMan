---
name: pm-plan
description: Sprint planning workflow
user_invocable: true
---

# /pm-plan — Sprint Planning

Run the full sprint planning workflow:

1. Call `pm_status` for current state
2. Call `pm_audit` to check for drift issues (including dependency cycles)
3. Call `pm_active` for in-flight work
4. Call `pm_burndown` for velocity data
5. Check `pm_list_sprints(status="active")` — warn if an active sprint already exists
6. Present findings and guide prioritization:
   - Show audit issues that need resolution
   - List backlog stories by priority
   - Recommend stories to scope next
7. **Dependency analysis**: Review story dependencies to determine sprint order
   - Stories with unmet dependencies should not enter sprint until blockers are planned
   - Visualize the dependency chain: "US-PRJ-3 depends on US-PRJ-2 which depends on US-PRJ-1"
8. **Implementation task validation**: For candidate stories, check audit findings for `missing-implementation-tasks`. For flagged stories, call `pm_auto_scope` to generate implementation task proposals. Present and create on approval. Stories still lacking implementation tasks should not enter the sprint.
9. For each selected story:
   - Call `pm_scope(story_id)` to get decomposition context
   - Propose task breakdown with appropriate `depends_on` (intra-story and cross-story)
   - Call `pm_estimate(id)` for each task
10. Create tasks on user approval
11. **Persist sprint**: Call `pm_create_sprint` with name, goal, dates, and planned story IDs
12. Summarize the sprint plan with sprint ID

## Cross-Story Dependency Planning

When planning sprints, consider the dependency graph:

- **Order stories by dependencies**: Stories that others depend on should be prioritized
- **Avoid orphan dependencies**: Don't plan a story without its dependency stories
- **Visualize critical path**: Show which stories block the most downstream work
- **Flag cross-story task deps**: Highlight tasks that depend on other stories' tasks

Example output:
```
Sprint dependency order:
1. US-PRJ-1 (no deps) — API foundation
2. US-PRJ-2 (depends on US-PRJ-1) — Data layer
3. US-PRJ-3 (depends on US-PRJ-1-3, US-PRJ-2) — Frontend integration
```
