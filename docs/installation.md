# Installation

## Prerequisites

- Python 3.10+
- pip

## Install

```bash
# Base package
pip install projectman

# With MCP server support (for Claude Code integration)
pip install "projectman[mcp]"

# With semantic search (requires sentence-transformers)
pip install "projectman[embeddings]"

# Everything
pip install "projectman[all]"

# Development
pip install "projectman[all,dev]"
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
