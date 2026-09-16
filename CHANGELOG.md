# Changelog

All notable changes to ProjectMan are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.11.0] - 2026-09-17

US-PM-54 (EPIC-PM-7). Measured on 2026-09-17, every full prompt-cache miss on
a long orchestrated run sat after a worker wait longer than the one-hour cache
TTL, and together they were 19-45% of the run's input spend. This release keeps
the cache warm through those waits and makes the cache TTL a run was on visible.

### Added

- **`/pm-orchestrate` heartbeat (US-PM-54).** Phase 0 arms one session-only
  cron job that fires every 30 minutes while the REPL is idle and has the
  orchestrator answer in a few words with no tools. Each firing is a cheap
  cached read that refreshes the one-hour prompt-cache TTL, so a worker wait
  longer than an hour no longer re-sends the whole context at the 2x write
  price. Measured on the three largest Kura runs, those misses were $6-16 a
  run, 19-45% of input spend; the beats cost about $1. The prompt also tells
  the orchestrator to delete the job when no run is in flight, and Phase 4
  deletes it on the normal path. Rationale, the regime comparison against a
  five-minute-cache ping-pong, and the `promptCacheTtl` setting that pins the
  one-hour cache through usage-credit overage: *Heartbeat* in
  `docs/reference/orchestrate-design.md`.
- **`projectman orch-cost` reports the cache TTL mix and heartbeats.** `ttl`
  counts the calls that wrote `ephemeral_5m` versus `ephemeral_1h` entries
  (from `usage.cache_creation`), and `heartbeats` counts the keep-alive
  firings, in both the text report and `--json`. A run that silently dropped
  to the five-minute cache now shows up in its metrics.

### Changed

- The rendered `pm-orchestrate` skill size cap is 10,200 characters (was
  10,000): the lane clauses the tests pin left no slack for the heartbeat's
  `CronCreate`/`CronDelete` pair. Four unpinned parentheticals were trimmed;
  no rule changed.

## [0.10.0] - 2026-09-09

Changes landed 2026-09-09 in Sprints 15 and 16 (EPIC-PM-7, orchestrator
context cost). Measured on 2026-09-08, one orchestrated task added 7-9k tokens
to the orchestrator's prompt here and 16-28k on a larger codebase, and every
full prompt-cache miss lined up with a worker that ran past the one-hour cache
window. This release attacks both.

### Added

- **ADR-005: worktree isolation.** Each orchestrated task now runs in its own
  git worktree on branch `orch/<run-id>/<task-id>`, cut from a run branch
  `orch/<run-id>` that pre-flight creates from `HEAD`. The worker commits its
  own code on its branch; the orchestrator merges it onto the run branch when
  `pm_accept` takes the task, and at no other time. Nothing is pushed and the
  `.project` store is never committed by a run. This supersedes the stage-only
  model's "no branches, no worktrees, no commits" rule; the no-push half stays.
- **`--lanes 2` on `/pm-orchestrate`.** The orchestrator can keep two
  independent tasks in flight, validating and merging whichever worker returns
  first while the other still runs. `--lanes 1` remains the default and is the
  old loop exactly.
- **`pm_board(lane_compatible_with=<task-id>)`.** Filters `available` down to
  tasks that can run beside one already in flight: not the same story, no
  dependency between them or their stories, transitively. The response carries
  `lane_excluded: <n>` so a short board is never mistaken for an empty backlog.
- **Validator subagent.** The orchestrator still owns the verdict, but the
  checks that produce it now run inside a subagent whose context is discarded
  the moment it answers a bounded JSON report (about 1,500 characters) that
  doubles as the `evidence` argument. With two lanes it is told which files
  belong to the other lane. Worker reports are capped the same way.
- **`projectman orch-cost <run-id>`.** Reads the Claude Code session transcript
  that recorded a run and reports context base, peak and growth, growth per
  dispatch and per accepted task, tool-result bytes by tool, worker-wait
  percentiles, and every full cache miss with the idle gap that preceded it.
  `--transcripts DIR` and `--json` are available.
