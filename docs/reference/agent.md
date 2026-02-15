# PM Agent Reference

The PM agent (`.claude/agents/pm.md`) is a Claude Code agent specialized in project management. It manages epics, stories, tasks, estimation, and sprint planning using ProjectMan's MCP tools, including the task board and hub context.

## When It Activates

The agent is invoked when Claude Code detects project management context in your conversation — discussions about epics, stories, tasks, sprints, estimation, or project status.

## Token Discipline

The agent follows strict rules to minimize context window usage:

1. **Fetch context** via `pm_context` — get combined hub + project context (hub vision/architecture + project docs + active epics/stories)
2. **Always start with `pm_status`** — never bulk-read project data
3. **One story/task at a time** via `pm_get` — never load everything
4. **Use `pm_search` for discovery** — don't scan files directly
5. **Read PROJECT.md for architecture context** — only when scoping or estimating

## Story Point Calibration

The agent uses fibonacci points calibrated for Claude-assisted development speed:

| Points | Effort | Example |
|--------|--------|---------|
| 1 | ~15 min | Config change, copy fix, simple bug |
| 2 | ~30 min | Single function, straightforward feature |
| 3 | ~1-2 hours | Multi-file feature with tests |
| 5 | ~half day | New module, cross-cutting change |
| 8 | ~1 day | Major feature, architectural work |
| 13 | ~2+ days | Epic-scale — should be decomposed |

## Core Workflows

### Status Check
```
pm_status → present dashboard → highlight blockers
```

### Story Creation
```
pm_create_story(epic_id) → pm_scope → pm_estimate → pm_create_tasks (batch)
```

### Epic Management
```
pm_create_epic → pm_create_story(epic_id) → pm_scope → pm_create_tasks (batch)
```

### Task Board
```
pm_board → pm_grab → implement → pm_update (done)
```

### Sprint Planning
```
pm_status → pm_audit → pm_active → pm_burndown → prioritize → scope → estimate → assign
```

### Task Execution
```
pm_grab (validates readiness) → implement → pm_update (review or done)
```

### Drift Detection
```
pm_audit → review findings → suggest fixes → execute approved fixes
```

## Customization

The agent file is installed at `.claude/agents/pm.md`. You can edit it to:

- **Adjust point calibration** for your team's velocity
- **Add project-specific rules** (naming conventions, testing requirements)
- **Modify workflows** (add review steps, approval gates)
- **Change the model** — set `model: opus` for complex planning, `model: haiku` for quick status checks
- **Restrict tools** — limit which MCP tools the agent can use

## Agent Frontmatter

```yaml
---
name: pm
description: Project management agent — manages epics, stories, tasks, estimation, and sprint planning
mcpServers:
  - projectman
---
```

The `mcpServers` field connects the agent to the ProjectMan MCP server, giving it access to all `pm_*` tools.
