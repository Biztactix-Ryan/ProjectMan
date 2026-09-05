# Hub Mode Git Workflow

This document covers the git workflow for hub mode — how changes in subprojects reach the hub's submodule refs.

## The Workflow

The hub repo tracks a specific commit per subproject via git submodule refs. Getting work into the hub is therefore two moves: land the commit in the subproject, then advance the hub's ref to it.

```
Developer         Subproject Repo         Hub Repo
─────────         ──────────────         ────────

1. Commit         main (updated)
   └─ push        ──────────────→

2. Update hub ref                        git add projects/api
                                         git commit "hub: update api to a1b2c3d"
                                         git push
```

ProjectMan does not manage how a subproject's commits get onto its tracked branch — direct pushes, pull requests and review are entirely your team's choice, and ProjectMan neither creates nor inspects them. What it automates is step 2, and the ordering that makes it safe: `projectman push` never advances a hub ref to a commit that has not been pushed to the subproject's remote.

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
4. **Push hub** — stages submodule ref updates, commits, and pushes, rebasing onto the remote if it has moved (see [Handling Conflicts](#handling-conflicts))

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

When the hub push is rejected because the remote has moved on, ProjectMan fetches and rebases, then pushes again. That handles the ordinary race — someone else's push landed between your fetch and yours — and nothing more.

### Rebase Flow

```
Push attempt       Result              Action
────────────       ──────              ──────
1st push           rejected            fetch + rebase
                   ↓
                   rebase succeeds?
                   ├─ yes → push again (up to 3 attempts)
                   └─ no  → abort the rebase, stop, report
```

### When the Rebase Conflicts

**ProjectMan never resolves a conflict for you.** Any conflicting rebase — a submodule ref both you and someone else advanced, or a `.project/` file you both edited — is aborted with `git rebase --abort`, and the push stops:

```
Hub:
  main → origin  ✗  rebase conflict — manual resolution required
```

The abort leaves the hub exactly as it was before the attempt: your commits are intact, nothing is half-rebased, and no ref has been picked for you. Resolve it yourself, then run `projectman push --scope hub` again:

```bash
cd hub-root
git fetch origin main
git rebase origin/main
# edit the conflicting files (for a submodule ref, `git checkout` the commit
# you actually want, then `git add projects/<name>`)
git rebase --continue
```

For a submodule ref conflict, decide deliberately which commit the hub should point at. The two sides are opaque SHAs and git has no way to merge them — if the two commits are genuinely different work, merge the *subproject* branches first and point the hub at the merge result, rather than picking one side and silently dropping the other.

### Retry Logic

The hub push retries up to 3 times (configurable). Each retry fetches the latest remote state and attempts a fresh rebase. A conflict ends the attempt immediately — the remaining retries are not used, because retrying cannot change the outcome.

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

### Ref Log

Every submodule ref change is recorded in `.project/ref-log.yaml`:

```yaml
- timestamp: '2026-02-24T02:30:00+00:00'
  project: api
  old_ref: abc1234
  new_ref: def5678
  source: coordinated_push
```

`source` is free-form. ProjectMan itself writes `sync` (a ref advanced by `projectman sync`) and `auto_rebase` (a ref that moved when a hub push rebased onto the remote); `coordinated_push` and `manual` are the conventional values for entries written by hand or by your own tooling.

The log is capped at 500 entries. Older entries rotate to `ref-log.archive.yaml`.

## PM Store on Its Own Branch

A hub whose `.project/` has been moved onto the `projectman` branch by [`projectman migrate-worktree`](../reference/cli.md#projectman-migrate-worktree) keeps the workflow above unchanged for code: submodule refs still live on `main` and still flow through the coordinated push. What moves is the PM data:

- `pm_commit` (any scope) commits on `projectman`; the hub's `main` is never touched, its working tree stays clean, and `.project/` is never a gitlink — there is no second submodule pointer to dirty the parent on every task update.
- `pm_push --scope hub` pushes `main` first (submodule ref updates) and then `projectman`. The result carries a `pm_store` entry naming the branch. A failed store push fails the call.
- `pm_git_status` reports the store separately (`pm_store`: branch, worktree flag, dirty count, ahead/behind) so a dirty store is not read as a dirty hub.

The full list of edges — `git clean -ffdx`, fresh clones, public visibility — is in [Living with the projectman worktree](../reference/cli.md#living-with-the-projectman-worktree).

## MCP Tools

These tools are available via the MCP server for agent-driven workflows:

| Tool | Description |
|---|---|
| `pm_commit` | Commit `.project/` changes (scope: hub, project:name, all) |
| `pm_push` | Push `.project/` changes and, in hub mode, coordinate the submodule push |
| `pm_git_status` | Per-project branch, alignment, dirty state, ahead/behind, and the PM store |
| `pm_push_all` | Coordinated push with optional dry run and project filter (break-glass — needs `tools.maintenance: true`) |
