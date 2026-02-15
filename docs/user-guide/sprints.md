# Sprint Planning

## Workflow

1. Run `/pm-plan` to start the sprint planning workflow
2. Review project status and audit findings
3. Check epics for strategic alignment and priority
4. Prioritize backlog stories
5. Scope selected stories into tasks
6. Estimate each task
7. Review the task board (`/pm board`) to see what's ready

## Board-Driven Development

Rather than assigning tasks during planning, prefer a board-driven approach: developers grab tasks from the task board (`/pm board`) as they become available. Tasks that pass readiness checks appear on the board automatically. Use `/pm-do <task-id>` to claim and start work on a task.

## Velocity

Track velocity by comparing completed points per sprint. Use `pm_burndown` to see progress.

## Point Calibration

| Points | Effort | Example |
|--------|--------|---------|
| 1 | ~15 min | Fix a typo, add a config value |
| 2 | ~30 min | Add a simple endpoint, write a test |
| 3 | ~1 hour | Implement a feature with moderate complexity |
| 5 | ~half day | Multi-file feature with tests |
| 8 | ~full day | Significant feature or refactor |
| 13 | 2+ days | Consider decomposing into smaller stories |
