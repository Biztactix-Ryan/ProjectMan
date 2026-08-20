# Decisions

Architectural decision record for ProjectMan. Newest first. Each entry: context, decision, alternatives rejected, consequences.

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
- Git commands run inside `.project/` automatically target the `projectman` branch, so `pm_commit`/`pm_push` shelling out to git in the store directory may need zero changes (verified under US-PM-21, not assumed).
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
