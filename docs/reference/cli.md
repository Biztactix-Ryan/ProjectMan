# CLI Reference

## projectman init

Initialize a new `.project/` directory in the current repo.

```bash
projectman init --name "My Project" --prefix MP
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | _(prompted)_ | Project name — prompted for only when a store is actually scaffolded |
| `--prefix` | `PRJ` | Uppercase prefix for IDs (e.g. `MP` → `US-MP-1`, `US-MP-1-1`, `EPIC-MP-1`) |
| `--description` | `""` | Project description |
| `--hub` | `false` | Initialize in hub mode (multi-repo management) |
| `--no-attach` | `false` | Scaffold a fresh store even when a `projectman` branch exists |

**On a clone it attaches instead of scaffolding:**

If the PM store lives on its own branch (see [`migrate-worktree`](#projectman-migrate-worktree)), a fresh clone has nothing to scaffold — the store already exists, it is just not mounted. So init first looks for a `projectman` branch and, when it finds one, runs the [`attach`](#projectman-attach) flow instead:

```
$ projectman init
Found origin/projectman — attaching the existing PM store instead of scaffolding a new one.
Attached .project/ to branch 'projectman'
...
```

| Condition | Result |
|-----------|--------|
| `origin/projectman` or a local `projectman` branch exists, and `.project/` is absent or an empty directory | Attaches; no files are written and `.gitignore` is untouched |
| Same, but `.project/` is already a worktree of the branch | Friendly no-op, exit 0 (`Already attached: …`) rather than the "already exists" error |
| Same, but `.project/` is a plain directory with content | `Error: .project/ already exists`, exit 1, nothing touched |
| No such branch — including outside a git repo | Scaffolds exactly as it always did |

Detection reads **local ref storage only and never fetches**, so run `git fetch origin` first if the branch was pushed after your last fetch. In the attach case `--name`, `--prefix`, `--description` and `--hub` describe a store that is not being created, so each one you passed is reported as ignored on stderr (`--hub ignored: attaching existing store`) and the attach still runs. Pass `--no-attach` to force the scaffolding path; it then refuses an existing `.project/` as usual.

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
| `.claude/skills/pm-orchestrate/SKILL.md` | `/pm-orchestrate` skill (drive a sprint via subagents) |
| `.claude/skills/pm-autoscope/SKILL.md` | `/pm-autoscope` skill (bulk epic/story/task creation) |
| `.claude/skills/pm-cleanup/SKILL.md` | `/pm-cleanup` skill (archive completed work) |

If `.mcp.json` already exists, ProjectMan merges its server config into the existing file without overwriting other MCP servers.

**Note:** If upgrading from an older version, stale skill directories (e.g. `pm-scope`, `pm-audit`, `pm-fix`, `pm-init`) may remain in `.claude/skills/`. These can be safely deleted.

## projectman upgrade

Upgrade projectman via pipx and keep installed skills in sync.

```bash
projectman upgrade              # upgrade + refresh installed skills
projectman upgrade --check     # show installed version and pipx source only
projectman upgrade --no-skills # upgrade without touching skill files
```

After a successful upgrade the command invokes the **new** binary's `refresh-skills`, re-rendering the pm agent and skills from the upgraded templates wherever they are already installed (`~/.claude` and the current directory's `.claude/`). `projectman update` is an alias.

## projectman refresh-skills

Re-render the pm agent + skills from the installed package's templates, in every location where they are already installed (`~/.claude` and `./.claude`). Does not install into new locations — use `setup-claude` for that. Run this in each project that keeps local skill copies after upgrading elsewhere.

```bash
projectman refresh-skills               # refresh (prunes superseded local copies)
projectman refresh-skills --keep-local  # keep + refresh local copies alongside global
```

If the skills are installed both globally and in the current project, the project-local copies are superseded — Claude Code loads both and shows duplicate skills — so they are removed by default (only ProjectMan-managed files are touched: `agents/pm.md` and `skills/pm*`; other agents/skills are left alone). Pass `--keep-local` to keep and refresh them instead. After any refresh, restart Claude Code (or start a new session) to pick up the updated skills.

## projectman web

Start the web dashboard server. Provides a visual UI with kanban board, epic/story/task views, search, burndown charts, and drag-drop status updates.

```bash
# Start with defaults (127.0.0.1:8000)
projectman web

