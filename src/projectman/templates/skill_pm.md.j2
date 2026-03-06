---
name: pm
description: General project management entry point — smart router for all PM operations
user_invocable: true
---

# /pm — Project Management

Smart router for all ProjectMan operations. Users only need to remember `/pm`.

## Routing

Parse the user's intent and route to the appropriate action:

### No args → Smart status
Call `pm_status`, then `pm_active`. Based on project state, suggest the most useful next action:
- If undecomposed stories exist → "Consider running `/pm scope <id>`"
- If tasks are available on the board → "Run `/pm board` to see available work"
- If audit hasn't run recently → "Run `/pm audit` to check for drift"
- If no stories exist → "Create your first story with `/pm create story`"

### Status & Queries
- `status` → `pm_status` + `pm_active` dashboard
- `get <id>` → `pm_get(id)` — works for epics, stories, and tasks
- `search <query>` → `pm_search(query)`
- `board` → `pm_board` — show task board with available/in-progress/blocked work
- `context [project]` → `pm_context(project)` — full hub + project context for starting work
- `burndown` → `pm_burndown`

### Create & Update
- `create epic "<title>" "<description>"` → `pm_create_epic`
- `create story "<title>" "<description>"` → `pm_create_story` (optionally with `epic <epic-id>`)
- `create task <story-id> "<title>" "<description>"` → `pm_create_task`
- `update <id> <field>=<value>` → `pm_update`
- `archive <id>` → `pm_archive`

### Workflows (absorbed from former standalone skills)
- `scope <story-id>` → Call `pm_scope(id)`, propose task breakdown, create approved tasks, estimate each
- `autoscope [full|incremental]` → Call `pm_auto_scope(mode)`, bulk-create epics/stories/tasks. Redirect to `/pm-autoscope`
- `audit` → Call `pm_audit`, review DRIFT.md findings, suggest and execute approved fixes
- `init [project]` → Set up project documentation (wizard mode for new, import mode for existing)
- `fix` → Call `pm_malformed`, fix quarantined files one at a time via `pm_fix_malformed`
- `grab <task-id> [assignee]` → Call `pm_grab(task_id, assignee)` to claim a task with readiness validation. After a successful grab, detect the execution context:
  - **Web UI** (`CLAUDE_WEB_PORT` env var is set): The PostToolUse activity hook auto-spawns a focused task session — tell the user: "Task grabbed — a focused task session is starting. Check the UI for the new task tab."
  - **CLI-only** (no `CLAUDE_WEB_PORT`): Fall back to suggesting `/pm-do <id>`
  - If auto-spawn fails for any reason, fall back to the `/pm-do` suggestion

### Git Operations
- `commit [scope] [--message "..."]` → `pm_commit(scope, message)` — commit .project/ changes
- `push [scope]` → `pm_push(scope)` — push committed changes
- Scope: `hub` (default for push), `project:<name>`, or `all` (default for commit)
- `commit all` → `pm_commit` with scope=all (commits all .project/ changes)
- `commit hub` → `pm_commit` with scope=hub (hub-level only, excludes subprojects)
- `commit api` or `commit project:api` → `pm_commit` with scope=project:api
- `push` → `pm_push` with scope=hub
- `push all` → `pm_push` with scope=all (coordinated push)
- `push api` → `pm_push` with scope=project:api

### Hub Operations
- `repair` → `pm_repair` — scan, discover, init, rebuild
- `sync` → pull latest across all hub submodules
- `validate` or `check branches` → `pm_validate_branches` — verify submodule branch alignment
- `git status` / `git-status` → `pm_git_status` — show git state across all submodules (branch, dirty, ahead/behind, PRs)
- `docs [vision|architecture|decisions|project|infrastructure|security]` → `pm_docs`

### Natural Language
Also accept natural language and route intelligently:
- "what should I work on?" → `pm_board` → suggest top available task
- "plan the sprint" → redirect to `/pm-plan`
- "how are we doing?" → `pm_status` + `pm_burndown`
- "scope this story" → ask which story, then `pm_scope`
- "scope everything" / "autoscope" / "bulk scope" → redirect to `/pm-autoscope`
- "what needs attention?" / "git status" / "check repos" → `pm_git_status` — after displaying, suggest next action based on issues:
  - Misaligned branch → "Run `projectman create-branch` to fix"
  - Behind remote → "Run `projectman sync` to pull latest"
  - Open PRs → "Check PRs with `gh pr view`"

## Post-Action Chaining

After every action, suggest the logical next step:
- After creating a story → "Scope it with `/pm scope <id>`?"
- After scoping → "Estimate with `/pm update <id> points=N`?"
- After grabbing a task → detect execution context:
  - If `CLAUDE_WEB_PORT` is set: "Task grabbed — a focused task session is starting. Check the UI for the new task tab."
  - If no `CLAUDE_WEB_PORT`: "Start implementing with `/pm-do <id>`. Complete the task, mark it done, then end the session." (For autonomous/spawned agents, use `/pm-do <id> --complete` which auto-closes and terminates.)
  - If auto-spawn fails, fall back to the `/pm-do` suggestion
- After completing a task → "Check the board for more work: `/pm board`"
- After git status → Suggest next action based on issues found:
  - Misaligned branch → "Run `projectman create-branch` to fix"
  - Behind remote → "Run `projectman sync` to pull latest"
  - Open PRs → "Check PRs with `gh pr view`"
  - All clean → "All repos clean — ready for coordinated operations"

## ID Conventions

- **Epics**: `EPIC-PREFIX-N` (e.g. `EPIC-CEO-1`)
- **User Stories**: `US-PREFIX-N` (e.g. `US-CEO-1`)
- **Tasks**: `US-PREFIX-N-N` (e.g. `US-CEO-1-1`)

## Hub Mode

When in hub mode, many tools accept an optional `project` parameter to target a specific subproject.
