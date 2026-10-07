# ProjectMan

Git-native project management for Claude Code. Manage User Stories, Tasks, Estimation, and Burndown — all stored as markdown files in your repo.

## Why?

Managing a growing number of projects with Claude Code leads to documentation drift, scattered TODO lists, and no structured way to plan work. ProjectMan solves this with:

- **Git-native storage** — stories, tasks, and epics are markdown files with YAML frontmatter
- **MCP integration** — Claude Code queries your project via MCP tools
- **Web dashboard** — visual kanban board, burndown charts, and project overview in your browser
- **Minimal tokens** — status summaries keep context window usage low
- **Task board** — see what's ready to work on and grab tasks in one step

## Quick Start

The Claude Code plugin is the supported install. It brings the pm skills, the pm agent,
the projectman MCP server and a SessionStart status hook. It needs
[uv](https://docs.astral.sh/uv/getting-started/installation/) on `PATH` and a Claude Code
release with plugin support. No minimum version is recorded yet; the plugin was verified
on Claude Code 2.1.292.

```
# 1. In Claude Code, add the marketplace and install the plugin
/plugin marketplace add Biztactix-Ryan/ProjectMan
/plugin install projectman@projectman
/reload-plugins

# 2. Then:
#    /projectman:pm init           — describe your project (wizard)
#    /projectman:pm create story   — add user stories
#    /projectman:pm-do US-MP-1-1   — grab and execute a task
```

To create a store from a shell (`projectman init --name "My Project" --prefix MP`), or to
run the web dashboard outside Claude Code, also install the CLI with pipx (see
[Install Options](#install-options)). On a clone whose PM store is already on the
`projectman` branch, plain `projectman init` attaches that store instead of scaffolding
a new one.

**Already installed with `projectman setup-claude`?** Install the plugin as above, then
run `projectman migrate-to-plugin --dry-run` to preview and `projectman migrate-to-plugin`
to remove the old agent, skill copies and MCP entries, so the plugin takes over. Restart
Claude Code afterwards. `setup-claude` and `refresh-skills` are deprecated: they now only
print these steps.

Full steps and verification: [Install as a Claude Code plugin](docs/installation.md#install-as-a-claude-code-plugin).
Running the CLI from a checkout? Reinstall from your local path after every pull — [Upgrading](docs/installation.md#upgrading) covers how to spot a stale install and the `mcp<2` pin a stale environment breaks on.

## Features

- **Stories & Tasks** — structured work items with frontmatter metadata
- **Epics** — strategic initiatives that group related stories
- **Web Dashboard** — visual kanban board, epic/story/task detail views, drag-drop status updates, search, and burndown charts
- **Task Board & Grab** — `pm_board` shows ready tasks, `pm_grab` claims them with readiness validation
- **Context Docs** — VISION.md, ARCHITECTURE.md, DECISIONS.md for system-level context
- **Fibonacci Estimation** — calibrated point system (1, 2, 3, 5, 8, 13)
- **Sprint Planning** — guided workflow via `/pm-plan`
- **Drift Detection** — `pm_audit` catches inconsistencies
- **Semantic Search** — find items by meaning (optional, requires fastembed)
- **Tags** — free-form labels on stories, epics, and tasks; filterable in search, board, and active views
- **Task Dependencies** — `depends_on` links between sibling tasks with cycle detection and topological ordering
- **Activity Log** — append-only JSONL audit trail of every create, update, delete, and archive
- **Run Log** — per-item history of work attempts, outcomes, and notes, recorded via `pm_update` and read with `pm_run_log`
- **Sprint Tracking** — create sprints with goals, dates, and planned stories; live progress rollup via `pm_get_sprint`
- **Auto-Commit & Push** — `pm_commit` and `pm_push` commit and push the PM store on its own branch
- **Git Status Dashboard** — `pm_git_status` shows the store's branch, alignment, dirty state, and ahead/behind
- **Burndown Tracking** — points completed vs remaining

## Architecture

```
User → Claude Code Skills (/pm, /pm-status, /pm-plan, /pm-do, /pm-orchestrate, /pm-autoscope, /pm-cleanup)
         → PM Agent (projectman:pm, from the plugin)
           → MCP Server (projectman serve, stdio)
             → Store (.project/ markdown files)
             → Embeddings (SQLite + fastembed)
             → Activity Log (JSONL append-only audit trail)
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

## Upgrading

```bash
# Upgrade the package and refresh installed Claude skills in one step
projectman upgrade

# Just check the installed version and source
projectman upgrade --check
```

`projectman upgrade` upgrades the pipx CLI. The plugin updates on its own path: `/plugin marketplace update projectman`, `/plugin update projectman@projectman`, then `/reload-plugins` (see [Updating](docs/installation.md#updating)). If old `setup-claude` skill copies are still installed, `projectman upgrade` re-renders them for one more release and tells you to run `projectman migrate-to-plugin`.

## Documentation

- [Installation](docs/installation.md)
- [Getting Started](docs/getting-started.md)
- [User Guide](docs/user-guide/stories.md)
- [Reference](docs/reference/cli.md)
- [Orchestrator Design](docs/reference/orchestrate-design.md)

## License

MIT