# Bind to all interfaces on a custom port
projectman web --host 0.0.0.0 --port 9000
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Host/IP to bind to (`0.0.0.0` for all interfaces) |
| `--port` | `8000` | Port to listen on |

Requires the `web` extra: `pip install "projectman[web] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"`

The web dashboard can also be started via MCP tools (`pm_web_start` / `pm_web_stop`) or the `/pm web start` skill command, which allows Claude to manage the server lifecycle and automatically find an available port.

## projectman serve

Start the MCP server. In the default stdio transport this is called automatically by Claude Code via the `.mcp.json` configuration — you typically don't need to run it manually. The SSE transport is for connecting remote clients or the orchestrator over HTTP.

```bash
# stdio (default) — used by Claude Code
projectman serve

# SSE over HTTP — for remote clients / the orchestrator
projectman serve --transport sse --host 0.0.0.0 --port 22001
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--transport` | `stdio` | Transport mode: `stdio` or `sse` |
| `--host` | `127.0.0.1` | Host to bind to (SSE mode only) |
| `--port` | `22001` | Port to bind to (SSE mode only) |

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

## projectman commit

Commit `.project/` changes to git.

```bash
# Commit all .project/ changes (hub + all subprojects)
projectman commit

# Commit only hub-level changes
projectman commit --scope hub

# Commit a specific subproject's changes
projectman commit --scope project:my-api

# With a custom message
projectman commit --message "Update sprint 3 tasks"
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--scope` | `all` | Scope: `hub`, `project:<name>`, or `all` |
| `--message` | _(auto-generated)_ | Commit message |

## projectman push

Push committed changes to remote.

```bash
# Push hub changes
projectman push

# Push a specific subproject
projectman push --scope project:my-api

# Coordinated push (preflight → subprojects → hub)
projectman push --projects my-api,my-frontend

# Dry run to preview
projectman push --dry-run
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--scope` | `hub` | Scope: `hub`, `project:<name>`, or `all` |
| `--dry-run` | `false` | Preview what would be pushed without pushing |
| `--projects` | _(auto-discover)_ | Comma-separated project names for coordinated push |

When `--projects` or `--dry-run` is used, the push runs in coordinated mode: preflight checks run first, then subprojects are pushed, then the hub.

## projectman git-status

Show git status of all hub submodules in a table.

```bash
projectman git-status
projectman git-status --verbose
projectman git-status --json
```

**Options:**

| Option | Description |
|--------|-------------|
| `--verbose` | Show additional detail |
| `--json` | Output as JSON |

**Output includes:** project name, branch, dirty state, ahead/behind counts, and open PRs.

## projectman validate-branches

Check that hub submodule branches match their configured tracking branches.

```bash
projectman validate-branches
```

## projectman changeset

Manage changesets for coordinating multi-project changes. Hub mode only.

### projectman changeset create

```bash
projectman changeset create "Auth across services" --projects my-api,my-frontend
projectman changeset create "DB migration" --projects my-api --description "Schema v2 migration"
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `name` | yes | Changeset title (positional argument) |
| `--projects` | yes | Comma-separated project names |
| `--description` | no | Changeset description |

### projectman changeset add-project

```bash
projectman changeset add-project CS-PRJ-1 my-worker --ref feature/auth-worker
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `changeset_id` | Changeset ID (e.g. `CS-PRJ-1`) |
| `project_name` | Project name to add |

**Options:**

| Option | Description |
|--------|-------------|
| `--ref` | Git branch/ref for this project's changes |