- **`duration_history` on `pm_estimate` and `pm_scope`.** Grab-to-done minutes
  per points band (p50, p90, max, n), read from `activity.jsonl` and counting
  only `orch-`-stamped transitions, so a sizer can tell a 3 that runs an hour
  here from a 3 that runs three.
- **`long_task_risk` on `pm_get_sprint`, and audit check `long-task-risk`.**
  Open tasks in a band whose p90 exceeds `orchestrate.max_task_minutes` are
  listed so `/pm-plan` can ask to split them before activating. The audit
  finding is warning-level so it never halts a run.
- **`orchestrate.max_task_minutes`** in `.project/config.yaml` (default 60,
  the prompt-cache window a worker must not overrun).
- **`brief=` and `fields=` on `pm_board`.** `brief=True` drops the story
  label, readiness blockers and suitability hints from every row; `fields=`
  names the row keys to keep, with the same semantics as `pm_get`.

### Changed

- The orchestrator's own traffic is slimmer: every pre-flight read is
  projected (`pm_list_sprints(status="active", brief=True)`,
  `pm_board(brief=True)`), worker prompts and reports carry less free text,
  and validation moved out of the orchestrator's context entirely.
- The rendered skill size cap is 10000 characters (was 9000). The orchestrate
  skill renders at 9995.
- `docs/reference/orchestrate-design.md` documents the isolation model, the
  validator subagent, lanes and the dependency barrier between them.

### Upgrading

After `pipx install --force "/mnt/repos/ProjectMan[all]"`, run
`projectman refresh-skills --keep-local` and restart the session. Until then
the installed orchestrate skill is the stage-only one and the MCP server has
no `lane_compatible_with`, `long_task_risk` or `duration_history`.

## [0.9.2] - 2026-09-08

Version bump only, no code changes. `pipx upgrade` replaces an install only
when the version number rises, so this release exists to move clients that
were pinned at an earlier build.

## [0.9.1] - 2026-09-08

### Removed

- A stray ProjectMan store that had been tracked under `src/projectman/web/`
  since 0.7.0. Nothing referenced it and it was never shipped in the wheel.

## [0.9.0] - 2026-09-08

Changes landed between 2026-08-19 and 2026-09-08.

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
- Bounds on the activity log. `activity_log_max_bytes` and
  `activity_log_max_days` in `config.yaml` make the append that finds
  `activity.jsonl` over the bound rename it to a dated sibling
  (`activity-YYYYMMDD-HHMMSS.jsonl`) and start a fresh file; readers walk the
  siblings oldest-first, so `pm_activity` still returns rotated history. Both
  keys are unset by default, and an unset log grows exactly as it always has.
- Run IDs and claim metadata are recorded on grab, release, update, and
  done_next. Stale claims are detected and can be recovered from the activity
  log, so an interrupted orchestrator run can resume.
- Tool families for web and maintenance can be switched off in config to shrink
  the tool list, with CLI fallbacks for each.
- `projectman migrate-worktree` moves `.project/` onto its own orphan
  `projectman` branch mounted as a git worktree, so PM data no longer clutters
  feature branches. It refuses on a dirty tree and rolls back fully on failure.
- `projectman attach` mounts that branch on a fresh clone, and
  `projectman init` auto-attaches when it finds the branch on origin.
- Usage telemetry: a committed baseline, per-tool longest-run metrics,
  tool-list-size reporting, and rates for completions without a run log. A
  post-subtraction baseline and one windowed to sessions after the
  note-length fix follow, each produced by the same extractor and each saying
  which of the earlier claims still hold.
- Reference docs for the verdict-verb, evidence, claim-and-release, and
  cache-semantics contracts.
- `pm_git_status` and `projectman git-status` report the PM store on its own
  (`pm_store`: branch, worktree flag, dirty count, ahead/behind), so a store on
  the `projectman` branch is never read as `main`'s state.
- `pm_commit` results carry `on_branch`, the branch the commit landed on.
- A "Living with the projectman worktree" reference covering `git clean`,
  the ignored-but-precious store, fresh clones, and the private sibling-repo
  variant for public repositories.
