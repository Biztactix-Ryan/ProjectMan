# Decisions

Architectural decision record for ProjectMan. Newest first. Each entry: context, decision, alternatives rejected, consequences.

---

<a id="adr-006"></a>

## ADR-006: The plugin is the repo root and launches its own server with `uv run` (2026-10-07)

**Status:** Accepted (2026-10-07) — the outcome of the US-PM-55 spike (run
orch-2026-10-07-fb10). Findings are from US-PM-55-5 and the measurements from US-PM-55-6;
both are in their tasks' run logs. US-PM-56-7 builds the plugin on this record. Nothing here
changes [ADR-001](#adr-001) (the store layout) or [ADR-004](#adr-004) (single-project scope).

**Context.** Today the MCP server is a pipx install (`projectman serve`), and the skills and
hooks come from the repo through `projectman refresh-skills`. These are two install steps on
two schedules, and they drift: v0.11.0 was tagged on 2026-09-17 while the pipx install here
was still 0.9.2. The spike asked whether a Claude Code plugin can carry the server itself, so
that installing or updating the plugin also installs or updates the server. Measured with
Claude Code 2.1.292, uv 0.11.32 and system CPython 3.12.3 on a fast wired link:

- **The task's literal commands fail.** `uvx --from ${CLAUDE_PLUGIN_ROOT} projectman[all] serve`
  fails because the extra belongs on the `--from` spec. `uv run --project ${CLAUDE_PLUGIN_ROOT}
  projectman serve` fails with "MCP extras not installed" because `uv run` syncs without
  extras. Two forms work, and both list all 42 tools:
  - (A) `uvx --from ${CLAUDE_PLUGIN_ROOT}[all] projectman serve`
  - (B) `uv run --project ${CLAUDE_PLUGIN_ROOT} --extra all projectman serve`
- **A plugin in a subfolder carries no Python source.** For a git-installed plugin at
  `./subrepo/plugin` (and for a `git-subdir` source), the plugin cache holds only
  `.claude-plugin/` and `.mcp.json` (20K). There is no `src/`, no `pyproject.toml` and no
  parent dir, so the server failed. A plugin at the repo root (`"source": "./"`, tested as
  `pmself`) or a `url` source gets the whole tracked tree (about 5.2M, no `uv.lock`) and
  connects. A local directory marketplace hides this, because it runs the plugin from the
  source dir, so `${CLAUDE_PLUGIN_ROOT}/..` appears to work there.
- **Warm start matches pipx** (spawn to `tools/list` reply, median of 7): pipx 0.656 s,
  (A) 0.684 s, (B) 0.666 s.
- **Cold start is 3.58 s for (A) and 3.87 s for (B)**, with an empty uv cache and about 265 MB
  of `[all]` wheels downloaded. That is a best case on a fast link. A plugin update with a
  warm cache takes 1.89-1.97 s for (A) and 1.81-1.83 s for (B).
- **The first session after a cold install has no projectman tools.** Claude Code starts
  plugin MCP servers fully async and `claude -p` does not wait. A cold build misses the init
  event (status `pending`) and the tools are absent for that session. The next session
  connects. The per-server connect timeout is 30 s.
- **With no uv on PATH the server fails silently.** Both forms hit ENOENT at once. Claude
  Code marks the server `failed`, the session runs normally, and the only trace is in the
  debug log. There is no fallback and no prompt.
- **Offline after a first install, only (B) works.** Once uv's cached index metadata is older
  than about 10 minutes, (A) re-resolves against PyPI on every start. With no network it
  fails in about 5.5 s, and on a hanging network (captive portal, dead wifi) after 48 s,
  which is past Claude Code's 30 s timeout. (B), with its `.venv` and `uv.lock` already
  present, started in 0.66 s in every offline case, as pipx does. Only `UV_OFFLINE=1` rescues
  (A), and putting that in `.mcp.json` would break the cold install.
- **Both forms need the network on a plugin update and on a cold install.** A new plugin
  version is a new root, so (A) rebuilds the package and (B) rebuilds the `.venv`. With stale
  metadata and no network both failed (4.4-5.3 s, or about 47 s on a hanging network). A cold
  install offline fails for both, and (B) leaves an empty `.venv` behind.
- **(B) writes into the plugin cache dir.** It creates a 243 MB `.venv` and a `uv.lock` in
  `${CLAUDE_PLUGIN_ROOT}`. `uv.lock` is gitignored in the repo, so an installed plugin
  arrives without one and resolves fresh. (A) writes only to the uv cache.

**Decision.** The plugin carries and launches its own server. pipx stops being the install
path.

1. **The plugin root is the repo root.** `.claude-plugin/plugin.json` and
   `.claude-plugin/marketplace.json` sit at the top of the repo, and the marketplace entry is
   `"source": "./"`. A subfolder plugin is ruled out by the cache finding above. A `url` or
   github source pointing at the same repo is equivalent and stays available to other
   marketplaces.
2. **The launch command is (B).** `.mcp.json` runs
   `uv run --project ${CLAUDE_PLUGIN_ROOT} --extra all projectman serve`. It is the only form
   that starts offline once installed, which is the property pipx gives today. On a working
   network it starts within 10 ms of pipx.
3. **`uv.lock` is committed.** It stops being gitignored, so every installed plugin resolves
   the same versions that were tested, instead of whatever PyPI serves on the day of install.
4. **The server version is the plugin version.** The server runs from the plugin's own
   source, so there is no separate pin to keep in step. `plugin.json`'s `version` is set from
   `pyproject.toml`'s at release time, and a test fails the build when the two differ.
   Updating the plugin updates the server, and the 0.9.2-vs-0.11.0 kind of drift cannot
   happen on this path.
5. **A plugin SessionStart hook handles the two silent failures.**
   - **uv check.** If `uv` is not on PATH, the hook prints one line saying the projectman
     tools need uv and how to install it, then exits 0. The session still starts.
   - **Warm-up.** When `${CLAUDE_PLUGIN_ROOT}/.venv` is missing (a cold install or a plugin
     update), the hook runs `uv sync --project ${CLAUDE_PLUGIN_ROOT} --extra all` and reports
     the result: "server ready" or "server is building, tools appear next session". If the
     sync fails, for example offline, it says so instead of leaving a quiet `failed`. When the
     `.venv` exists the hook does nothing, so a warm start costs nothing extra.

**Alternatives rejected.**

- *(A) `uvx --from ${CLAUDE_PLUGIN_ROOT}[all]`.* Rejected on the offline result. It is cleaner
  (nothing written into the plugin root, no lockfile), but it fails offline as soon as the
  index metadata is 10 minutes old, and on a hanging network it fails after 48 s, past the
  connect timeout. A laptop on a train would lose its backlog tools for no reason, even with
  every wheel already cached.
- *Keep pipx and have the plugin pin to a compatible server.* The plugin would ship only
  skills and hooks, and a SessionStart hook would compare `projectman --version` with the
  plugin's and warn on a mismatch. Rejected: it keeps the two install steps and only detects
  drift instead of removing it. A warning that asks for `pipx install --force` and
  `refresh-skills` is the current manual recipe, restated. pipx's real advantages (no uv
  needed at runtime, offline starts) are matched by (B) plus the uv check.
