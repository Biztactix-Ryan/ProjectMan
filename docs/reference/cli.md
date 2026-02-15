# CLI Reference

## projectman init

Initialize a new `.project/` directory in the current repo.

```bash
projectman init --name "My Project" --prefix MP
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | _(prompted)_ | Project name |
| `--prefix` | `PRJ` | Uppercase prefix for story IDs (e.g. `MP` → `MP-1`, `MP-2`) |
| `--description` | `""` | Project description |
| `--hub` | `false` | Initialize in hub mode (multi-repo management) |

**What it creates:**

```
.project/
├── config.yaml
├── PROJECT.md
├── INFRASTRUCTURE.md
├── SECURITY.md
├── index.yaml
├── stories/
└── tasks/
```

With `--hub`, also creates:
```
.project/
├── projects/
├── roadmap/
└── dashboards/
```

## projectman setup-claude

Install Claude Code integration files into the current project.

```bash
projectman setup-claude
```

**What it creates:**

| File | Purpose |
|------|---------|
| `.mcp.json` | MCP server configuration (merged with existing if present) |
| `.claude/agents/pm.md` | PM agent definition |
| `.claude/skills/pm/SKILL.md` | General `/pm` skill |
| `.claude/skills/pm-status/SKILL.md` | `/pm-status` skill |
| `.claude/skills/pm-plan/SKILL.md` | `/pm-plan` skill |
| `.claude/skills/pm-scope/SKILL.md` | `/pm-scope` skill |
| `.claude/skills/pm-audit/SKILL.md` | `/pm-audit` skill |
| `.claude/skills/pm-do/SKILL.md` | `/pm-do` skill |

If `.mcp.json` already exists, ProjectMan merges its server config into the existing file without overwriting other MCP servers.

## projectman serve

Start the MCP server in stdio transport mode. This is called automatically by Claude Code via the `.mcp.json` configuration — you typically don't need to run this manually.

```bash
projectman serve
```

Requires the `mcp` extra: `pip install "projectman[mcp] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"`

## projectman add-project

Add a project as a git submodule to a hub. Only available in hub mode.

```bash
projectman add-project my-api git@github.com:org/my-api.git
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Short name for the project (becomes directory name under `projects/`) |
| `git_url` | Git remote URL for the repository |

**What it does:**

1. Runs `git submodule add <url> projects/<name>`
2. Registers the project in `.project/config.yaml`
3. The submodule's `.project/` directory becomes visible to the hub

## projectman audit

Run drift detection and generate a `DRIFT.md` report.

```bash
# Audit current project
projectman audit

# Audit all projects in hub
projectman audit --all
```

**Options:**

| Option | Description |
|--------|-------------|
| `--all` | Audit all projects in the hub (hub mode only) |

**Checks performed:**

| Check | Severity | Description |
|-------|----------|-------------|
| Done + incomplete tasks | warning | Story marked done but has tasks not marked done |
| Undecomposed stories | info | Active/ready stories with no tasks |
| Stale in-progress | warning | Items in-progress for >14 days without update |
| Point mismatch | info | Story points don't match sum of task points |
| Thin description | info | Story body has fewer than 20 characters |

Output is written to `.project/DRIFT.md` and printed to stdout.