- `pm_next` and the `/pm-next` skill: a short note the next session reads
  first. It is read, appended to, replaced, and cleared through the tool,
  `pm_context` returns it under `next_time`, and the indexer, the audit, and
  search leave `NEXT.md` alone.
- Structured error responses. Every failure carries a machine-readable
  `error_code` alongside its message, raised from specific exception types
  with the catch-all kept as a fallback.
- `pm_board` explains the difference between a `blocked` status and a task
  held back by an unmet dependency, and `pm_create_tasks` documents forward
  references between the tasks of one batch.
- An Upgrading section in `docs/installation.md`: the pipx force-reinstall
  from a local path, the `refresh-skills` step, the symptom of a stale
  install, and the `mcp<2` requirement. The README links to it.
- This changelog, with the 0.8.0 through 0.8.15 version history.

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
- The skills are rewired to the new surface: the orchestrator uses the verdict
  verbs and the evidence fields, and the pm and autoscope skills reach for
  `pm_context` and `pm_estimate` when sizing work.
- Creating an item never overwrites one. Every create path raises when the
  target file already exists, ID allocation stays above every surviving item
  even after a file is deleted, and creates write atomically.
- A write dirties only the item file and `activity.jsonl`. The five derived
  index files are regenerated by `pm_reindex`, `pm_commit`, and the CLI
  `reindex` command rather than on every write, and no reader serves stale
  data because of it.
- The pm-orchestrate skill is under 9KB of instruction. Its rationale and
  resume protocol moved to `docs/reference/orchestrate-design.md`, and its
  worker prompt carries the git-safety rules learned in Sprints 5 to 7
  verbatim.
- `pm_estimate` before writing points and a session-start `pm_context` are
  mandatory only under the orchestrator. The interactive skill and agent
  templates no longer require either; the orchestrate skill still takes one
  bounded `pm_context` per run and refuses unestimated sprint content.
- Mutating tools carry honest `destructiveHint` annotations, IDs are validated
  against the `US-PREFIX-N`, `US-PREFIX-N-N`, and `EPIC-PREFIX-N` patterns
  instead of by convention, and list parameters accept real lists alongside
  the comma-separated strings that still work.
- The skills docs say which operations route through `/pm` and which are CLI
  or MCP.
- Reading the activity log has one implementation. `activity_log.py` owns the
  tolerant reader — missing file, unparseable line — that `pm_activity`, the
  orchestrator resume path and the migrations each used to hand-roll
  separately.
- `pm_audit` warns only about what someone can act on. The
  criteria-without-test-task rule skips done and archived stories, whose
  criteria were verified some other way and where the suggested remedy would
  only add todo test tasks under finished work. The done-without-evidence
  rule counts only completions that could have carried evidence — a run-log
  entry written at or after this store's own first evidence, or a `done`
  transition stamped with a run ID — rather than every task completed before
  the contract existed. Both rules are stated in the audit code instead of a
  magic date, and no historical item was edited to move the numbers: this
  repository's audit went from three standing warnings to zero.
- The unit suite runs green on a fresh checkout. The template-history tests
  read their fixture from a pinned commit instead of following `HEAD` and skip
  with a reason when git cannot show it, the CLI default-flag test passes on
  both the installed click and click 8.1, and keyword search and the estimator
  gained direct unit tests.

### Performance

- Config is read once per process instead of on every call.
- Semantic search is vectorised rather than brute-force.
- Board, epic, search, and audit views no longer read each item from disk
  individually. Regression tests pin the query counts.
- Cache updates and invalidations are O(1) by ID through a secondary index,
  instead of a linear scan of the cache list on every mutation.
- Deep-copy overhead on cached reads is gone.

### Fixed

- `pm_done_next` and `pm_release` report when a note was truncated, matching
  `pm_update`.
- Archiving a task no longer marks it done.
- `pm_commit` and `pm_push` work against a worktree-mounted `.project/`.
  Commits land on the `projectman` branch and pushes move only that branch;
  before, the commit failed on the ignored path and push sent `main`.