- *A plugin in a subfolder (`plugin/`) launching from `${CLAUDE_PLUGIN_ROOT}/..`.* Rejected:
  a git-installed plugin's cache has no parent dir and no source, so the server cannot start.
  It only looks like it works from a local directory marketplace.
- *Move or vendor the Python package into a plugin subfolder.* Rejected: it moves `src/` and
  `pyproject.toml` (packaging, tests, CI, the PyPI layout) to satisfy the plugin cache, when a
  root plugin needs no move at all.
- *Put `UV_OFFLINE=1` in `.mcp.json` to rescue (A).* Rejected: a cold install would then fail
  every time, because there is nothing in the cache to run offline.

**Consequences and known edges.**

- **uv is a hard prerequisite.** pipx needed uv only to install, not at runtime. The plugin
  needs it on every start. The SessionStart uv check turns a silent `failed` into a stated
  requirement, but it cannot install uv. The install docs must say so first.
- **The first session after an install or update may still lack the tools.** The warm-up
  sync and the async server start can run at the same time, and a cold build (3.6-3.9 s
  measured, longer on a slower link) can outlast the init event either way. The hook's
  message makes the gap visible ("tools appear next session"), but it does not close it.
  Whether the hook can finish before the server spawns, and whether uv's `.venv` lock
  serialises the two processes cleanly, is for US-PM-56-7 to verify.
