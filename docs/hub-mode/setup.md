# Hub Mode Setup

A hub is a repo that carries several projects as git submodules under
`projects/` and keeps a system-wide view over them. Each project's PM data
lives **inside that project's own repo**, at `projects/{name}/.project` — a git
worktree of that submodule's `projectman` branch. The hub's own `.project/`
holds the hub's context documents, its epics, its sprints and the generated
dashboards, and reads everything else through the stores the submodules bring
with them.

## Initialize a Hub

```bash
mkdir my-hub && cd my-hub
git init
projectman init --name "My Hub" --prefix HUB --hub
```

## Add Projects

```bash
projectman add-project my-api https://github.com/user/my-api.git
projectman add-project my-frontend https://github.com/user/my-frontend.git --branch develop
```

Each project is added as a git submodule under `projects/`.
[`projectman add-project`](../reference/cli.md#projectman-add-project) then does
three things, in this order:

1. `git submodule add <url> projects/<name>` (with `--branch` when you gave one).
2. **Mounts the subproject's store, attach-or-create.** If the clone brought
   `origin/projectman` down with it, that branch *is* the store and is simply
   attached at `projects/{name}/.project`. If there is no such branch, the
   orphan branch is created, mounted, scaffolded with a fresh store and
   committed. The mount is added to the submodule's `.gitignore`, so the
   worktree is not untracked noise in that checkout.
3. **Registers the project in the hub's `.project/config.yaml`** — only once the
   store is actually there. If the mount fails, the name is deliberately *not*
   registered (a registered project with no store would break every reader that
   walks the project list) and the message tells you how to remove the
   half-added submodule and try again.

The output says which of the two mount paths ran, and — for a freshly created
branch — the `git -C projects/<name>/.project push -u origin projectman` that
publishes it.

## Structure

```
my-hub/
├── .project/                # the hub's own store
│   ├── config.yaml          #   hub: true, and the registered project names
│   ├── VISION.md
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── PROJECT.md
│   ├── INFRASTRUCTURE.md
│   ├── SECURITY.md
│   ├── index.yaml
│   ├── epics/               #   epics are hub-level — see epics.md
│   ├── stories/
│   ├── tasks/
│   ├── dashboards/
│   └── roadmap/
└── projects/
    ├── my-api/              # git submodule — the my-api repo
    │   └── .project/        # my-api's PM data: a worktree of the submodule's
    │       ├── config.yaml  #   own `projectman` branch
    │       ├── stories/
    │       └── tasks/
    └── my-frontend/         # git submodule
        └── .project/        # my-frontend's PM data, likewise
```

PM data therefore travels with the code it describes: a task edit in `my-api` is
a commit on the `my-api` repo's `projectman` branch, not a commit on the hub.
The hub is a **read-only rollup** — it reads every mounted store, and it never
commits or pushes inside a repo it does not own. The one exception is
`projectman sync`, which re-mounts a store whose worktree has gone missing.

Stores are addressed by **prefix** — the `API` in `US-API-3` — everywhere in the
tool surface: `pm_status(prefix="API")`, `projectman commit --prefix API`. See
[Addressing a store](../reference/mcp-tools.md#addressing-a-store).

## Cloning a Hub

A fresh clone arrives with no store mounted anywhere, because each store lives
on a branch rather than in the tree:

```bash
git clone --recurse-submodules https://github.com/user/my-hub.git
cd my-hub

projectman attach     # mount the hub's own .project, if the hub store is on
                      # its `projectman` branch
projectman sync       # pull each submodule, then mount every subproject store
```

[`projectman sync`](../reference/cli.md#projectman-sync)'s second pass attaches
any registered project whose `projects/{name}/.project` worktree is missing —
a fresh submodule clone, a removed worktree — so it is the one command to run
after cloning. Inside a single subproject checkout on its own,
[`projectman attach`](../reference/cli.md#projectman-attach) does the same job
for that one repo. Both are idempotent: an already-mounted store is reported
and left alone.

## Migrating an Older Hub

Hubs built before this layout kept every subproject's PM data inside the hub's
own store, so every task edit anywhere became a commit on the hub repo. One
command moves them:

```bash
projectman migrate-hub --dry-run   # check the preconditions and see the plan
projectman migrate-hub             # --no-push to stay local
```

[`projectman migrate-hub`](../reference/cli.md#projectman-migrate-hub) has two
independent halves.

**The store move.** For each registered project that still has data in the hub,
it attaches the submodule's existing `projectman` branch (or creates the orphan
branch when there is none), copies the store across byte for byte, and commits
it there with a message naming where it came from. Then, once, it `git rm -r`s
the hub's copies and commits that removal on the hub. Each `projectman` branch
is pushed with `git push -u origin projectman` when the subproject has an origin
remote, unless `--no-push` is given; a push failure only warns, because the
local move is already done. The hub's own commit and its updated submodule
pointers are yours to push.

**The epics step.** Epics are hub-level (see [epics.md](epics.md)), so a second
half runs after the store move: every `epics/EPIC-{PROJECT}-N.md` left in a
subproject store is moved into the hub's `.project/epics/` under a fresh
hub-prefixed ID from the hub's own counter, and every story in *every* store
that linked to one has its `epic_id` rewritten — including a story in one
subproject that pointed at an epic living in another. Each changed store is
committed inside itself, and the old-to-new mapping is both in the commit
message and printed.

The halves are independent, so a hub whose stores already sit at
`projects/{name}/.project` gets just the epics step — `migrate-hub` is still
the command to reach for.

Every precondition is checked before the first change, so a refusal leaves
nothing half-migrated. It exits 1 having changed nothing when the hub's tree is
dirty, when an affected submodule's tree is dirty, when a mounted store the
epics step would commit in has uncommitted changes, when a submodule is not
checked out, or when a submodule's `projectman` branch already carries a store
of its own — merging two PM stores is not a call the command makes. A hub with
nothing left to move says so and exits 0, so re-running is safe.

## Hub Context Documents

During `projectman init --hub`, the hub's context documents are created in
`.project/`. Three of them carry the system-wide view:

- **VISION.md** — system-wide product vision, guiding principles, and roadmap
- **ARCHITECTURE.md** — system architecture overview and service map
- **DECISIONS.md** — architectural decision log (ADRs)

These apply across all subprojects. Update them with `pm_update_doc`:

```
pm_update_doc("vision", content="Updated vision text...")
pm_update_doc("architecture", content="Updated architecture text...")
pm_update_doc("decisions", content="New decision entry...")
```

Read them at any time with `pm_docs`:

```
pm_docs("vision")
pm_docs("architecture")
pm_docs("decisions")
```

## Loading Combined Context

`pm_context(prefix=...)` loads the hub-level vision and architecture documents
together with one project's own docs and its active epics and stories. The
project is named by its **prefix** — the `API` in `US-API-3` — not by its
directory name:

```
pm_context(prefix="API")
```

Lists are capped at 20 items each by default, with totals. Use `limit` to
adjust:

```
pm_context(prefix="API", limit=5)
```

## Git Configuration

### Auto-commit

Enable automatic commits whenever PM data changes (story/task/epic creates and
updates):

```yaml
# .project/config.yaml
auto_commit: true
```

Each `create` or `update` then stages and commits the affected `.project/` files
with a message like `pm: create US-PRJ-5` or `pm: update US-PRJ-3-1
status=done`, in the store that owns them — so a subproject's commit lands on
that subproject's `projectman` branch.

### Tracked branch per subproject

Each submodule tracks a code branch recorded in `.gitmodules`. Set it when
adding the project, or change it later:

```bash
projectman add-project my-api https://github.com/user/my-api.git --branch develop
projectman set-branch my-api main
```

`projectman sync` fast-forward pulls that branch. It is the submodule's *code*
branch and is reported separately from the store's `projectman` branch
everywhere — the two are different facts.

## Syncing

```bash
projectman sync
```

Two passes: a fast-forward `git pull` in every checked-out submodule, skipping a
dirty or diverged one with a note rather than touching it; then a re-attach of
every registered project whose store worktree is missing. It reports both —
`sync complete: N updated, N skipped, N failed, N stores attached`, a line per
project, and a `stores:` block naming what was mounted. Run it before an audit
or a dashboard regeneration.

## History: the design this replaced

Hub mode was rebuilt in September 2026 (EPIC-PM-5). The design before it worked
like this, and reading it explains commands you may find in old notes:

- **Per-project PM data lived in the hub's own store**, one subdirectory per
  project inside the hub's `.project/`. The subproject repos knew nothing about
  their own backlog.
- **Every tool took a project-name argument** to say which of those
  subdirectories to read or write. Stores are now addressed by ID prefix, and
  that argument is gone.
- **The hub orchestrated git across repos it did not own**: a hub-wide push that
  walked every dirty subproject and then pushed the hub, a rebuild-everything
  `repair` command, and a branch-alignment check. All three were removed;
  `projectman sync` is the one hub-wide verb left, and it only pulls and
  re-attaches.
- **Epics were per-store**, so a "cross-repo" epic could not roll up across
  repos at all. Epics are now hub-level.

Why it was replaced — from the audit of 2026-09-05, which the five
`docs/hub-mode` documents that used to sit here recorded at length:

1. **The data was far from its code.** A backlog for `my-api` that only exists
   in a hub is invisible to anyone cloning `my-api`, and is lost outright if the
   hub is ever rebuilt.
2. **Every task edit was a hub commit.** Five projects updating their tasks all
   day meant five streams of unrelated commits on one repo, with the merge
   conflicts on `index.yaml` that implies.
3. **`hub/registry.py` had grown to roughly 2,700 lines** driving git inside
   repositories the hub did not own — the three retired commands above — which
   is where the sharpest failure modes lived.

The decision, its alternatives and its consequences are recorded as
[ADR-003](../../.project/DECISIONS.md#adr-003) in `.project/DECISIONS.md`; the
link points at that heading's anchor. (ADR-001 in the same file records the
earlier decision to keep a store on an orphan `projectman` branch mounted as a
worktree, which is the mechanism this layout is built on.)
