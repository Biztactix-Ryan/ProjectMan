# Installation

## Prerequisites

- Python 3.10+
- pip
- git

## Install from GitHub

```bash
# Recommended — includes MCP server for Claude Code integration
pip install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Base package only (CLI + store, no MCP server)
pip install "git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# With semantic search (requires sentence-transformers)
pip install "projectman[embeddings] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Everything (MCP + embeddings)
pip install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Development (clone + editable install)
git clone https://github.com/Biztactix-Ryan/ProjectMan.git
cd ProjectMan
pip install -e ".[all,dev]"
```

## Verify

```bash
projectman --help
```

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `mcp` | mcp[cli] | MCP server for Claude Code |
| `embeddings` | sentence-transformers, numpy | Semantic search |
| `dev` | pytest | Testing |