- `migrate-worktree` pushes the branch from the repo root, so a relative
  remote URL resolves correctly.
- Keyword search skips an item file whose frontmatter will not parse and
  returns results from every other file, instead of aborting the whole query.
  The `pm_search` response and the `/api/search` payload carry a `skipped`
  count, 0 when every file parsed.
- The web API's create endpoints return 409 with the coded error when the ID
  already exists and 422 on an invalid ID, and `docs/reference/agent.md` no
  longer opens with a mandatory `pm_context` call the agent template does not
  make.

### Removed

- **Changesets and the hub pull-request workflow.** Gone are the five
  `pm_changeset_*` MCP tools, the `projectman changeset` CLI group
  (`create`, `add-project`, `status`, `create-prs`, `push`), the
  `CS-*` changeset file format and its `next_changeset_id` counter, the
  `tools.changesets` config flag, and — in `hub/registry.py` — feature-branch
  creation and listing, PR creation and PR status polling, `update_hub_refs` /
  `update_hub_refs_after_merge`, deploy-branch validation, and the automatic
  resolution of submodule-ref rebase conflicts. Their tests are deleted, not
  skipped.

  **Why:** the changeset tools were called 9 times across 484 recorded
  sessions. Teams already have a branching and review convention and did not
  want a second one imposed by their project-management tool, so a quarter of
  the code and tests was taxing every change to a feature nobody used.

  **What to use instead:** `pm_commit` / `projectman commit`, `pm_push` /
  `projectman push` and `pm_git_status` / `projectman git-status` remain. Each
  acts on the one store this repo has, and `git-status` reports that store's
  branch, dirty count and ahead/behind. Create branches and pull requests with
  `git` and `gh` directly.
- **The `project` argument on every tool.** No tool takes a project name any
  more. There is one store, so nothing needs addressing: an ID's prefix is
  still validated against the `US-PREFIX-N` patterns, but no tool and no web
  route takes a prefix or a project. The web API's `?project=` query parameter
  went with it, and the MCP `tools/list` schema shrank by the difference.
- **Hub mode.** ProjectMan is a single-project tool. Gone are
  `projectman init --hub`, `add-project`, `set-branch`, `sync`, and
  `migrate-hub`; the `--project` and `--prefix` CLI options; the `prefix`
  argument on every MCP tool and on the web API's ID-less routes; the hub's
  copy of everyone's PM data at `.project/projects/{name}` and the
  `projects/{name}/.project` layout that replaced it; hub-level epics and the
  cross-project rollup, including `pm_status` subproject rows and `pm_epic`'s
  `by_project` grouping; hub dashboards (`hub/dashboards.py`, its
  `generate_dashboards` entry point, and the `.project/dashboards` directory
  `projectman init` used to create); the cross-repo git verbs `pm_push_all` /
  `projectman push-all`, `repair`, and `validate-branches`; the hub
  documentation check in `projectman audit`;
  the `hub:` and `projects:` config keys — a legacy `config.yaml` carrying
  them still loads, with the keys ignored and a one-line warning on stderr;
  `docs/hub-mode/`; and the whole `src/projectman/hub` package.

  **Why:** the multi-project surface was used 9 times across 484 recorded
  sessions, and 71 of the package's 97 error sites had no observed traffic at
  all — mostly hub and web. The Sprint 10 and 11 redesign, which moved each
  store next to its code and made the hub a read-only rollup, was meant to
  answer that; it gained no user. Nobody attached a project to a hub after it
  landed and no `migrate-hub` ever ran against a real one, so the mode was
  carrying the largest share of the package's branches for nothing.
  Rebuilding an unused mode is not a fix for it being unused. ADR-004 records
  the decision and supersedes ADR-003.

  **What to do instead:** an existing hub keeps working on 0.8.15 — nothing is
  retracted from a released version — so stay there if you need it. Otherwise
  run each former subproject as a single project on 0.9.0: its store already
  lives on that repo's own `projectman` branch, so there is nothing to
  convert. No migration is offered. What is lost is the rollup across projects
  and hub-level epics, which have no single-project equivalent.