- **Plugin updates need the network.** Each new plugin version is a new root with no
  `.venv`, so the first start after an update must reach PyPI unless the metadata is fresh.
  A committed `uv.lock` should let uv skip resolution on update, but that was not measured
  offline in the spike. Offline update remains a known failure, and the hook reports it.
- **The plugin cache grows by about 243 MB per installed version.** The `.venv` lives in the
  version's cache dir, beside the wheels in the uv cache (about 265 MB, shared across
  versions). Old versions' dirs, and their `.venv`, go when Claude Code prunes them.
- **The whole tracked tree ships as the plugin**: tests, docs, `.github` and `.claude`
  included, about 5.2M. That is acceptable at this size. Trimming it is a packaging question
  (a `url` source on a release branch, say), not a reason for a subfolder plugin.
- **Tool names change.** Plugin servers are namespaced `mcp__plugin_<plugin>_<server>__*`,
  not `mcp__projectman__*`. Skills, agents and allowlists that name tools need updating, and
  a user with both the plugin and the old pipx `mcp__projectman__` server would see every
  tool twice. The migration note removes the pipx MCP entry when the plugin is installed.
- **pipx is not withdrawn.** The PyPI package and `projectman serve` stay for users who run
  ProjectMan outside a Claude Code plugin, for the CLI, and for the web UI. pipx just stops
  being the way Claude Code gets the server.

---

<a id="adr-005"></a>

## ADR-005: Each orchestrated task runs in its own worktree and commits on its own branch (2026-09-09)

