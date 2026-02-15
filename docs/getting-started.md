# Getting Started

## Single-Repo Walkthrough

### 1. Initialize

```bash
cd your-project
projectman init --name "My App" --prefix APP
```

This creates `.project/` with config, story/task directories, and documentation templates.

### 2. Install Claude Code Integration

```bash
projectman setup-claude
```

Restart Claude Code to pick up the new MCP server and skills.

### 3. Create Your First Story

Use `/pm` in Claude Code:

```
/pm create story "User Authentication" "As a user, I want to log in so that I can access my account"
```

This creates a story with an ID like `US-APP-1`.

### 4. Create an Epic

Group related stories under a strategic initiative:

```
/pm create epic "Authentication System"
```

This creates an epic with an ID like `EPIC-APP-1`.

### 5. Scope the Story

```
/pm scope US-APP-1
```

Claude will propose a task breakdown. Approve to create tasks. You can also link stories to epics during scoping or via `/pm` commands.

### 6. Estimate Tasks

Claude uses fibonacci points (1, 2, 3, 5, 8, 13) calibrated for AI-assisted development speed.

### 7. See Available Work

```
/pm board
```

The task board shows tasks that are ready to work on, with dependencies resolved. You can also use the `pm_board` MCP tool directly.

### 8. Execute Work

```
/pm-do US-APP-1-1
```

Claude reads the task, implements it, and marks it done.

### 9. Check Status

```
/pm-status
```

See your project dashboard with completion stats. You can also use `/pm board` to see remaining available work at a glance.
