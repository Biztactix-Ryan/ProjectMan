# Daily Workflow

## Morning Check-in

1. `/pm-status` — see project dashboard with epic/story/task counts
2. `/pm board` — see the task board with available, in-progress, and blocked tasks
3. Pick a task from the board or continue in-progress work

## Grabbing Work

```
/pm-do US-APP-1-1
```

The `/pm-do` command auto-grabs the task if it's available:
- Validates readiness (has estimate, description, parent story is active)
- Claims the task and sets it to in-progress
- Loads parent story context and sibling tasks
- If readiness fails, shows what needs fixing first

## During Work

- Update task status as you progress
- Create new tasks if you discover additional work: `/pm create task US-APP-1 "New task title" "Description"`
- Note blockers: `/pm update US-APP-1-2 --status blocked`

## End of Day

- Mark completed tasks as done
- Update in-progress tasks with notes
- `/pm-status` for a final check

## Weekly

- `/pm audit` to catch drift across all 13 audit checks
- `/pm-plan` for next sprint if needed
- Review epics for strategic alignment
