# Hub Mode Git Workflow

This document covers the opinionated git workflow for hub mode — how changes flow from feature branches through PRs to the hub's submodule refs.

## The Workflow

Hub mode follows a strict flow: **feature branches → PR → merge → hub ref update**.

```
Developer         Subproject Repo         Hub Repo
─────────         ──────────────         ────────

1. Create branch  feature/add-auth
   └─ commit      ──────────────→
   └─ commit

2. Open PR        PR #42
   └─ review      ──────────────→
   └─ approve

3. Merge PR       main (updated)
                  ──────────────→

4. Update hub ref                        git add projects/api
                                         git commit "hub: update api to a1b2c3d"
                                         git push
```

Changes never go directly to `main` in subprojects. The hub repo tracks specific commits via git submodule refs, updated only after PRs merge.

## Coordinated Push

The coordinated push command orchestrates pushing multiple repos in the correct order with safety gates at every step.

### How It Works

```
projectman push --scope all
```

1. **Discover** — finds all subprojects with unpushed commits
2. **Preflight** — validates every project before anything is pushed:
   - Branch alignment (each submodule on its tracked branch)
   - Convention validation (branch naming, deploy protection)
   - Remote reachability (can reach origin)
   - Staged changes check (warns if dirty but nothing staged)
3. **Push subprojects** — pushes each subproject sequentially, stops on first failure
4. **Push hub** — stages submodule ref updates, commits, and pushes with auto-rebase

If any preflight check fails, nothing is pushed. If a subproject push fails, remaining subprojects and the hub are skipped.

### Commands

```bash
# Push all dirty subprojects + hub
projectman push --scope all

# Push specific projects only
projectman push --projects api,web

# Dry run — show what would happen
projectman push --dry-run

# Push just the hub (no subprojects)
projectman push --scope hub

# Push a single subproject
projectman push --scope project:api
```

### Push Report

A successful coordinated push produces a report like:

```
Subprojects:
  api  main → origin  a1b2c3d  ✓
  web  main → origin  d4e5f6g  ✓
Hub:
  main → origin  f8a9b0c  ✓
```

If the hub needed a rebase:

```
Hub:
  main → origin  f8a9b0c  ✓  (rebased, 1 retry)
```

## Handling Conflicts

When the hub push is rejected because the remote is ahead, ProjectMan automatically attempts a rebase.

### Auto-Rebase Flow

```
Push attempt       Result              Action
────────────       ──────              ──────
1st push           rejected            fetch + rebase
                   ↓
                   rebase succeeds?
                   ├─ yes → push again (up to 3 attempts)
                   └─ no  → classify conflict
```

### Conflict Types

**Submodule ref conflicts** — two developers updated the same submodule ref:

- ProjectMan checks if the refs are fast-forwardable using `git merge-base --is-ancestor`
- If one ref is an ancestor of the other, the newer ref wins automatically
- If the refs have diverged (neither is an ancestor), the rebase aborts with guidance:

```
Hub:
  main → origin  ✗  (diverged ref conflict)
  Suggestion: resolve the conflict in the subproject first, then retry
```

**.project/ file conflicts** — two developers edited the same PM file:

- The rebase aborts immediately
- Manual resolution is required (edit the conflicting files, then `git rebase --continue`)

### Retry Logic

The hub push retries up to 3 times (configurable). Each retry fetches the latest remote state and attempts a fresh rebase. This handles the race condition where another push lands between your fetch and push.

## Cross-Repo Changesets

Changesets group related changes across multiple subprojects into a single trackable unit. Use them when a feature spans repos (e.g., an API change that requires frontend updates).

### Lifecycle

```
1. Create          CS-HUB-1: add-auth [open]
   ↓                 api: pending
   ↓                 web: pending

2. Set refs        CS-HUB-1: add-auth [open]
   ↓                 api: pending  (ref: feature/auth)
   ↓                 web: pending  (ref: feature/auth-ui)

3. Create PRs      CS-HUB-1: add-auth [open]
   ↓                 api: open     PR #42
   ↓                 web: open     PR #18

4. PRs merge       CS-HUB-1: add-auth [partial → merged]
   ↓                 api: merged   PR #42
   ↓                 web: merged   PR #18

5. Update hub      CS-HUB-1: add-auth [merged]
                     Hub refs updated to merged commits
```

### Commands

```bash
# Create a changeset spanning api and web
projectman changeset create add-auth --projects api,web --description "Auth system"

# Set the branch ref for each project
projectman changeset add-project CS-HUB-1 api --ref feature/auth
projectman changeset add-project CS-HUB-1 web --ref feature/auth-ui

# Generate gh PR creation commands with cross-references
projectman changeset create-prs CS-HUB-1

# Check PR merge status (queries GitHub via gh CLI)
projectman changeset status CS-HUB-1

# When all PRs are merged, update hub submodule refs
projectman changeset push CS-HUB-1
```

### PR Cross-References

When you run `changeset create-prs`, each generated PR body includes cross-references to all other projects in the changeset:

```markdown
## Part of changeset: add-auth (CS-HUB-1)

### Cross-references
- api (ref: feature/auth)
- web (ref: feature/auth-ui)
```

This makes it easy for reviewers to find related PRs across repos.

### Status Tracking

The `changeset status` command queries GitHub via the `gh` CLI to check each PR's state:

| Entry Status | Meaning |
|---|---|
| `pending` | No PR created yet |
| `open` | PR exists, not yet merged |
| `merged` | PR merged |
| `closed` | PR closed without merging (needs review) |

The changeset's overall status updates automatically:
- **open** — at least one entry is pending or open
- **partial** — some merged, some still open
- **merged** — all entries merged
- **closed** — any entry closed without merging (flagged for review)

## Commit Messages

ProjectMan generates commit messages automatically based on what changed.

### PM Data Commits

When committing `.project/` changes:

| Changed files | Message |
|---|---|
| Few items (≤4) | `pm: update US-PRJ-5, US-PRJ-3-1` |
| Many items | `pm: update 3 stories, 2 tasks` |
| Config only | `pm: update config` |
| Mixed | `pm: update 2 stories, 1 epic, config` |

### Hub Ref Commits

When submodule refs are updated:

```
hub: update api, web to a1b2c3d, d4e5f6g
```

After a changeset merge:

```
hub: changeset add-auth merged — update api, web
```

### Ref Log

Every submodule ref change is recorded in `.project/ref-log.yaml`:

```yaml
- timestamp: '2026-02-24T02:30:00+00:00'
  project: api
  old_ref: abc1234
  new_ref: def5678
  source: coordinated_push
```

Sources include: `coordinated_push`, `changeset`, `sync`, `manual`, `auto_rebase`.

The log is capped at 500 entries. Older entries rotate to `ref-log.archive.yaml`.

## MCP Tools

These tools are available via the MCP server for agent-driven workflows:

| Tool | Description |
|---|---|
| `pm_commit` | Commit `.project/` changes (scope: hub, project:name, all) |
| `pm_push_all` | Coordinated push with optional dry run and project filter |
| `pm_changeset_create` | Create a cross-repo changeset |
| `pm_changeset_status` | Check PR merge status via gh CLI |
| `pm_changeset_create_prs` | Generate PR commands with cross-references |