**Status:** Accepted — revises the *stage-only model* recorded in
[`docs/reference/orchestrate-design.md`](../docs/reference/orchestrate-design.md), whose
"no commits, no pushes, no branches, no worktrees" rule this supersedes on its isolation and
commit halves; the no-push half is kept and restated below. [ADR-004](#adr-004) stays in
force — ProjectMan is still a single-project tool, and nothing here adds a second store, a
second repo or a registry. Decided 2026-09-09, carried out in EPIC-PM-7 (US-PM-51).

**Context.** The stage-only model chose one shared checkout because sequential dispatch plus
"no commits" meant nothing needed separating: exactly one worker was editing exactly one
tree at a time. Two things have since made that the weak part of the loop.

- **The boundary between two tasks was a guess.** With one tree, the orchestrator told this
  worker's edits from the ones already there with a pre-task `git status --short` snapshot
  and an md5 list of the files the task was forbidden to touch. Both are heuristics over a
  shared mutable directory, and both cost orchestrator context on every dispatch (measured
  2026-09-09: validation was the largest single bucket of the 7–9k tokens a task added).
- **It is the thing blocking parallel lanes.** The store has had compare-and-swap claiming
  since ADR-001's successors; what stopped a second worker was never the claim, it was that
  two agents editing one unbranched checkout cannot be separated afterwards. The Agent tool
  already offers `isolation: worktree`, so the isolation the model said did not exist is
  available for the asking.

**Decision.** Each orchestrated task runs in its own git worktree and commits on its own
branch.

1. **A worktree and a branch per task.** Every dispatch gets its own worktree on branch
   `orch/<run-id>/<task-id>`, cut from the run branch.
2. **The run branch is cut from `HEAD` at pre-flight.** `orch/<run-id>` is the run's trunk;
   task branches start from it and are merged back onto it.
3. **The worker commits its own code, on its own branch, and only code.** The commit is the
   worker's last act and its report names the branch. The `.project` store is never part of
   it.
4. **The orchestrator merges accepted branches onto the run branch.** Fast-forward where it
   can, a merge commit where it cannot. A branch is merged when — and only when —
   `pm_accept` takes the task.
5. **Nothing is pushed.** No `git push`, no `pm_push`, by the orchestrator or by a worker.
   Every branch this run creates is local.
6. **The `.project` store is never committed by a run.** No `pm_commit`. Store state is left
   for the human, exactly as before.
7. **The worker safety rules survive unchanged inside the worktree.** No `git checkout`,
   `git restore`, `git stash`, `git reset` or `git clean`; no `pm_create_*` or Store write
   outside a `tmp_path` fixture; tracked files are edited directly.

**Alternatives rejected.**

- *Keep the shared tree with snapshots and md5 lists.* Rejected: it is the status quo whose
  cost is stated above. A snapshot proves something changed, never who changed it, and it
  can only ever be checked after the damage.
- *One branch for the whole run, no per-task branch.* Rejected: it isolates the run from the
  user's tree but not the tasks from each other, which is the separation the story is for. A
  rejected task could not then be dropped without unpicking commits around it.
- *Push the task branches.* Rejected: a run that pushes makes a bad sprint expensive again —
  the failure mode the stage-only model was built to avoid. Publishing is the user's call,
  taken after reading the run branch.
- *Commit the `.project` store on the run branch too.* Rejected: the store is a worktree of
  the `projectman` branch (ADR-001), on its own history and its own cadence; folding it into
  a code branch would put backlog churn in a code merge and make a declined run also a lost
  run record.
- *Let each worker branch from `HEAD` instead of the run branch.* Rejected: a dependent task
  would then start without its dependency's work and re-implement or conflict with it. The
  merge point is what makes the ordering meaningful.

**Consequences and known edges.**

- **The run's product is a run branch to review and merge, not a diff to read.** The user
  reviews `orch/<run-id>` — per-task commits, with their branch names — and merges, rebases
  or deletes it. `git diff` against the working tree is no longer the artefact; the branch
  is. A rejected sprint costs one branch deletion.
- **A worker starts from the run branch and cannot see unmerged work.** Isolation cuts both
  ways: a task whose dependency has not yet been accepted and merged would begin from a tree
  without it. Dependent tasks therefore wait for the merge, and the accept-then-merge step
  is ordering-critical rather than bookkeeping.
- **The worktree carries no `.project`, so all store access is via the MCP tools.** The store
  is gitignored on the code branch, so it is simply absent from a fresh worktree. Workers
  read and write the backlog through `pm_grab`, `pm_update` and friends, which act on the
  primary checkout's store — no worker ever opens `.project` files by path.
- **A parked task leaves its branch behind for a human.** Parking does not merge and does not
  delete: the branch stays as the record of the attempt, named for the task and the run, for
  someone to read, salvage or drop. The final report lists branches merged, unmerged and
  abandoned so the leftovers are discoverable.
- **Worktrees are a resource with a lifetime.** They are created per task and removed when
  the run ends; a crashed run leaves worktrees and branches whose names carry the run id,
  which is what makes them identifiable afterwards.
- **Sequential dispatch is unchanged by this ADR.** It removes the obstacle to lanes; it does
  not open them. Parallelism is a later decision that has to answer how two lanes share one
  merge point.

---

<a id="adr-004"></a>

## ADR-004: Hub mode is removed — ProjectMan is a single-project tool (2026-09-08)

**Status:** Accepted — supersedes [ADR-003](#adr-003). Decided 2026-09-08 and carried out in EPIC-PM-6 (US-PM-44, US-PM-45, US-PM-46, US-PM-47).

**Context.** ADR-003 (2026-09-06) answered the 2026-09-05 audit by *redesigning* hub mode rather than removing it. The redesign shipped in full — 59 points across Sprints 10 and 11 — and then the measurements that motivated it were re-read against what the redesign actually bought:

- **9 hub or changeset uses in 484 sessions.** The 2026-09-05 usage audit counted every session in the corpus and found the multi-project surface used nine times. That is not a feature with light adoption; it is a feature with no adoption, carrying the largest share of the package's conditional branches.
- **71 of the 97 error sites had zero observed traffic, mostly hub and web** (`docs/reference/error-paths-inventory.md`, now marked as history). Three quarters of the error handling in the package guarded paths nobody walked, and the hub was the bulk of it.
- **The ADR-003 redesign gained no user.** Six weeks of the audit's evidence said the mode was unused; two sprints of work made the unused mode better. Nobody attached a project to a hub after it landed, and no `projectman migrate-hub` was ever run against a real hub. Rebuilding a thing before checking whether anyone wants it is the mistake ADR-003 made, and it does not get corrected by rebuilding it again.
- **US-PRJ-34 (parallel rollup) was archived as moot on 2026-09-08.** It was the last piece of hub work still in the backlog; nothing in it made sense once the mode it optimised had no traffic.

The decision is therefore not "the redesign was wrong". ADR-003's four moves were the right shape *given* that hub mode had to exist. The premise was the defect: hub mode did not have to exist.

**Decision.** ProjectMan is a single-project tool.

1. **Single-project mode only.** The hub package, hub-only tools, hub CLI commands (`add-project`, `set-branch`, `migrate-hub`, `sync`), the `projects/{name}/.project` layout, hub rollups and hub docs all leave the package. One store, one repo, no registry.
2. **IDs keep their prefix.** `US-PRJ-1` stays `US-PRJ-1`. The prefix is part of the ID's identity and appears in filenames, branch history, run logs and every doc — dropping it would be a rename of every artefact in every existing project for no gain now that the prefix addresses nothing.
3. **ADR-001's orphan-branch storage is unchanged.** `.project` remains a worktree of the repo's own `projectman` branch. That design was never hub-specific and is untouched here.
4. **Removed in EPIC-PM-6** — US-PM-44 (the hub package and its tools), US-PM-45 (CLI and web), US-PM-46 (config, templates and scaffolding), US-PM-47 (docs, templates and this record).

**Alternatives rejected.**

- *Keep hub mode behind an off-by-default flag.* Rejected: a flag does not remove the branches, the tests, the docs or the error paths — it only removes the mode from the default answer while every cost stays. The nine uses in 484 sessions do not pay for a second code path, gated or not.
- *Keep the ADR-003 redesign and wait for adoption.* Rejected: this is what the last two sprints were. The redesign has been available since Sprint 11 and its adoption is zero. Waiting longer only spends more maintenance on the same evidence.
- *Ship a migration that folds a hub into N single projects.* Rejected as unbuildable-for-nobody: writing, testing and supporting a one-shot converter costs more than the hubs it would convert, of which the observed count is zero outside this repo's own experiments. The path forward is stated in the consequences instead, and is short enough to follow by hand.
- *Drop the ID prefix along with the hub.* Rejected: see decision 2. The prefix's *addressing* role is gone; its *naming* role is not, and a mass rename would break every external reference to an ID for cosmetic tidiness.
- *Leave the hub code in the tree, undocumented and untested.* Rejected: unexercised code that no doc describes is the worst of both — it still breaks the build, still shows up in every refactor, and now has no statement of intent to check it against.

**Consequences and known edges.**

- **Existing hubs keep working on 0.8.x.** Nothing is retracted from a released version; a hub that works today keeps working on the version it is pinned to. Hub mode is absent from 0.9.0 onward.
- **A legacy `config.yaml` still loads.** `hub:` and `projects:` keys are stripped at load with a single line on stderr (`projectman: ignoring retired config key(s) … (hub mode was removed)`; `LEGACY_CONFIG_KEYS` in `src/projectman/config.py`), so a checkout predating the removal opens rather than erroring. The keys are ignored, not migrated.
- **No migration path is offered.** There is no `migrate-hub` and no replacement for it.
- **Each former subproject works as a single project on 0.9.0.** Its store is already a `projectman` branch of its own repo (ADR-003's decision 1, which shipped), so a subproject needs no conversion — it is a single project already. What is lost is the hub-level rollup across them, and hub-level epics, which have no single-project equivalent.
- **ADR-003 stands as the record of what was removed.** It is superseded, not deleted; its context and alternatives explain the design that EPIC-PM-6 took out.
- **The two reference documents that inventoried hub code are kept as history** (`docs/reference/error-paths-inventory.md`, `docs/reference/readiness-warnings-determination.md`), each marked with a History blockquote naming this ADR's epic. `CHANGELOG.md` and this file are the other two places hub mode may still be named; every other page is swept by `tests/test_docs_after_subtraction.py`.

---

<a id="adr-003"></a>

## ADR-003: PM data lives with its code — the hub is a read-only rollup (2026-09-06)

**Status:** Superseded by [ADR-004](#adr-004) (2026-09-08) — hub mode was removed outright in EPIC-PM-6. Originally Accepted — scoped from the 2026-09-05 audit, implemented in EPIC-PM-5 (US-PM-31, US-PM-34, US-PM-35, US-PM-36, US-PM-37).

**Context.** The 2026-09-05 audit of hub mode (recorded in the EPIC-PM-5 body, and at length in the five `docs/hub-mode` audit documents now folded into a History section of `setup.md`) found four structural problems, not a list of bugs:

- **Per-project data was far from its code.** Each subproject's backlog lived in the hub's own store under `.project/projects/{name}/`. A backlog for `my-api` that exists only in a hub is invisible to anyone cloning `my-api`, and is lost outright if the hub is rebuilt.
- **Every task edit was a hub commit.** Five projects updating tasks all day produced five streams of unrelated commits on one repo, with the `index.yaml` merge conflicts that implies.
- **An optional `project` argument sat on 42 tools** restating what the ID prefix already said. `pm_get("US-API-3", project="api")` is the prefix twice, and the two could disagree.
- **Docs promised cross-project epics the store did not deliver.** Epics were stored per store, so a "cross-repo" epic could not roll up across repos at all.
- **`hub/registry.py` had grown to roughly 2,700 lines** driving git *inside repositories the hub did not own* — a hub-wide push that walked every dirty subproject, a rebuild-everything repair command, and a branch-alignment check.

**Decision.** Four moves, taken together:

1. **PM data lives with its code.** Each subproject's store is `projects/{name}/.project`, mounted as a worktree of *that repo's own* `projectman` branch — ADR-001's design applied per submodule (US-PM-31). The hub keeps its own store for hub-level docs, epics and dashboards.
2. **The ID prefix names the store.** The `project` argument is gone from every tool; the prefix inside an ID *is* the address, and the few ID-less verbs take an optional `prefix` (US-PM-34).
3. **Epics are hub-level only** and roll up linked stories from every attached subproject, with `by_project` in the rollup and a `not_attached` list when a store is unmounted. `projectman migrate-hub` moves legacy per-store epics up (US-PM-36).
4. **The hub is a read-only rollup.** The coordinated push, the repair command and the branch validator left the package entirely; `pm_commit` and `pm_push` act on exactly one store named by prefix, running git inside that store's own repo, and `projectman sync` — pull every submodule, re-attach any missing store — is the one hub-wide git verb (US-PM-35).

**Alternatives rejected.**

- *Keep per-project data in the hub store under `.project/projects/{name}`, and fix the ergonomics around it.* This is the design being replaced. It cannot be fixed by ergonomics: the data's distance from its code is the defect, and every symptom above (invisible backlogs, hub-commit churn, `index.yaml` conflicts) follows from the location, not from the interface over it.
- *A private sibling repo per project — the `<repo>-pm` variant ADR-001 documents.* It solves separate permissions well, and stays available for a project that needs it. Rejected as the default because it doubles the repository count for every subproject, and a hub that must clone a second repo per project to read a backlog is strictly more fragile than one reading a branch of a repo it already has as a submodule.
- *Keep an optional `project` argument alongside the prefix, for compatibility.* Rejected: two addresses for one store is the bug, not the migration path. A caller passing both invites a silent disagreement the server must arbitrate, and every tool signature and doc page keeps carrying an argument that never changes an answer. An ID with an unknown prefix now returns a coded `not_found` listing the prefixes that exist — a better answer than a redundant parameter.
- *Per-store epics with a hub-level index over them.* Rejected: an index is a second source of truth that drifts. A story linked to an epic in another store would need its link validated against a file the store cannot see, and the rollup would be as stale as the last index write. Epics at hub level make `epic_id` checkable before it is written.
- *Keep the coordinated push as an opt-in flag.* Rejected: opt-in or not, it is the hub committing and pushing inside repos it does not own, and it was the source of the retry, rebase and submodule-ref-conflict machinery that made up most of those 2,700 lines. It had zero observed traffic in the error-path corpus. `projectman sync` pulls; pushing a subproject is that subproject's own `pm_push`.

**Consequences and known edges.**

- **Single-project mode is unchanged.** One store, no prefix, no hub — every path above is hub-only.
- **Hub reads never fail on an unattached store.** A registered project whose worktree is missing shows up as a `not_attached` row with a hint (`projectman sync`), so a partial rollup says it is partial instead of silently omitting a repo.
- **A hub built before this change needs `projectman migrate-hub` once.** It moves each `.project/projects/{name}` into that subproject's own `projectman` branch, lifts per-store epics to the hub, and leaves the hub's commit and submodule pointers for a human to push.
- **Advancing submodule refs stays manual.** ProjectMan reports what each subproject's ref says; it does not move code between repos.
- **The web API's `?project=` query parameter remains** (`get_store` in `src/projectman/web/routes/api.py`). It is an HTTP route parameter, not a tool argument, and is out of scope here; it goes in the web layer's own cleanup.
- **Closed (US-PM-39, 2026-09-07):** that cleanup happened. The web layer now routes by prefix like every MCP tool — ID-taking routes resolve the store from the ID's prefix, ID-less routes take an optional `?prefix=`, and `?project=` is gone from `src/projectman/web/routes/api.py`, so the remaining-parameter caveat above is closed and no argument in the package addresses a store by project name.

---

## ADR-002: An archive is identified only by a positive archive signal, never by a status footprint (2026-08-20)

**Status:** Accepted — decided in US-PM-17-6, binding on US-PM-17-7 (implementation), US-PM-17-1..-5 and -8 (tests), and US-PM-17-9 (the live candidates in this repo). The `migrations.py` module docstring is the normative statement; this ADR records why.

**Context.** `find_archived_as_done` infers that a done task is a pre-US-PM-16 archive from a footprint: its last status event moved it `todo`/`blocked` -> `done` and changed only `status`. The old `archive` really was `update(task_id, status="done")`, so that footprint is genuine — but closing a task in one write produces the identical bytes, and closing straight from `todo` is routine (`pm_update(id, status="done")`, `pm_done_next` on an ungrabbed task). `migrate_archived_as_done(apply=True)` reverts candidates to their prior status, so a false positive destroys the record of delivered work. The docstring asserted this could not happen.

Measured against this repo's own data: six tasks match the footprint, carrying byte-identical events (same `changes` payload, same `source: cli`, same actor). Two (`US-PM-1-1`, `US-PM-2-1`) were disposed of two seconds after their parent story's acceptance criteria were rewritten; four (`US-PRJ-29-2`..`-5`) were closed by a `/pm` audit pass with run-log notes reading "Closed during audit: AC placeholder task". Nothing in the data separates the classes — and both classes turn out to be the same kind of event.

**Decision.** A write requires a positive archive signal: an activity event for the task whose `changes` explicitly contains `archived` with `after` true (or a future `event_type: "archive"`), not later cleared. A candidate is a task that carries such a signal but has lost the flag on disk — a dropped write, a hand-edited or restored frontmatter, a bad merge — where the log is authoritative about an event it actually recorded.

Applying sets `archived: true`. It restores a `status` only when the signal event itself recorded a status change; otherwise status is untouched. This yields the invariant: **the migration never moves a task out of `done` on inferred evidence.** The flag alone fixes the metrics, because `models.is_archived` is what completion, burndown and velocity consult. Tasks matching the old footprint are reported under `needs_review` and never written.

**Alternatives rejected.**
- *Narrow the footprint using evidence genuine completion tends to leave (run log, assignee, points).* Rejected on this repo's data. The run-log signal is inverted — the four tasks that must not be migrated have run logs, the two older ones do not — and its absence proves nothing, since 210 of 272 done tasks have no run log at all (a status write without a `note` never creates one). All six have `assignee: null` and `points: null`. No discriminator exists, and any such rule would still write on ambiguous evidence.
- *Report-only for the ambiguous shape, with explicit per-task confirmation to write.* Rejected as the primary mechanism: it relocates a provably unsupported decision to a human who has no better evidence than the tool does, and a per-task prompt invites rubber-stamping. Its reporting half is adopted (`needs_review`); its write half is not.

**Consequences and known edges.**
- Every pre-signal archive becomes unrecoverable by machine — from any prior status, not just `in-progress`. This extends the stance the module already took for `in-progress -> done` to the rest of the space, honestly.
- The manual remedy is to archive by hand — the `pm_archive` MCP tool, or `Store.archive(task_id)` directly; no CLI subcommand exposes it today. Either sets the flag and leaves `status` alone. Honest record, correct metrics, no claim the work was never done.
- The four live false positives in this repo stop being candidates automatically. The two older tasks moved to `needs_review`, and US-PM-17-9 applied the manual remedy above to both: `Store.archive` set `archived: true` on US-PM-1-1 and US-PM-2-1 with `status: done` untouched, preserving the metrics correction US-PM-16 delivered. Both now carry a positive archive signal, so the live report reads 0 candidates / 4 `needs_review` (the US-PRJ-29 tasks, which are genuinely complete and must stay `done`).
- The write path narrows to log/disk disagreement. That class is real but rare, so an applied run will usually be a no-op — which is the correct outcome, not a regression.
- `EventType.archive` exists in `models.py` but nothing emits it; today's signal is the `archived` key in an `update` event's `changes`. Emitting the dedicated event later would strengthen the signal without changing this contract.

---

## ADR-001: Store PM data on an orphan branch mounted as a worktree (2026-08-20)

**Status:** Accepted — implementation tracked in EPIC-PM-3 (US-PM-19/20/21).

**Context.** `.project/` lives in the repo and every task update lands as a commit on `main`, polluting code history with PM noise. Constraints: local-first must stay intact (Claude Code and the MCP server read/write plain files in the repo root), Forgejo should serve as the sync server without new services or frameworks, and code history should stay purely code.

**Decision.** Move `.project/` onto a dedicated orphan branch (`projectman`) mounted back into the repo root as a git worktree. Locally nothing changes — the files sit where they always have — but commits made inside `.project/` land on the `projectman` branch with its own history. `main` gitignores `.project/` and never sees a task update again.

Key properties:
- Git commands run inside `.project/` automatically target the `projectman` branch. **Verified under US-PM-21 (2026-09-02): the "zero changes" hope was false** — `pm_commit`/`pm_push` shelled out from the repo *root*, where `git add .project` refuses the ignored worktree path and `git status .project/` is silent. They now run inside the store (`store_git_state` in `worktree.py` is the single source of truth), and `pm_git_status` reports the store separately. Rough edges are documented in `docs/reference/cli.md` ("Living with the projectman worktree").
- Forgejo syncs, browses, renders, and backs up the branch with the same remote and permissions; Forgejo Actions can hang off it later (e.g. burndown regeneration on push).
- `git clone --single-branch` and shallow CI clones never pull PM data.
- Migration is a snapshot import by default; `git filter-repo --subdirectory-filter .project` is the history-preserving variant.

**Alternatives rejected.**
- *Branch-switching* — churns the working tree; ugly in exactly the way the worktree mount is not.
- *Git submodule for `.project/`* (including in hub mode) — the submodule pointer in `main` dirties the parent repo on every task update, recreating the noise being eliminated.
- *Forgejo wiki repo* (`<repo>.wiki.git`) — natively "with the repo but not in it" and renders in the UI, but the wiki renderer's flat naming conventions and YAML-frontmatter handling fit ProjectMan's structure poorly.

**Consequences and known edges.**
- Fresh clones need `git worktree add .project projectman` before data appears — automated via `projectman attach` and detection in `projectman init` (US-PM-20).
- `.project/` becomes ignored-but-precious; `git clean -fdx` won't recurse into the worktree without `-ff`, but users must know it is not disposable.
- PM data shares the repo, so on public repos the `projectman` branch is visible. Private-data variant: a sibling `<repo>-pm` repository cloned into `.project/` (still gitignored) — identical local ergonomics, separate permissions, at the cost of two repos per project.
- If PM state should ever surface in Forgejo's issue/project boards (Forgejo has no plugin system), the path is a one-way n8n sync from `.project` frontmatter to Forgejo issues via the API — visibility without moving the source of truth.
