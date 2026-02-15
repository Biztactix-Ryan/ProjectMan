# Skills Reference

ProjectMan installs 6 Claude Code skills (slash commands) via `projectman setup-claude`.

## /pm

General entry point for project management. Routes to the appropriate MCP tools based on your request.

```
/pm                          # Interactive — Claude asks what you need
/pm create story "Title"     # Route to story creation
/pm show PRJ-1               # Route to pm_get
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
4. Suggests `/pm-audit` if drift is detected

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

## /pm-scope

Decompose a user story into concrete implementation tasks.

```
/pm-scope PRJ-1
```

**Workflow:**
1. Reads story via `pm_scope` to get context
2. Analyzes acceptance criteria and description
3. Proposes a task breakdown (each task 1-3 points)
4. Presents tasks for your approval
5. Creates approved tasks via `pm_create_task`
6. Estimates each task via `pm_estimate` + `pm_update`
7. Shows final breakdown with total points

## /pm-audit

Run drift detection and review findings.

```
/pm-audit
```

**Workflow:**
1. Calls `pm_audit` to generate the drift report
2. Presents findings organized by severity
3. For each finding, suggests a resolution:
   - Done stories with incomplete tasks → complete tasks or reopen story
   - Stale items → check relevance, update or archive
   - Missing descriptions → offer to flesh out with `/pm-scope`
   - Point mismatches → recalibrate with `pm_estimate`
4. Offers to execute suggested fixes

## /pm-do

Pick up and execute a specific task. This is the "do the work" command.

```
/pm-do PRJ-1-1
```

**Workflow:**
1. Reads the full task via `pm_get`
2. Sets task status to `in-progress` via `pm_update`
3. Reads implementation steps and definition of done
4. Implements the work described in the task
5. Verifies all definition-of-done items are met
6. Sets task status to `done` via `pm_update`
7. Reports what was accomplished

**Note:** This skill has `disable-model-invocation: true` — it only runs when you explicitly invoke it with `/pm-do`, never automatically. This is because it performs real code changes.

## Customization

All skills are installed as markdown files in `.claude/skills/<name>/SKILL.md`. You can edit them to:

- Add project-specific conventions
- Modify workflow steps
- Change tool usage patterns
- Add additional context or rules

Skills are version-controlled with your project, so customizations are shared with your team.
