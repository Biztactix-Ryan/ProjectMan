# Installation

## Prerequisites

- Python 3.10+
- git
- pipx (recommended) or pip

## Install with pipx (Recommended)

pipx installs ProjectMan in an isolated virtual environment and puts the `projectman` command on your PATH. This is the cleanest approach on modern Linux/macOS where system-wide pip installs are restricted.

```bash
# Install pipx if you don't have it
sudo apt install pipx    # Debian/Ubuntu
brew install pipx        # macOS
pipx ensurepath          # Add to PATH (restart shell after)

# Install ProjectMan with MCP support (recommended)
pipx install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or with everything (MCP + semantic search)
pipx install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

## Install with pip (in a venv)

If you prefer managing your own virtual environments:

```bash
# Create and activate a venv
python3 -m venv ~/.venvs/projectman
source ~/.venvs/projectman/bin/activate

# Install
pip install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

Note: you'll need to activate the venv or add it to your PATH for the `projectman` command to be available.

## Development Install

```bash
git clone https://github.com/Biztactix-Ryan/ProjectMan.git
cd ProjectMan
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

## Verify

```bash
projectman --help
```

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `mcp` | mcp[cli] | MCP server for Claude Code integration |
| `embeddings` | sentence-transformers, numpy | Semantic search via embeddings |
| `all` | both of the above | Everything |
| `dev` | pytest, pytest-tmp-files | Testing |
