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

### 4. Scope the Story

```
/pm-scope APP-1
```

Claude will propose a task breakdown. Approve to create tasks.

### 5. Estimate Tasks

Claude uses fibonacci points (1, 2, 3, 5, 8, 13) calibrated for AI-assisted development speed.

### 6. Execute Work

```
/pm-do APP-1-1
```

Claude reads the task, implements it, and marks it done.

### 7. Check Status

```
/pm-status
```

See your project dashboard with completion stats.
