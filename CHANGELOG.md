# Changelog

All notable changes to ProjectMan are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Changes landed between 2026-08-19 and 2026-09-02.

### Added

- Verdict tools `pm_accept`, `pm_retry`, `pm_park`, and `pm_review`. Each fixes
  the resulting status and requires a note, so every terminal decision leaves a
  run-log entry.
- `pm_release` tool to hand a task back. It clears the assignee, sets status,
  logs the release, and can guard on the expected holder.
- Bulk tools `pm_update_many` and `pm_archive_many`, with a shared
  partial-failure contract so one bad item does not fail the whole call.
- Structured evidence on run-log entries: files touched, tests run, and which
  definition-of-done items were met or unmet. `pm_run_log` can filter on it and
  audit warns when work is marked done without any.
- Field projection. `fields=` on `pm_get` and `pm_grab`, and `brief=` on
  `pm_batch_get` and `pm_list_sprints`, return only what you ask for.
- `pm_update` supports `unassign=true` and `clear="field,field"` for assignee,
  dependencies, tags, points, and epic.
- `pm_audit` gained a one-line digest and a `since=` parameter that
  short-circuits when nothing changed.
- Run IDs and claim metadata are recorded on grab, release, update, and
  done_next. Stale claims are detected and can be recovered from the activity
  log, so an interrupted orchestrator run can resume.
- Tool families for changesets, web, and maintenance can be switched off in
  config to shrink the tool list, with CLI fallbacks for each.
- `projectman migrate-worktree` moves `.project/` onto its own orphan
  `projectman` branch mounted as a git worktree, so PM data no longer clutters
  feature branches. It refuses on a dirty tree and rolls back fully on failure.
- `projectman attach` mounts that branch on a fresh clone, and
  `projectman init` auto-attaches when it finds the branch on origin.
- Usage telemetry: a committed baseline, per-tool longest-run metrics,
  tool-list-size reporting, and rates for completions without a run log.
- Reference docs for the verdict-verb, evidence, claim-and-release, and
  cache-semantics contracts.
- `pm_git_status` and `projectman git-status` report the PM store on its own
  (`pm_store`: branch, worktree flag, dirty count, ahead/behind), so a store on
  the `projectman` branch is never read as `main`'s state.
- `pm_commit` results carry `on_branch`, the branch the commit landed on.
- A "Living with the projectman worktree" reference covering `git clean`,
  the ignored-but-precious store, fresh clones, and the private sibling-repo
  variant for public repositories.

### Changed

- Task claiming is atomic. A lost race returns an `already_claimed` error over
  MCP and a 409 over HTTP instead of silently double-assigning.
- All store writes go through temp-file plus rename, so a concurrent reader
  never sees half-written frontmatter.
- `pm_done_next` is a thin wrapper over the accept path and always logs, even
  when no note is given.
- Acceptance criteria accept a list of strings. A single string is one
  criterion and is no longer split on commas.
- The archived-as-done migration only acts on a positive archive signal.
  Ambiguous cases are reported for review instead of being rewritten.
- The pm, autoscope, and orchestrate skills call `pm_context` and
  `pm_estimate` before writing points, and the orchestrator uses the verdict
  verbs and evidence fields.

### Performance

- Config is read once per process instead of on every call.
- Semantic search is vectorised rather than brute-force.
- Board, epic, and search views no longer read each item from disk
  individually. Regression tests pin the query counts.
- Deep-copy overhead on cached reads is gone.

### Fixed

- Shell-injection risk in changeset PR command generation.
- `pm_done_next` and `pm_release` report when a note was truncated, matching
  `pm_update`.
- Archiving a task no longer marks it done.
- `pm_commit` and `pm_push` work against a worktree-mounted `.project/`.
  Commits land on the `projectman` branch and pushes move only that branch;
  before, the non-hub commit failed on the ignored path, the hub commit was a
  silent no-op, and push sent `main`.
- `migrate-worktree` pushes the branch from the repo root, so a relative
  remote URL resolves correctly.

### Removed

- Internal usage-study transcripts, and machine-specific paths and labels in
  stories, notes, docs, and the telemetry baseline.

### Known gaps

- API authentication for the web server is scoped but not started.
