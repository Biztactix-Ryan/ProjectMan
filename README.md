# ProjectMan

Git-native project management for Claude Code. Manage User Stories, Tasks, Estimation, and Burndown — all stored as markdown files in your repo.

## Why?

Managing a growing number of projects with Claude Code leads to documentation drift, scattered TODO lists, and no structured way to plan work. ProjectMan solves this with:

- **Git-native storage** — stories, tasks, and epics are markdown files with YAML frontmatter
- **MCP integration** — Claude Code queries your project via MCP tools
- **Minimal tokens** — status summaries keep context window usage low
- **Hub mode** — manage multiple repos from one place via git submodules
- **Task board** — see what's ready to work on and grab tasks in one step

## Quick Start

```bash
# 1. Install from GitHub (pipx recommended for CLI tools)
pipx install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# 2. Initialize your project
cd your-repo
projectman init --name "My Project" --prefix MP

# 3. Install Claude Code integration
projectman setup-claude

# 4. Restart Claude Code, then:
#    /pm init            — describe your project (wizard)
#    /pm create epic     — define strategic initiatives
#    /pm create story    — add user stories
#    /pm scope US-MP-1   — decompose into tasks
#    /pm-do US-MP-1-1    — grab and execute a task
```

## Features

- **Stories & Tasks** — structured work items with frontmatter metadata
- **Epics** — strategic initiatives that group related stories
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
             → Store (.project/ files in each repo)
             → Embeddings (SQLite + sentence-transformers)
```

## Install Options

```bash
# Recommended: pipx (auto-manages venv, puts projectman on PATH)
pipx install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or with pip inside a venv
pip install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

Extras: `[mcp]` for Claude Code integration, `[embeddings]` for semantic search, `[all]` for everything.

Don't have pipx? `sudo apt install pipx && pipx ensurepath`

## Documentation

- [Installation](docs/installation.md)
- [Getting Started](docs/getting-started.md)
- [User Guide](docs/user-guide/stories.md)
- [Hub Mode](docs/hub-mode/setup.md)
- [Reference](docs/reference/cli.md)

## License

MIT