- Internal usage-study transcripts, and machine-specific paths and labels in
  stories, notes, docs, and the telemetry baseline.

### Known gaps

- API authentication for the web server is scoped but not started.

## [0.8.15] - 2026-07-05

### Added

- /pm-orchestrate accepts `--orchestrator-model` and `--executor-model`.
- A model-selection step lets a larger model orchestrate the sprint while a
  cheaper one executes the tasks.

### Changed

- Worker subagents are spawned at the chosen executor tier.
- The model-selection prompt only appears when a newer model than the defaults
  is available.

## [0.8.14] - 2026-07-04

### Added

- `pm_update` with an empty assignee clears the assignment.

### Changed

- `pm_grab` is idempotent: re-claiming a task already assigned to the same
  assignee succeeds, which enables pre-claim handoff to workers.
- /pm-orchestrate's accept path uses `pm_done_next` scoped to the same story, so
  the run log, story auto-close, and the next pre-claim happen in one call,
  skipping a board refresh; unused pre-claims are released on stop.
- README and reference docs brought up to date for 0.8.x: all 47 MCP tools
  documented, /pm-orchestrate and /pm-cleanup listed, `serve --transport`
  options and the correct default port documented, the audit check table
  expanded from 13 to 17 entries, sprint and run-log file formats added, and an
  Upgrading section added.

### Fixed

- Retry workers no longer fail to re-grab a task they already hold.

## [0.8.13] - 2026-07-03

### Added

- New `refresh-skills` command that re-renders the agent and pm skills wherever
  they are already installed, without installing them into new locations.

### Changed

- `upgrade` now invokes the newly installed binary's `refresh-skills` so skills
  are re-rendered from the upgraded templates; `--no-skills` opts out.
- `refresh-skills` prunes project-local pm skills that a global install
  supersedes (`--keep-local` refreshes both instead), touching only
  ProjectMan-managed files.
- A "restart Claude Code" notice is printed whenever skill files change.

## [0.8.12] - 2026-07-03

### Added

- `pm_done_next`: completes a task, writes its run log, auto-closes the story
  when it is finished, and claims the next ready task in one call.

### Changed

- MCP responses are roughly 37% smaller: write calls echo the id, status, and
  changed fields rather than the whole object.
- `pm_get` accepts comma-separated IDs, run-log output became opt-in via
  `include_log`, and `pm_batch_get` gained an `ids` parameter.
- `pm_grab` can skip the story body and leaves done tasks out of the sibling
  list, reporting a done count instead.
- New payload ceilings: `pm_context` caps document text, auto-scope caps
  documents and skips lockfiles, and `pm_commit` returns a file count instead of
  echoing the message.
- `pm_audit` hides info-level findings unless `include_info` is set; DRIFT.md
  still lists everything.
- YAML output keeps unicode characters and long lines intact instead of escaping
  and wrapping them.
- /pm-do claims a task with `pm_grab` alone instead of three separate fetches.

### Fixed

- SSE transport mode serves the full Web UI and `/api/*` routes.
- Corrected a broken relative import in the web API routes.

## [0.8.11] - 2026-07-02

### Added

- `setup-claude --global` installs the agent and skills into `~/.claude` and
  registers the MCP server at user scope; `--local-skills` adds project-local
  copies.
- New `upgrade` command driving the pipx upgrade, plus `install` and `update`
  aliases.
- /pm-orchestrate is now distributed with the package.

### Changed

- /pm-orchestrate independently validates worker output (inspecting diffs,
  checking DoD evidence, re-running named tests) and retries once then parks the
  task instead of halting the sprint, writing a run-log entry per attempt.
- /pm-do requires proof for each DoD item before a task can be marked done, and
  writes status and run-log outcome in a single update.
- /pm-plan closes out expired sprints, sizes selection to velocity, requires a
  sprint goal, and gates on scoping before activating.
- /pm, /pm-status, /pm-autoscope, and /pm-cleanup gained clearer trigger
  descriptions and next-step chaining.