### projectman changeset status

```bash
# List all changesets
projectman changeset status

# Show specific changeset
projectman changeset status CS-PRJ-1
```

### projectman changeset create-prs

Generate `gh` CLI commands for creating cross-referenced PRs.

```bash
projectman changeset create-prs CS-PRJ-1
```

Prints one `cd <project> && gh pr create …` line per project with a ref.
The commands are built from argument lists and rendered with `shlex.quote`
/ `shlex.join`, so a title, description or branch ref containing `"`,
backticks, `$(…)`, `;`, `&&`, `|` or a newline is quoted rather than
interpreted.  The MCP tool `pm_changeset_create_prs` returns the same
invocation as an `argv` list for callers that execute it without a shell.
Nothing is executed — review the output, then run it.

### projectman changeset push

Check PR merge status and update changeset status.

```bash
projectman changeset push CS-PRJ-1
```

## projectman migrate-archived

Repair tasks the activity log says were archived but whose files are not flagged archived.

Before ProjectMan gave tasks an `archived` flag, archiving a task set its status to `done`. Abandoned work therefore counts as delivered in completion, burndown and velocity. This command finds tasks whose `archived` flag went missing from disk — a dropped write, a hand-edited or restored frontmatter, a bad merge — and puts it back.

```bash
# Report what would change — the default, writes nothing
projectman migrate-archived

# Write the changes
projectman migrate-archived --apply
```

**Options:**

| Option | Description |
|--------|-------------|
| `--apply` | Write the changes. Without it the command only reports. |
| `--project` | Project name (hub mode only) |

**Safety:**

- Dry run by default — `--apply` is the only thing that writes.
- Idempotent: a migrated task carries `archived: true`, so re-running finds nothing.
- Never runs implicitly. No other command triggers it.
- **The migration never moves a task out of `done` on inferred evidence.**

**What it can and cannot detect.** Identification requires a *positive archive signal*: an activity event that explicitly wrote `archived: true` for the task (a dedicated `archive` event counts equally), not later cleared. A candidate is a task carrying that signal whose file has lost the flag. Applying sets `archived: true`; it restores a status only when the signal event itself recorded a status change. Consequently:

- A task closed in a single `todo -> done` write is **not** a candidate. The pre-`archived`-flag archive was literally `update(status="done")`, which is byte-identical to routine completion, so that footprint is no longer evidence of anything. Those tasks are listed under "need manual review" and never written — see ADR-002 in `.project/DECISIONS.md`.
- Archives made before the flag existed are unrecoverable by machine. The manual remedy is to archive by hand — the `pm_archive` MCP tool, or `Store.archive(task_id)` directly; no CLI subcommand exposes it today. Either sets the flag and leaves `status` alone, which fixes the metrics without claiming the work was never done.
- A task whose status changed after the archive was recorded was picked back up; it is reported as skipped rather than migrated.
- If a signal event's status payload is unusable, the task is listed under "need manual review" and left untouched — the migration never invents a status.

Every ambiguous case is skipped rather than written: a missed archive is a metrics inaccuracy, whereas a wrongly restored task destroys the record of real completed work.

## projectman migrate-worktree

Move `.project/` onto a dedicated orphan branch mounted as a worktree, so project state stops riding along with code commits.

```bash
projectman migrate-worktree
```

It runs the migration end to end:

1. creates an empty orphan `projectman` branch — a root commit `ProjectMan root` over the empty tree, built with `git commit-tree` so your checkout and `HEAD` are never touched;
2. untracks `.project` on the current branch (`git rm -r --cached`) and adds a `.project/` line to `.gitignore` (no duplicate if one is already there);
3. commits those two changes on the current branch;
4. moves the PM files aside to a temp directory and mounts the branch with `git worktree add .project projectman`;
5. restores the files into the worktree and commits them there;
6. pushes the branch with `git push -u origin <branch>` when an `origin` remote is configured — once after step 1 and again after step 5.

