# ProjectMan

Git-native project management for Claude Code. Manage User Stories, Tasks, Epics, Estimation, and Burndown — all stored as markdown files with YAML frontmatter in your repo.

## Architecture

### Tech Stack

- **Language**: Python 3.10+
- **Build System**: Hatchling
- **MCP Framework**: FastMCP (stdio transport)
- **Web Framework**: FastAPI + HTMX (optional `[web]` extra)
- **Data Models**: Pydantic v2
- **Storage**: Markdown files with YAML frontmatter (via python-frontmatter)
- **Embeddings**: fastembed (optional `[embeddings]` extra)
- **CLI**: Click
- **Templating**: Jinja2

### Components

- **`server.py`** — MCP server exposing all PM tools (query, create, update, audit, hub, web)
- **`store.py`** — CRUD operations for stories, tasks, and epics via python-frontmatter
- **`models.py`** — Pydantic models defining Story, Task, Epic, Config, and their status enums
- **`cli.py`** — Click-based CLI (`projectman init`, `projectman serve`, `projectman setup-claude`)
- **`indexer.py`** — Builds YAML index with running totals (story/task/epic counts, points)
- **`audit.py`** — 12-check drift detection (orphans, missing refs, stale docs, etc.)
- **`scoper.py`** — Story decomposition guidance for breaking stories into tasks
- **`estimator.py`** — Fibonacci point calibration (1, 2, 3, 5, 8, 13)
- **`readiness.py`** — Task board readiness checks (blocked, available, in-progress)
- **`search.py`** — Keyword search with optional semantic search via embeddings
- **`embeddings.py`** — fastembed-based semantic search with SQLite cache
- **`config.py`** — Project configuration loading/saving
- **`hub/`** — Hub mode: git submodule registry, cross-project rollup, dashboards
- **`web/`** — FastAPI web dashboard: kanban board, burndown charts, HTMX templates
- **`templates/`** — 21 Jinja2 templates for generated markdown files and skills

### Data Flow

```
User → Claude Code Skills (/pm, /pm-status, /pm-plan, /pm-do)
       → PM Agent (.claude/agents/pm.md)
         → MCP Server (projectman serve, stdio transport)
           → Store (reads/writes .project/ markdown files)
           → Indexer (rebuilds index.yaml on mutations)
           → Embeddings (SQLite + fastembed, optional)
           → Web Dashboard (FastAPI + HTMX, optional)
```

All data lives in `.project/` as markdown files committed to git. The MCP server reads/writes these files and rebuilds the index after every mutation. Claude Code interacts via MCP tools; humans can also use the CLI or web dashboard.

## Key Decisions

- **Markdown + YAML frontmatter** — Human-readable, git-diffable, zero-dependency storage. No external database needed.
- **MCP over HTTP API** — stdio transport keeps it local-only with zero network config. Claude Code natively supports MCP.
- **Fibonacci estimation** — Enforced (1,2,3,5,8,13) to prevent false precision in story points.
- **fastembed over sentence-transformers** — Switched in v0.7.6 to eliminate CUDA bloat and reduce install size.
- **Hub mode via git submodules** — Leverages existing git infrastructure for multi-repo management without custom sync.
- **HTMX for web dashboard** — Server-rendered with minimal JS; keeps the codebase Python-centric.
- **Optional extras** — `[mcp]`, `[web]`, `[embeddings]`, `[all]` — users install only what they need.

## Dependencies

- **click** (>=8.0) — CLI framework
- **pyyaml** (>=6.0) — YAML parsing for config and index
- **pydantic** (>=2.0) — Data models and validation
- **jinja2** (>=3.0) — Template rendering for generated files
- **python-frontmatter** (>=1.0) — Markdown + YAML frontmatter parsing
- **mcp[cli]** (>=1.0) — MCP server framework (optional)
- **fastembed** (>=0.4) + **numpy** (>=1.24) — Semantic search embeddings (optional)
- **fastapi** (>=0.115) + **uvicorn** (>=0.34) — Web dashboard (optional)

## Development Setup

```bash
# Clone
git clone https://github.com/Biztactix-Ryan/ProjectMan.git
cd ProjectMan

# Create venv and install with dev dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"

# Run tests
pytest

# Run MCP server (for Claude Code)
projectman serve

# Launch web dashboard
projectman web
```

---
*Last reviewed: 2026-02-16*
*Update this document when architecture changes. The daily audit checks for staleness.*
