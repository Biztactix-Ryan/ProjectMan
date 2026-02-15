# Skills Reference

ProjectMan installs 5 Claude Code skills (slash commands) via `projectman setup-claude`. These provide the primary interface for interacting with ProjectMan from Claude Code.

## /pm

General entry point for project management. Routes to the appropriate MCP tools based on your request, including scope, audit, fix, and other subcommands.

```
/pm                          # Interactive — Claude asks what you need
/pm create story "Title"     # Route to story creation
/pm show US-PRJ-1            # Route to pm_get
/pm scope US-PRJ-1           # Decompose story into tasks
/pm audit                    # Run drift detection
/pm fix                      # Fix malformed files
/pm web start                # Launch the web dashboard
/pm web stop                 # Stop the web server
```

## /pm-status

Quick project dashboard. Shows story/task counts, points, completion percentage, and highlights blockers.

```
/pm-status
```

**What it does:**
1. Calls `pm_status` to get the compact index
2. Calls `pm_active` to show in-progress work
3. Highlights blockers or items needing attention
4. Suggests `/pm audit` if drift is detected

## /pm-plan

Guided sprint planning workflow. Walks through the full planning process.

```
/pm-plan
```

**Workflow:**
1. `pm_status` — current state
2. `pm_audit` — check for drift
3. `pm_active` — what's in-flight
4. `pm_burndown` — velocity trend
5. Review and prioritize backlog
6. Scope unscoped stories (`pm_scope`)
7. Estimate unestimated stories (`pm_estimate`)
8. Assign stories to sprint
9. Sprint summary with point target (20-30 for solo dev with AI)

## /pm-do

Pick up and execute a specific task. This is the "do the work" command.

```
/pm-do US-PRJ-1-1
```

**Workflow (3 phases):**

1. **Claim & Context** — Auto-grabs the task via `pm_grab` with readiness validation. Loads task context including parent story, related files, and definition of done.
2. **Execute** — Implements the work described in the task. Follows implementation steps and verifies definition-of-done items as they are completed.
3. **Complete** — Reviews task status, detects sibling task completion (whether all tasks under the parent story are now done), and updates status via `pm_update`.

**Note:** This skill has `disable-model-invocation: true` — it only runs when you explicitly invoke it with `/pm-do`, never automatically. This is because it performs real code changes.

## /pm-autoscope

Automated bulk scoping. Discovers what needs scoping and walks through creation.

```
/pm-autoscope
/pm-autoscope full
/pm-autoscope incremental
```

**Two modes** (auto-detected):

- **Full scan** (no epics/stories exist): Reads codebase signals (docs, build files, source tree), proposes epics, stories, and tasks for user approval, then creates them all.
- **Incremental** (stories exist without tasks): Fetches undecomposed stories in paginated batches (default 5), scopes each with `pm_scope`, proposes 2-6 tasks, gets user approval, and creates them in bulk via `pm_create_tasks`. Loops through batches until done.

Also accessible via `/pm autoscope` or natural language like "scope everything".

## Web Dashboard via /pm

The `/pm` skill routes web-related commands to the MCP web tools:

```
/pm web                  # Start the web dashboard (default 127.0.0.1:8000)
/pm web start 0.0.0.0    # Bind to all interfaces
/pm web stop             # Stop the server
/pm web status           # Check if it's running
```

If a port is already in use, Claude automatically retries with the next available port. The web dashboard provides:

- Project overview with clickable stat cards
- Kanban board with drag-drop status updates
- Epic, story, and task detail views
- Search across all items
- Burndown and audit views
- Documentation editor

Requires the `web` extra: `pip install projectman[web]` or `pipx install projectman[all]`.

## Customization

All skills are installed as markdown files in `.claude/skills/<name>/SKILL.md`. You can edit them to:

- Add project-specific conventions
- Modify workflow steps
- Change tool usage patterns
- Add additional context or rules

Skills are version-controlled with your project, so customizations are shared with your team.