**Options:**

| Option | Description |
|--------|-------------|
| `--branch` | Branch to create and mount (default: `projectman`) |
| `--no-push` | Migrate locally only; never push, even when an `origin` remote exists |

**Safety:**

- The temp copy of your PM files is only deleted once the worktree commit has succeeded; any failure after the move puts the files back where they were.
- Every precondition is checked before the first mutation, so a refusal leaves the repo exactly as it was — no branch created, no commit, `.gitignore` and `.project/` untouched. Refusals exit non-zero with the reason on stderr.

**It refuses to run when:**

| Condition | Message points you at |
|-----------|----------------------|
| The target branch already exists locally | `projectman attach` |
| `origin/<branch>` already exists in local ref storage | `projectman attach` |
| `.project/` is already a git worktree | nothing to migrate |
| There is no `.project/` to move | the missing directory |
| The working tree is dirty | commit or stash first (the offending paths are listed) |

Dirty means, precisely:

- **blocks** — any staged or unstaged change to a *tracked* file anywhere in the repo (modification, deletion, rename, unmerged conflict). The migration commits on your current branch, so staged work would be swept into that commit, and a change inside `.project/` would additionally be carried unreviewed into the import commit;
- **blocks** — an *untracked* file under `.project/` when the PM store is already partly tracked, since the import commit would silently pick it up;
- **does not block** — untracked files outside `.project/` (they are neither committed nor moved), a `.project/` that is untracked in its entirety (that is exactly what the migration is for), or ignored files.

The `origin/<branch>` check reads local refs only — it never fetches, so a branch pushed since your last `git fetch` is invisible to it.

**Remotes:**

When `git remote get-url origin` succeeds, the migration pushes `<branch>` twice — right after the orphan branch is created, and again after the import commit — so `origin/<branch>` ends at the import commit and the local branch has `origin/<branch>` as its upstream. Only `<branch>` is pushed; the commit the migration makes on your current branch is left for you to push.

| Situation | What happens |
|-----------|--------------|
| `origin` configured | `git push -u origin <branch>` after branch creation and after the import commit |
| No `origin` remote | Pushes skipped, migration succeeds, output says `no origin remote — skipped push; run \`git -C .project push -u origin projectman\` after adding one.` |
| `--no-push` given | Pushes skipped even with a remote; publish later with `git -C .project push -u origin projectman` |
| First push fails | **Fatal** — exit 1. Branch creation was the only mutation, so the branch is deleted and nothing is migrated. Fix the remote and re-run, or use `--no-push` |
| Second push fails | **Warning only** — exit 0. The local migration has already landed and is correct; undoing it over an unreachable remote would be strictly worse. The output names git's error and tells you to re-run `git -C .project push` |

Only the configured `origin` is contacted, and only by `git push`. A repo without a remote migrates entirely offline.

**Snapshot import vs. the history-preserving variant:**

Snapshot import is the default and the only mode this command implements: the `projectman` branch starts from an empty root commit and the migration adds one commit holding `.project/` as it stands now. The history of those files is not deleted — it stays where it always was, on the branch you migrated from.

[ADR-001](../../.project/DECISIONS.md) ("Store PM data on an orphan branch mounted as a worktree") records the alternative:

> Migration is a snapshot import by default; `git filter-repo --subdirectory-filter .project` is the history-preserving variant.

To take that route instead of running `migrate-worktree`: clone the repo, run `git filter-repo --subdirectory-filter .project` on the clone to rewrite its history down to just the PM files, push the result as the `projectman` branch, then untrack and gitignore `.project/` on your working branch and mount the branch with `projectman attach`. It costs a rewrite and an extra clone; the payoff is that `git log` inside `.project/` reaches back past the migration.

## projectman attach

Mount the `projectman` branch at `.project/` — the fresh-clone counterpart of `migrate-worktree`.

```bash
projectman attach
```

