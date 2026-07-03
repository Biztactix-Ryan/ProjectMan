---
name: pm
description: Project management entry point — status, boards, creating/updating epics/stories/tasks, sprints, dependencies, git ops. Use for any ProjectMan request that doesn't match a more specific pm-* skill ("what should I work on", "create a story", "how are we doing", "commit project state").
---

# /pm — Project Management

Smart router for all ProjectMan operations. Users only need to remember `/pm`. Tool parameters are documented on the MCP tools themselves — this skill covers routing and judgment, not signatures.

## Routing

### No args → Smart status
Call `pm_status`, then `pm_active`, then `pm_list_sprints(status="active")`. Suggest the most useful next action:
- Active sprint with ready tasks → "Run the sprint: `/pm-orchestrate`, or grab a task: `/pm-do <id>`"
- Active sprint past its end date → "Sprint ended — close it out and plan the next: `/pm-plan`"
- No active sprint but scoped backlog → "Plan a sprint: `/pm-plan`"
- Undecomposed stories → "Scope them: `/pm scope <id>` or `/pm-autoscope`"
- No stories at all → "Create your first story with `/pm create story`"
- Audit not run recently → "Check for drift: `/pm audit`"

### Status & Queries
- `status` / "how are we doing?" → run the `/pm-status` skill (full dashboard: sprint progress, blockers, recent failures) — don't rebuild it here
- `get <id>` → `pm_get(id)` — epics, stories, tasks
- `search <query>` → `pm_search(query)`
- `board` → `pm_board` — available/in-progress/blocked work
- `context [project]` → `pm_context(project)` — full hub + project context for starting work
- `burndown` → `pm_burndown`
- `deps [id]` → show what an item depends on and what depends on it (from `pm_get` `depends_on` fields; `pm_audit` for graph-wide checks)
- `history <id>` / `runs <id>` → `pm_run_log(id)` — attempt history: which agents worked it, outcomes, failures

### Sprints
- `sprints` → `pm_list_sprints` — all sprints with status
- `sprint` → `pm_list_sprints(status="active")` + progress of the active sprint
- `sprint <id>` → `pm_get_sprint(id)`
- `sprint complete [id]` → `pm_update_sprint(id, status="completed")` — show completed vs. planned points first
- "plan a sprint" → redirect to `/pm-plan`
- "run the sprint" → redirect to `/pm-orchestrate`

### Create & Update
- `create epic "<title>" "<description>"` → `pm_create_epic`
- `create story "<title>" "<description>"` → `pm_create_story` (optionally `epic <epic-id>`, `depends_on <ids>`)
- `create task <story-id> "<title>" "<description>"` → `pm_create_task` (optionally `depends_on <ids>`)
- `update <id> <field>=<value>` → `pm_update`
- `archive <id>` → `pm_archive`

Note: sprints are updated via `pm_update_sprint` (statuses: planning/active/completed/cancelled), not `pm_update`.

### Dependencies
Stories and tasks support cross-item dependencies via `depends_on` — task→task (any story), story→story, task→story, story→task. Cycles are rejected at creation/update; `pm_audit` checks for orphans and cycles project-wide; `pm_grab` requires all dependencies done.

Examples:
- `create story "Frontend" "..." depends_on US-PRJ-1`
- `create task US-PRJ-2 "Integrate API" "..." depends_on US-PRJ-1-3`
- `update US-PRJ-2 depends_on=US-PRJ-1,US-PRJ-1-5`

### Workflows
- `scope <story-id>` → `pm_scope(id)`, propose task breakdown, create approved tasks, estimate each
- `autoscope` → redirect to `/pm-autoscope`
- `audit` → `pm_audit`, review findings, suggest and execute approved fixes
- `init [project]` → set up project documentation (wizard for new, import for existing)
- `fix` → `pm_malformed`, then fix quarantined files one at a time via `pm_fix_malformed`
- `grab <task-id> [assignee]` → `pm_grab(task_id, assignee)` — claim with readiness validation. On success, suggest `/pm-do <id>` to execute (spawned agents use `/pm-do <id> --complete`).
- `done <task-id> [note]` → `pm_done_next(task_id, outcome, note)` — complete a task, auto-close its story if finished, and claim the next ready task in one call. Prefer this over separate `pm_update` + `pm_grab` when working through tasks.

### Git Operations
- `commit [scope] [--message "..."]` → `pm_commit(scope, message)` — commit .project/ changes. Scope: `all` (default), `hub`, `project:<name>`
- `push [scope]` → `pm_push(scope)` — scope: `hub` (default), `all` (coordinated), `project:<name>`

### Hub Operations
- `repair` → `pm_repair` — scan, discover, init, rebuild
- `sync` → pull latest across all hub submodules
- `validate` / `check branches` → `pm_validate_branches`
- `git status` → `pm_git_status` — branch, dirty, ahead/behind, PRs across submodules
- `docs [vision|architecture|decisions|project|infrastructure|security]` → `pm_docs`

### Natural Language
Route intent, not keywords:
- "what should I work on?" → `pm_board` → suggest top available task
- "what's failing?" / "what went wrong?" → `pm_run_log` on recent items + `pm_activity`
- "what depends on X?" / "what blocks X?" → dependency queries via `pm_get`
- "what needs attention?" → `pm_git_status`, then suggest per issue:
  - Misaligned branch → "Fix with `projectman set-branch <project> <branch>`"
  - Behind remote → "Pull latest with `projectman sync`"
  - Open PRs → "Check with `gh pr view`"

## Post-Action Chaining

After every action, suggest the logical next step:
- Created a story → "Scope it: `/pm scope <id>`"
- Scoped a story → "Plan it into a sprint: `/pm-plan`"
- Grabbed a task → "Execute it: `/pm-do <id>`"
- Completed a task → `pm_done_next` already returns the next ready task — offer to continue with it
- Sprint fully planned → "Run it: `/pm-orchestrate`"
- All repos clean → "Ready for coordinated operations"

## ID Conventions

- **Epics**: `EPIC-PREFIX-N` · **Stories**: `US-PREFIX-N` · **Tasks**: `US-PREFIX-N-N`

## Hub Mode

In hub mode, most tools accept an optional `project` parameter to target a specific subproject.
