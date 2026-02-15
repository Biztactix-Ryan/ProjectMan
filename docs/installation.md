# Installation

## Prerequisites

- Python 3.10+
- git
- pipx (recommended) or pip

## Setting Up pipx

pipx installs Python CLI tools in isolated virtual environments and puts them on your PATH. This is the cleanest approach on modern Linux/macOS where system-wide pip installs are restricted (PEP 668).

```bash
# Debian/Ubuntu
sudo apt install pipx

# macOS
brew install pipx

# Fedora/RHEL
sudo dnf install pipx

# Or via pip (any platform)
python3 -m pip install --user pipx

# Add pipx to your PATH (required after first install)
pipx ensurepath
```

After running `pipx ensurepath`, restart your shell (or run `source ~/.bashrc` / `source ~/.zshrc`) for the PATH change to take effect.

## Install with pipx (Recommended)

```bash
# Install everything (MCP + web dashboard + semantic search)
pipx install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or just MCP + web dashboard (no semantic search)
pipx install "projectman[mcp,web] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"

# Or MCP only (no web dashboard or semantic search)
pipx install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

To upgrade later:

```bash
pipx upgrade projectman
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
| `web` | fastapi, uvicorn | Web dashboard with kanban board, burndown charts, and project overview |
| `embeddings` | sentence-transformers, numpy | Semantic search via embeddings |
| `all` | all of the above | Everything |
| `dev` | pytest, pytest-tmp-files, httpx | Testing |
