# Daily Workflow

## Morning Check-in

1. `/pm-status` — see project dashboard with epic/story/task counts
2. `/pm board` — see the task board with available, in-progress, and blocked tasks
3. `/pm web start` — optionally launch the web dashboard for a visual overview
4. `/pm commit` — commit any `.project/` changes left uncommitted from the previous session
5. Pick a task from the board or continue in-progress work

## Grabbing Work

```
/pm-do US-APP-1-1
```

The `/pm-do` command auto-grabs the task if it's available:
- Validates readiness (has estimate, description, parent story is active)
- Claims the task and sets it to in-progress
- Loads parent story context and sibling tasks
- If readiness fails, shows what needs fixing first

**Tip:** In a Web UI environment, `/pm grab <task-id>` auto-spawns a focused task session — no need to manually run `/pm-do`.

## During Work

- Update task status as you progress
- Create new tasks if you discover additional work: `/pm create task US-APP-1 "New task title" "Description"`
- Note blockers: `/pm update US-APP-1-2 --status blocked`

If **auto-commit** is enabled, every create/update operation automatically commits the affected `.project/` files with a descriptive message (e.g. `pm: create US-PRJ-5`, `pm: update US-PRJ-3-1 status→done`). Otherwise, commit manually when you reach a checkpoint:

```
/pm commit                               # auto-generated message from changed files
/pm commit --message "scope sprint 4"    # custom message
```

## Committing & Pushing Changes

ProjectMan includes built-in git integration for committing and pushing `.project/` data.

### Manual Commit & Push

```
/pm commit              # commit all .project/ changes (auto-generated message)
/pm commit --message "your message"   # custom commit message
/pm push                # push committed changes to remote
```

In hub mode, you can scope commits and pushes:

```
/pm commit hub          # hub-level changes only
/pm commit project:api  # specific subproject
/pm commit all          # everything (default)
/pm push hub            # push hub repo
/pm push project:api    # push specific subproject
/pm push all            # coordinated push: subprojects first, then hub
```

### Coordinated Push (Hub Mode)

For multi-repo hubs, use coordinated push to safely push all dirty subprojects and the hub in the correct order:

```
/pm push all            # auto-discovers dirty projects, pushes in order
/pm push all --dry-run  # preview what would be pushed without executing
```

This runs preflight validation, pushes subprojects first, then pushes the hub with auto-rebase on conflict.

### Auto-Commit

Enable `auto_commit` in your project config to automatically commit `.project/` changes whenever stories or tasks are created or updated:

```yaml
# .project/config.yaml
auto_commit: true
```

When enabled, each create/update operation stages the affected files and commits them with a descriptive message. This keeps your PM data in sync with git without manual commit steps.

**When to use auto-commit:** Best for solo workflows or when you want every PM change tracked individually. For team workflows, manual commits give more control over grouping related changes.

## End of Day

- Mark completed tasks as done
- Update in-progress tasks with notes
- `/pm commit` to commit any uncommitted `.project/` changes
- `/pm push` to sync with remote (or `/pm push all` in hub mode)
- `/pm-status` for a final check — confirm nothing is left in-progress unexpectedly

## Quick Reference: Manual vs Automated Workflow

| Step | Manual (git only) | With ProjectMan |
|------|-------------------|-----------------|
| Check project state | `git status` + read files | `/pm-status` or `/pm board` |
| Claim a task | Edit YAML by hand | `/pm grab US-X-Y` or `/pm-do US-X-Y` |
| Track progress | Update files manually | `/pm update US-X-Y --status in-progress` |
| Commit PM data | `git add .project/ && git commit` | `/pm commit` (auto-generated message) |
| Commit on every change | N/A | `auto_commit: true` in config |
| Push single repo | `git push origin branch` | `/pm push` |
| Push multi-repo hub | Push each repo manually in order | `/pm push all` (coordinated) |
| Preview push | N/A | `/pm push all --dry-run` |
| End-of-day sync | `git add . && git commit && git push` | `/pm commit` then `/pm push` |

## Web Dashboard

Start the visual dashboard at any time with `/pm web start` or `projectman web`. It provides:

- Clickable project overview with stat cards
- Kanban board with drag-drop task status updates
- Detailed epic, story, and task views
- Search across all items
- Burndown charts and audit findings

Stop it with `/pm web stop` when you're done.

## Weekly

- `/pm audit` to catch drift across all 13 audit checks
- `/pm-plan` for next sprint if needed
- Review epics for strategic alignment
