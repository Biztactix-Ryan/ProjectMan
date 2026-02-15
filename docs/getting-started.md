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

### 3. Describe Your Project

Run the getting-started wizard to fill in your project documentation:

```
/pm init
```

Claude walks you through describing your project's architecture, infrastructure, and security posture. This fills in PROJECT.md, INFRASTRUCTURE.md, and SECURITY.md — the context that feeds into story creation, scoping, and audits.

You can also read or update individual docs at any time:

```
/pm docs project           # read PROJECT.md
/pm docs infrastructure    # read INFRASTRUCTURE.md
/pm docs security          # read SECURITY.md
```

### 4. Create an Epic

Start with a strategic initiative that groups related work:

```
/pm create epic "Authentication System"
```

This creates an epic with an ID like `EPIC-APP-1`.

### 5. Create Your First Story

```
/pm create story "User Authentication" "As a user, I want to log in so that I can access my account"
```

This creates a story with an ID like `US-APP-1`. Link it to your epic during creation or afterwards.

### 6. Scope the Story

```
/pm scope US-APP-1
```

Claude reads your project docs for context, proposes a task breakdown, and creates approved tasks with implementation details and definitions of done.

### 7. Estimate Tasks

Claude uses fibonacci points (1, 2, 3, 5, 8, 13) calibrated for AI-assisted development speed.

### 8. See Available Work

```
/pm board
```

The task board shows tasks that pass readiness checks — estimated, well-described, and with an active parent story.

### 9. Execute Work

```
/pm-do US-APP-1-1
```

Claude grabs the task (validating readiness), loads the parent story context, implements the work, and marks it done.

### 10. Check Status

```
/pm-status
```

See your project dashboard with completion stats. Use `/pm board` to see remaining available work at a glance.

### 11. Launch the Web Dashboard

```
/pm web start
```

Opens a visual dashboard in your browser with a kanban board, epic/story/task detail views, drag-drop status updates, search, and burndown charts. The web server runs in the background — stop it with `/pm web stop`.

You can also launch it from the CLI:

```bash
projectman web                         # http://127.0.0.1:8000
projectman web --host 0.0.0.0 --port 9000  # bind to all interfaces on port 9000
```
