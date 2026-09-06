# Hub Mode Git Workflow

Two different things move through git in a hub, and keeping them apart is most
of what this document is for:

- **Code** — a subproject's commits, and the hub's submodule ref that points at
  one of them.
- **PM data** — each store, living on the `projectman` branch of the repo it
  describes. The hub's own store is one of these; so is every
  `projects/{name}/.project`.

ProjectMan moves PM data, one store at a time. It never moves code between
repos, and it never commits or pushes inside a subproject on your behalf.

## Code: Getting a Subproject Commit Into the Hub

The hub repo tracks a specific commit per subproject via git submodule refs, so
getting work into the hub is two moves: land the commit in the subproject, then
advance the hub's ref to it.

```
Developer         Subproject Repo         Hub Repo
─────────         ──────────────         ────────

1. Commit         main (updated)
   └─ push        ──────────────→

2. Update hub ref                        git add projects/api
                                         git commit "hub: update api to a1b2c3d"
                                         git push
```

ProjectMan does not manage how a subproject's commits get onto its tracked
branch — direct pushes, pull requests and review are entirely your team's
choice, and ProjectMan neither creates nor inspects them. Step 2 is yours too:
stage and commit the submodule ref in the hub, then `git push` it. ProjectMan
*reports* what each subproject's ref says (`projectman sync`,
`projectman git-status`); it does not advance refs across repos for you.

When a hub push is rejected because the remote has moved on, fetch and rebase
yourself, then push again:

```bash
cd hub-root
git fetch origin main
git rebase origin/main
# edit the conflicting files (for a submodule ref, `git checkout` the commit
# you actually want, then `git add projects/<name>`)
git rebase --continue
git push
```

For a submodule ref conflict, decide deliberately which commit the hub should
point at. The two sides are opaque SHAs and git has no way to merge them — if
they are genuinely different work, merge the *subproject* branches first and
point the hub at the merge result, rather than picking one side and silently
dropping the other.

## PM Data: Commit and Push One Store

`pm_commit` and `pm_push` — and their CLI twins `projectman commit` and
`projectman push` — act on exactly **one** store, named by `prefix`. Omit the
prefix and it is the hub's own store.

```bash
# The hub's own store
projectman commit
projectman push

# One subproject's store, inside that subproject's own repo
projectman commit --prefix API
projectman push --prefix API
```

```
pm_commit(prefix="API")
pm_push(prefix="API")
```

Git runs **inside the store directory**, so the commit lands on the branch that
owns it: `projectman` for a worktree store, which every subproject store is.
`pm_push` sends that one branch to that repo's own `origin` and nothing else.
An unknown prefix is an error listing the prefixes the hub knows; `pm_commit`
with nothing staged is an expected negative (`nothing_to_commit`), not a
failure.

There is no hub-wide commit or push. A nightly job that wants every project
covered loops over the prefixes — see [cron.md](cron.md).

## Sync: The One Hub-Wide Verb

```bash
projectman sync
```

Two passes, in this order:

1. a fast-forward `git pull` in every checked-out submodule, skipping a dirty or
   diverged one with a note rather than touching it;
2. a re-attach of every registered project whose `projects/{name}/.project`
   worktree has gone — a fresh submodule clone, a removed worktree — by mounting
   that submodule's `projectman` branch, or creating and mounting it when the
   branch does not exist yet.

That second pass is the only write ProjectMan makes inside a subproject. Every
line of the report names the project it concerns, and one unfixable subproject
never aborts the rest.

## Reading the State: `pm_git_status`

`pm_git_status` (CLI: `projectman git-status`) is a read-only rollup, one row
per registered project, in registration order. Each row describes that
project's **store** — `projects/{name}/.project` read through the same worktree
helper `pm_commit` and `pm_push` consult to decide which branch to act on:

| Column | What it is |
|---|---|
| `Project` | The registered project name |
| `Store branch` | The branch owning the store (`projectman`), or `not attached` |
| `Checkout` | The submodule's own checked-out code branch — a separate fact |
| `Dirty` | Uncommitted files **under the store**, never the code checkout's |
| `Ahead/Behind` | The store branch against its upstream |
| `Issues` | Detached store HEAD, uncommitted store changes, behind upstream, missing directory, or an unmounted store |

The JSON form adds `attached`, `prefix`, `worktree`, `upstream` and
`last_commit` (the store's last commit — the last PM change) per project, plus a
`pm_store` entry for the hub's own store. A subproject with no store mounted is
a row carrying `attached: false` and a `hint` naming the commands that fix it,
never an error. Pass a `prefix` to get the single matching row.

There is no deploy-branch alignment score: the hub reports what each
subproject's `projectman` branch says, and nothing about how that repo deploys.

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

When you update submodule refs by hand, the conventional message shape is:

```
hub: update api, web to a1b2c3d, d4e5f6g
```

### Ref Log

Every submodule ref change ProjectMan observes is recorded in the hub's
`.project/ref-log.yaml`:

```yaml
- timestamp: '2026-02-24T02:30:00+00:00'
  project: api
  old_ref: abc1234
  new_ref: def5678
  source: manual
```

`source` is free-form. ProjectMan itself writes `sync` (a ref advanced by
`projectman sync`); `manual` is the conventional value for entries written by
hand or by your own tooling.

The log is capped at 500 entries. Older entries rotate to
`ref-log.archive.yaml`.

## PM Store on Its Own Branch

A hub whose `.project/` has been moved onto the `projectman` branch by
[`projectman migrate-worktree`](../reference/cli.md#projectman-migrate-worktree)
keeps everything above unchanged for code: submodule refs still live on `main`.
What moves is the PM data:

- `pm_commit` (with or without a prefix) commits on the `projectman` branch of
  the store it names; the hub's `main` is never touched, its working tree stays
  clean, and `.project/` is never a gitlink — there is no second submodule
  pointer to dirty the parent on every task update.
- `pm_push` pushes that one store's branch and nothing else. The submodule-ref
  commits on the hub's `main` are yours to push.
- `pm_git_status` reports the hub's store separately (`pm_store`: branch,
  worktree flag, dirty count, ahead/behind) so a dirty store is not read as a
  dirty hub.

Every subproject store is already in this shape, mounted by
`projectman add-project`, `projectman sync` or `projectman migrate-hub`.

The full list of edges — `git clean -ffdx`, fresh clones, public visibility — is
in [Living with the projectman worktree](../reference/cli.md#living-with-the-projectman-worktree).

## MCP Tools

| Tool | Description |
|---|---|
| `pm_commit` | Commit one store's `.project/` changes (`prefix`: the project, or the hub's own store) |
| `pm_push` | Push the branch that owns one store (`prefix`: the project, or the hub's own store) |
| `pm_git_status` | Per-project store branch, checkout branch, dirty state, ahead/behind, plus the hub's own store |

The hub-wide git orchestration this document used to describe was removed in
September 2026; [setup.md's History section](setup.md#history-the-design-this-replaced)
says what it was and why.