- The MCP server now honours the `PROJECTMAN_ROOT` environment variable.

### Fixed

- Removed stale skill references: a nonexistent `create-branch` command, an
  invalid sprint status value, and `pm_run_log` used as a writer.

### Removed

- Retired skill templates and a stale bundled copy of the web `.claude`
  directory.

## [0.8.10] - 2026-05-28

### Added

- /pm-orchestrate skill: reads the active sprint and drives it by dispatching
  `/pm-do --complete` worker subagents one at a time, reporting progress as it
  goes. It stages changes only — it never commits, pushes, or merges.

## [0.8.9] - 2026-04-11

### Added

- GitHub Actions CI running unit tests on Python 3.10, 3.11, and 3.12 plus
  stdio, SSE, and Web UI suites.
- Integration test suites covering both transports, twelve CRUD and workflow
  domains, and cache staleness against external file changes.

### Fixed

- Cache staleness tracks file count as well as mtime, so externally deleted
  files are detected and not just newer ones.
- Index generation reads straight from disk instead of a possibly stale cache,
  so generated index pages match reality.
- Embeddings are re-indexed automatically when a story or task is created or
  updated.
- The web API caches a store per hub subproject instead of rebuilding it per
  request.
- Cache appends no longer count as invalidations in cache statistics.
- `pm_create_story` always returns `test_tasks`, even when the list is empty.

## [0.8.8] - 2026-04-04

### Added

- Cross-story dependencies: tasks and stories can depend on items in other
  stories, forming a project-wide dependency graph.
- `depends_on` is now available on stories, not just tasks.
- Sprint create, get, and update tools report dependency warnings.

### Changed

- The cycle and orphan audit checks scan the whole project graph instead of a
  single story.
- Readiness checks validate cross-story dependencies before a task can be
  grabbed.
- PM skills and templates document cross-story dependency usage.

## [0.8.7] - 2026-04-04

### Added

- Testing documentation for projects that use ProjectMan, describing the
  `./tests/testing.sh <category>` harness interface they are expected to
  implement.

## [0.8.6] - 2026-03-19

### Added

- Sprints are now a persisted entity, with planned and completed points computed
  automatically.
- Four sprint MCP tools: `pm_create_sprint`, `pm_get_sprint`,
  `pm_list_sprints`, and `pm_update_sprint`.
- Audit check warning on stories that have test tasks but no implementation
  task.
- /pm-cleanup skill for archiving done epics, stories, and tasks with user
  approval.

### Changed

- /pm-plan validates implementation tasks, persists the sprint, and warns when a
  sprint is already active.

## [0.8.5] - 2026-03-13

### Added

- HTTP/SSE transport for the MCP server: `serve --transport (stdio|sse)` with
  `--host` and `--port`.
- `setup-claude` can write an SSE `.mcp.json` configuration.
- Orchestrator REST API: `/api/health`, `/api/project`, `/api/tasks/current`,
  and `/api/tasks/{id}`.
- SSE `/events` stream with keepalive and Last-Event-ID reconnection.
- Task, story, and epic create/update now emit events on that stream.

### Changed

- Default stdio behaviour is unchanged; the event bus is a no-op outside SSE
  mode.

## [0.8.4] - 2026-03-10

### Added

- Run-log tracking: `pm_update` accepts an outcome
  (success/partial/blocked/failed/info) and a note of up to 1024 characters.
- Run-log entries appended as JSONL under `.project/logs/<item-id>.jsonl`.
- `pm_run_log` MCP tool for reading run-log entries with pagination.

### Changed

- `pm_get` surfaces the three most recent run-log entries.
- /pm-do records an outcome on both completion and failure; agent, skills, and
  docs updated to match.

## [0.8.3] - 2026-03-08

### Added

- `pm_batch_get` MCP tool returning all epics, stories, or tasks with full data
  in a single call.
- `Store.list_all()` backing the new bulk retrieval path.

### Changed

- MCP tool docs, agent config, and /pm skill routing cover bulk retrieval.

