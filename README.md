# ProjectMan

Git-native project management for Claude Code. Manage User Stories, Tasks, Estimation, and Burndown — all stored as markdown files in your repo.

## Why?

Managing a growing number of projects with Claude Code leads to documentation drift, scattered TODO lists, and no structured way to plan work. ProjectMan solves this with:

- **Git-native storage** — stories, tasks, and epics are markdown files with YAML frontmatter
- **MCP integration** — Claude Code queries your project via MCP tools
- **Web dashboard** — visual kanban board, burndown charts, and project overview in your browser
- **Minimal tokens** — status summaries keep context window usage low
- **Hub mode** — manage multiple repos from one place via git submodules
- **Task board** — see what's ready to work on and grab tasks in one step

## Quick Start

```bash
# 1. Install pipx if you don't have it
sudo apt install pipx    # Debian/Ubuntu
brew install pipx        # macOS
pipx ensurepath          # Add to PATH (restart your shell after this)

# 2. Install from GitHub
pipx install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# 3. Initialize your project
cd your-repo
projectman init --name "My Project" --prefix MP

# 4. Install Claude Code integration
projectman setup-claude

# 5. Restart Claude Code, then:
#    /pm init            — describe your project (wizard)
#    /pm create epic     — define strategic initiatives
#    /pm create story    — add user stories
#    /pm scope US-MP-1   — decompose into tasks
#    /pm-do US-MP-1-1    — grab and execute a task
#    /pm web start       — launch the web dashboard
```

## Features

- **Stories & Tasks** — structured work items with frontmatter metadata
- **Epics** — strategic initiatives that group related stories
- **Web Dashboard** — visual kanban board, epic/story/task detail views, drag-drop status updates, search, and burndown charts
- **Task Board & Grab** — `pm_board` shows ready tasks, `pm_grab` claims them with readiness validation
- **Hub Context Docs** — VISION.md, ARCHITECTURE.md, DECISIONS.md for system-level context
- **Fibonacci Estimation** — calibrated point system (1, 2, 3, 5, 8, 13)
- **Sprint Planning** — guided workflow via `/pm-plan`
- **Drift Detection** — `pm_audit` catches inconsistencies
- **Semantic Search** — find items by meaning (optional, requires sentence-transformers)
- **Hub Mode** — multi-repo management via git submodules
- **Burndown Tracking** — points completed vs remaining

## Architecture

```
User → Claude Code Skills (/pm, /pm-status, /pm-plan, /pm-do)
         → PM Agent (.claude/agents/pm.md)
           → MCP Server (projectman serve, stdio)
             → Store (.project/ markdown files, hub-managed per project)
             → Embeddings (SQLite + sentence-transformers)
             → Web Dashboard (FastAPI + HTMX, launched via pm_web_start)
```

## Install Options

```bash
# Install pipx first if you don't have it
sudo apt install pipx    # Debian/Ubuntu
brew install pipx        # macOS
pipx ensurepath          # Add to PATH (restart your shell after this)

# Recommended: install everything (MCP + web dashboard + semantic search)
pipx install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or just MCP + web dashboard (no semantic search)
pipx install "projectman[mcp,web] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or with pip inside a venv
pip install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

Extras: `[mcp]` for Claude Code integration, `[web]` for the web dashboard, `[embeddings]` for semantic search, `[all]` for everything.

## Documentation

- [Installation](docs/installation.md)
- [Getting Started](docs/getting-started.md)
- [User Guide](docs/user-guide/stories.md)
- [Hub Mode](docs/hub-mode/setup.md)
- [Reference](docs/reference/cli.md)

## License

MIT
