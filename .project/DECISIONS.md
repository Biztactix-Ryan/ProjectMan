# Decisions

Architectural decision record for ProjectMan. Newest first. Each entry: context, decision, alternatives rejected, consequences.

---

<a id="adr-003"></a>

## ADR-003: PM data lives with its code — the hub is a read-only rollup (2026-09-06)

**Status:** Accepted — scoped from the 2026-09-05 audit, implemented in EPIC-PM-5 (US-PM-31, US-PM-34, US-PM-35, US-PM-36, US-PM-37).

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
