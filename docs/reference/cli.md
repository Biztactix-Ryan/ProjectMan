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
| `--prefix` | `PRJ` | Uppercase prefix for IDs (e.g. `MP` → `US-MP-1`, `US-MP-1-1`, `EPIC-MP-1`) |
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
├── epics/
├── stories/
└── tasks/
```

With `--hub`, also creates:
```
.project/
├── VISION.md
├── ARCHITECTURE.md
├── DECISIONS.md
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
| `.claude/skills/pm-do/SKILL.md` | `/pm-do` skill |

If `.mcp.json` already exists, ProjectMan merges its server config into the existing file without overwriting other MCP servers.

**Note:** If upgrading from an older version, stale skill directories (e.g. `pm-scope`, `pm-audit`, `pm-fix`, `pm-init`) may remain in `.claude/skills/`. These can be safely deleted.

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

## projectman sync

Pull latest from all hub submodules. Hub mode only.

```bash
projectman sync
```

**What it does:**

1. Iterates through all registered subprojects
2. Pulls the latest changes for each submodule
3. Updates submodule references

## projectman set-branch

Set the tracking branch for a subproject. Hub mode only.

```bash
projectman set-branch my-api develop
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Name of the registered subproject |
| `branch` | Branch name to track |

## projectman repair

Scan the hub for unregistered projects, initialize missing `.project/` directories, rebuild all indexes and embeddings, and regenerate dashboards. Hub mode only.

```bash
projectman repair
```

**What it does:**

1. Discovers directories in `projects/` not registered in config — registers them
2. Initializes `.project/` structure for projects that don't have one
3. Rebuilds `index.yaml` for every subproject
4. Rebuilds hub-level embeddings from all subproject stories/tasks (namespaced IDs)
5. Regenerates hub dashboards (`status.md`, `burndown.md`)
6. Writes a `REPAIR.md` report to `.project/`

Use this after cloning a hub, adding projects manually, or whenever things seem out of sync.

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

**Checks performed (13 total):**

| # | Check | Severity | Description |
|---|-------|----------|-------------|
| 1 | Done story with incomplete tasks | ERROR | Story marked done but has tasks not marked done |
| 2 | Undecomposed stories | WARNING | Active/ready stories with no tasks |
| 3 | Stale in-progress | WARNING | Items in-progress for >14 days without update |
| 4 | Point mismatch | INFO | Story points don't match sum of task points |
| 5 | Thin description | INFO | Story or task body has fewer than 20 characters |
| 6 | Documentation staleness/missing | ERROR/WARNING/INFO | Missing docs (error), unfilled templates (warning), stale docs (info) |
| 7 | Empty active epic | WARNING | Active epic with no linked stories |
| 8 | Done epic with open stories | ERROR | Epic marked done but has stories not done/archived |
| 9 | Orphaned epic reference | WARNING | Story references a non-existent epic ID |
| 10 | Stale draft epic | INFO | Draft epic with no stories for >30 days |
| 11 | Hub documentation checks | WARNING/INFO | Missing or unfilled hub docs (VISION.md, ARCHITECTURE.md, DECISIONS.md) |
| 12 | Stale task assignment | WARNING | Task assigned to someone with no updates for >14 days |
| 13 | Malformed files in quarantine | WARNING | Files quarantined in `.project/malformed/` needing repair |

Output is written to `.project/DRIFT.md` and printed to stdout.