## [0.8.2] - 2026-03-07

### Changed

- The scoper now orders implementation tasks before test tasks.
- Generated test tasks declare `depends_on` pointing at their implementation
  task(s).
- The pm-scope and pm-autoscope skill templates document the ordering rule.

## [0.8.1] - 2026-03-06

### Added

- Reference documentation for tags, task dependencies, changesets, the activity
  log, auto-commit, coordinated push, and git status.
- New MCP tool doc sections: Git & Push, Changeset, and Activity Log.
- CLI documentation for `commit`, `push`, `git-status`, `validate-branches`, and
  the changeset subcommands.
- Changeset Format and Activity Log Format entries in the file-formats
  reference.
- Dependencies and Tags sections in the task and story user guides.

### Fixed

- README no longer points at sentence-transformers; embeddings are documented as
  fastembed.

## [0.8.0] - 2026-03-06

### Added

- Hub-mode git workflow: feature branches, pull requests, coordinated multi-repo
  push, and ref tracking.
- Cross-repo changesets for grouping related changes across several projects.
- Task dependencies with topological ordering and cycle detection.
- Tags on stories and tasks, with filtering in the active, search, and board
  tools.
- Append-only JSONL activity log recording every mutation.
- Auto-commit of project-state changes when `auto_commit` is enabled in config.
- New MCP tools for git status, commit, push, push-all, changesets, and
  activity.
- Web UI now shows the activity log, tags, and dependency info on task and story
  detail pages.
- Hub-mode documentation covering the git workflow, conflict resolution, and
  submodule drift.

<!--
Releases before 0.9.0 were never tagged, so their links compare commit SHAs.
The 0.8.0 link points at its own release commit, having no predecessor here.
0.9.0 onward is tagged `vX.Y.Z`.
-->

[Unreleased]: https://github.com/Biztactix-Ryan/ProjectMan/compare/v0.10.0...main
[0.10.0]: https://github.com/Biztactix-Ryan/ProjectMan/compare/v0.9.2...v0.10.0
[0.9.2]: https://github.com/Biztactix-Ryan/ProjectMan/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/Biztactix-Ryan/ProjectMan/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Biztactix-Ryan/ProjectMan/compare/657efba...v0.9.0
[0.8.15]: https://github.com/Biztactix-Ryan/ProjectMan/compare/2261a0d...657efba
[0.8.14]: https://github.com/Biztactix-Ryan/ProjectMan/compare/1982933...2261a0d
[0.8.13]: https://github.com/Biztactix-Ryan/ProjectMan/compare/da98100...1982933
[0.8.12]: https://github.com/Biztactix-Ryan/ProjectMan/compare/39ae124...da98100
[0.8.11]: https://github.com/Biztactix-Ryan/ProjectMan/compare/532ed54...39ae124
[0.8.10]: https://github.com/Biztactix-Ryan/ProjectMan/compare/fca9f18...532ed54
[0.8.9]: https://github.com/Biztactix-Ryan/ProjectMan/compare/35c04c1...fca9f18
[0.8.8]: https://github.com/Biztactix-Ryan/ProjectMan/compare/5052003...35c04c1
[0.8.7]: https://github.com/Biztactix-Ryan/ProjectMan/compare/66e2894...5052003
[0.8.6]: https://github.com/Biztactix-Ryan/ProjectMan/compare/4af9a57...66e2894
[0.8.5]: https://github.com/Biztactix-Ryan/ProjectMan/compare/03a1674...4af9a57
[0.8.4]: https://github.com/Biztactix-Ryan/ProjectMan/compare/ae98a7b...03a1674
[0.8.3]: https://github.com/Biztactix-Ryan/ProjectMan/compare/dca10fa...ae98a7b
[0.8.2]: https://github.com/Biztactix-Ryan/ProjectMan/compare/7cd6fdc...dca10fa
[0.8.1]: https://github.com/Biztactix-Ryan/ProjectMan/compare/69f26db...7cd6fdc
[0.8.0]: https://github.com/Biztactix-Ryan/ProjectMan/commit/69f26db
