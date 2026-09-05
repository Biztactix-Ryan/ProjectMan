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

## Upgrading

`pipx upgrade projectman` reinstalls from the source pipx recorded — for a git URL that
means the published branch, **not** your working tree. A plain `pipx upgrade` never picks
up local changes.

**Stale install symptoms:** the CLI or MCP server behaves like an older version than your
checkout — a tool argument the code accepts is rejected as unexpected, a flag you can see
in `src/` is missing, or an installed pm skill mentions a tool that does not exist.

Reinstall from the checkout, re-render the skills, then restart Claude Code:

```bash
# 1. Reinstall from the local tree (--force: the version number may not have changed)
pipx install --force "/path/to/ProjectMan[all]"

# 2. Re-render the pm agent + skills from the newly installed templates
projectman refresh-skills --keep-local
```

`--keep-local` keeps and refreshes project-local `.claude/` skill copies; without it they
are pruned when the same skills are installed globally in `~/.claude`.

Then **restart Claude Code** (or start a new session): the MCP server is a long-lived child
process, so a running session keeps the old code until that process is replaced.

### The `mcp<2` requirement

ProjectMan pins `mcp[cli]>=1.0,<2` because mcp 2.x renamed `FastMCP`, which `projectman
serve` imports. An environment holding mcp 2.x fails with:

```
Error: MCP extras not installed. Run: pip install projectman[mcp]
```

Reinstalling as above resolves the pin. In a hand-managed environment, force it with
`pipx inject projectman "mcp[cli]<2"` or `pip install "mcp[cli]<2"`.

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `mcp` | mcp[cli] | MCP server for Claude Code integration |
| `web` | fastapi, uvicorn | Web dashboard with kanban board, burndown charts, and project overview |
| `embeddings` | fastembed, numpy | Semantic search via embeddings |
| `all` | all of the above | Everything |
| `dev` | pytest, pytest-tmp-files, httpx | Testing |
