# Installation

The supported install is the Claude Code plugin: see
[Install as a Claude Code plugin](#install-as-a-claude-code-plugin). It needs uv and a
Claude Code release with plugin support (no minimum version is recorded yet; verified on
Claude Code 2.1.292). The pipx CLI below is optional with the plugin: install it for
`projectman init`, `projectman web` and `projectman migrate-to-plugin` from a shell.
`projectman setup-claude` and `projectman refresh-skills` are deprecated and now only print
the plugin steps; an existing setup-claude install moves over with
[`projectman migrate-to-plugin`](#old-setup-claude-copies).

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

## Install the CLI with pipx

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

That reinstalls from the git URL above. If you install from a local checkout instead,
`pipx upgrade` will not see your changes — see [Upgrading](#upgrading).

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

**Plugin:** `/plugin marketplace update projectman`, `/plugin update projectman@projectman`,
then `/reload-plugins` — see [Updating](#updating). Nothing else to run.

**pipx CLI from a checkout:** `pipx upgrade projectman` reinstalls from the source pipx
recorded, **not** your working tree, so it never picks up local changes. The current
release is 0.11.0; `CHANGELOG.md` records what changed in it.

**Stale install symptoms:** the CLI behaves like an older version than your checkout — a
tool argument the code accepts is rejected as unexpected, or a flag you can see in `src/`
is missing. Reinstall from the checkout, then restart Claude Code:

```bash
pipx install --force "/path/to/ProjectMan[all]"   # --force: the version may not have changed
```

Still on setup-claude skill copies? Run `projectman migrate-to-plugin`. For this one
release only, `projectman refresh-skills --keep-local --legacy` re-renders them the old way
(plain `refresh-skills` now only prints the plugin steps).

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

## Install as a Claude Code plugin

ProjectMan ships as a Claude Code plugin, and this is the supported install. The repo is
both the marketplace and the plugin. Installing it gives you the pm skills (`/projectman:pm`, `/projectman:pm-status`,
...), the `projectman:pm` agent, the projectman MCP server and a SessionStart hook that
prints a ProjectMan status block. You don't need pipx or `setup-claude` for this path.

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) on `PATH`. The plugin
  starts its MCP server with `uv run --project <plugin dir> --extra all projectman serve`
  and its hook with `uv run ... projectman session-context`. uv builds the environment on
  first use. Without uv, the hook prints a one-line warning and the MCP tools stay
  unavailable.
- git, and Claude Code with plugin support. No minimum version is recorded yet; these
  steps were verified on Claude Code 2.1.292 and, from a clean config directory, on 2.1.303 (`claude --version`).

### Add the marketplace and install

In Claude Code:

```
/plugin marketplace add Biztactix-Ryan/ProjectMan
/plugin install projectman@projectman
```

From a local clone, point the marketplace at the checkout instead:

```
/plugin marketplace add /path/to/ProjectMan
/plugin install projectman@projectman
```

The same steps from a shell, scoped to one project (`--scope user` is the default; with
`local`, the entries go into that project's `.claude/settings.local.json`):

```bash
cd /path/to/your/project
claude plugin marketplace add /path/to/ProjectMan --scope local
claude plugin install projectman@projectman --scope local
```

**First session after install:** if you install from inside a running session, the MCP
tools may not show up until the next session. Run `/reload-plugins`. If the tools are
still missing, start a new session.

### Verify

- **Skills and agent:** `/projectman:pm-status` and the other `projectman:*` skills show
  up in the `/` menu, and the `projectman:pm` agent is listed in `/agents`.
- **MCP tools:** `/mcp` lists `plugin:projectman:projectman` as connected. Its tools are
  namespaced `mcp__plugin_projectman_projectman__pm_*`.
- **Status block:** start a session in a directory that has a `.project/`. The session
  opens with a `## ProjectMan context (<path>/.project)` block. The hook prints nothing
  in directories without a `.project/`, and no plugin skill or MCP tool creates one.
- **Sprint band:** in the terminal and the desktop app, a dim line above the prompt shows
  the active sprint's points, the task in progress and the first line of the NEXT.md
  note, for example `Sprint 20 — 11/19 pts · ▶ US-PM-62-6 Draw the sprint band · next:
  Close EPIC-PM-7`. The plugin reads it from its MCP server when the band is first drawn
  and again after each turn, so it costs no model tokens. A part with nothing to show is
  left out, and in a directory without a `.project/` the band shows nothing.

Creating a store needs the `projectman init` CLI. If you installed the CLI, run
`projectman init` in the project. On a plugin-only machine, run the copy that ships
with the plugin, through the same `uv` environment the plugin's MCP server uses:

```bash
cd /path/to/your/project
uv run --project ~/.claude/plugins/cache/projectman/projectman/0.11.0 --extra all projectman init
```

Replace `0.11.0` with the installed version. If you're not sure of the path, run
`claude plugin list --json` and use the `installPath` it shows. Then start a new
session in the project to see the status block.

To check without opening the TUI, run a headless session and read its init event:

```bash
claude -p --output-format stream-json --verbose --include-hook-events --max-turns 1 "Reply OK"
```

The `system`/`init` line lists the `projectman:*` skills, the `projectman:pm` agent and
`plugin:projectman:projectman` with `"status": "connected"`. A `hook_response` line for
`SessionStart:startup` carries the status block in its `output`. Both lines are written
before Claude Code contacts the API, so the check works even when the session is not
logged in; the reply is then "Not logged in", which does not affect the check.
`claude mcp list` shows the server as connected as well.

`claude plugin install` may also print "1 userConfig option not yet set". That option is
`guard_main_session`, which defaults to off. You only need to set it if you want the
worker git guards in the main session too (`/plugin configure projectman@projectman`).

### Letting a clean orchestrate run merge

When a `/projectman:pm-orchestrate` run ends, it merges its run branch `orch/<run-id>`
into the branch you started it from and deletes the run branch. The run branch only ever
holds accepted, validated work, so it lands even when some tasks were parked or sent to
review: those tasks stay on their own `orch/<run-id>--<task-id>` branches and worktrees,
and the report lists each one as "not landed". Only a dirty working tree outside
`.project/`, or a merge that conflicts, keeps the run branch. Claude Code's auto-mode
classifier blocks the merge, because it changes your branch without asking. Unless you
add a permission rule, the run prints the merge command for you to run instead. To let it
merge, allow just those commands in `.claude/settings.local.json` (or
`.claude/settings.json`, or `~/.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "Bash(git merge --ff-only orch/*)",
      "Bash(git merge --no-ff -m * orch/*)",
      "Bash(git branch -d orch/*)"
    ]
  }
}
```

Keep the rules this narrow. The first is the normal case. The second covers a start
branch that moved during the run, and the third deletes the run branch once it has been
merged. Parked and review task branches are never merged by the run, whatever the
rules allow; you read them and decide.

### Updating

```
/plugin marketplace update projectman
/plugin update projectman@projectman
/reload-plugins
```

From a shell, run `claude plugin marketplace update projectman` and then
`claude plugin update projectman@projectman`. After that, run `/reload-plugins` in any
open session, or start a new one. `/reload-plugins` re-reads the plugin's skills, agents
and hooks inside the running session, so you don't need to restart Claude Code.
`plugin update` still ends with "Restart to apply changes". Running `/reload-plugins`
is enough; it picks up changed skills and newly added ones.

`plugin update` only moves when the plugin's `version` in `.claude-plugin/plugin.json`
changes. If the version is unchanged, it reports "already at the latest version".

A marketplace added from a local clone is read straight from that folder. An edit to a
skill in the checkout is picked up by `/reload-plugins` or by the next session, without
a `plugin update`.

### Old `setup-claude` copies

If you previously ran `projectman setup-claude` (or `refresh-skills`), the pm skills and
agent also exist as plain copies in `~/.claude/` or a project's `.claude/`. A pipx
`projectman` MCP entry may also exist in `~/.claude.json`. These sit alongside the
plugin, so every skill appears twice: once as `pm-status`, once as
`projectman:pm-status`. There are also two projectman MCP servers. Remove the old copies
with `projectman migrate-to-plugin`; run it in each project that has its own `.claude/`
copies or `.mcp.json` entry:

```bash
projectman migrate-to-plugin --dry-run   # list what would be removed, write nothing
projectman migrate-to-plugin             # remove it
```

It removes only what ProjectMan wrote: the pm agent and skills in `~/.claude` and
`./.claude`, the user-scope projectman MCP server, the projectman entry in `./.mcp.json`,
and the per-project `pm-context.sh` SessionStart hook. Other skills, MCP servers, hooks
and a user-modified `pm-context.sh` are kept. Restart Claude Code afterwards.