A clone of a migrated repo arrives with `origin/projectman` but no `.project/`, because the PM state lives on its own branch and the working branch ignores that path. Attach runs the git incantation that mounts it:

> [`projectman init`](#projectman-init) detects that branch and runs this same flow by itself, so on a fresh clone either command works; reach for `attach` when you want the mount explicitly, or with a `--branch` other than the default.

| Situation | What it runs |
|-----------|--------------|
| Only `origin/projectman` exists | `git worktree add --track -b projectman .project origin/projectman` — creates the local branch tracking the remote one |
| A local `projectman` branch already exists, unmounted | `git worktree add .project projectman` — the existing branch is mounted as-is, never recreated |

**Options:**

| Option | Description |
|--------|-------------|
| `--branch` | Branch to mount at `.project` (default: `projectman`) — use the same name you passed to `migrate-worktree` |

**Idempotent and clobber-safe:**

| `.project/` is | What happens |
|----------------|--------------|
| Missing | Mounted |
| An empty directory | Removed, then mounted (`git worktree add` wants a path that does not exist); it is put back if the add fails |
| Already a worktree of `<branch>` | **No-op**, exit 0: `Already attached: .project/ is a worktree of 'projectman' — nothing to do.` |
| A worktree of a *different* branch (or a detached HEAD) | Refused, exit 1, naming what is actually mounted |
| A plain directory with content | Refused, exit 1, untouched — it is either an unmigrated store (run `projectman migrate-worktree`) or files that are not ours to delete |
| A file | Refused, exit 1, untouched |

It also refuses (exit 1) when there is no `projectman` branch locally or as `origin/projectman`, pointing at `git fetch origin` when a remote is configured and at `projectman migrate-worktree` when there is not.

Attach reads **local ref storage only and never fetches**, so a branch pushed since your last `git fetch origin` is invisible to it; the refusal says as much. Nothing is committed or pushed, and no tracked file is edited — a migrated repo already ignores `.project/` on its working branch, so attach only mounts.

Refusals happen before any mutation, so a refused attach leaves the repo exactly as it was: no branch created, no worktree registered, `.project/` byte for byte as it was found.

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

**Checks performed (17 total):**

| # | Check | Severity | Description |
|---|-------|----------|-------------|
| 1 | Done story with incomplete tasks | ERROR | Story marked done but has tasks not marked done |
| 2 | Undecomposed stories | WARNING | Active/ready stories with no tasks |
| 3 | Stale in-progress | WARNING | Items in-progress for >14 days without update |
| 4 | Point mismatch | INFO | Story points don't match sum of task points |
| 5 | Thin description | INFO | Story or task body has fewer than 20 characters |
| 6 | Missing acceptance criteria | WARNING | Active/ready story with no acceptance criteria |
| 7 | Documentation staleness/missing | ERROR/WARNING/INFO | Missing docs (error), unfilled templates (warning), stale docs (info) |
| 8 | Empty active epic | WARNING | Active epic with no linked stories |
| 9 | Done epic with open stories | ERROR | Epic marked done but has stories not done/archived |
| 10 | Orphaned epic reference | WARNING | Story references a non-existent epic ID |
| 11 | Stale draft epic | INFO | Draft epic with no stories for >30 days |
| 12 | Hub documentation checks | WARNING/INFO | Missing or unfilled hub docs (VISION.md, ARCHITECTURE.md, DECISIONS.md) |
| 13 | Stale task assignment | WARNING | Task assigned to someone with no updates for >14 days |
| 14 | Malformed files in quarantine | WARNING | Files quarantined in `.project/malformed/` needing repair |
| 15 | Dependency cycle | ERROR | A cycle exists in the task/story `depends_on` graph |
| 16 | Orphaned dependency reference | WARNING | A task/story depends on an ID that doesn't exist |
| 17 | Missing implementation tasks | WARNING | Story has only test tasks and no implementation tasks — needs scoping |

Output is written to `.project/DRIFT.md` and printed to stdout.
