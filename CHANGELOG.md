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
- Tool families for web and maintenance can be switched off in config to shrink
  the tool list, with CLI fallbacks for each.
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
  the code and tests was taxing every change to a feature nobody used. A hub
  redesign, built on the read-only rollup that stays, will follow.

  **What to use instead:** `pm_commit` / `projectman commit`, `pm_push` /
  `projectman push` (still coordinated: subprojects first, hub ref only after)
  and `pm_git_status` / `projectman git-status` are unchanged. Create branches
  and pull requests with `git` and `gh` directly. A hub push whose rebase
  conflicts now aborts cleanly and reports `rebase conflict — manual
  resolution required` instead of picking a ref for you; resolve it and push
  again. The read-only hub rollup and dashboards are untouched.
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
No git tags exist in this repository, so the links below compare commit SHAs.
The 0.8.0 link points at its own release commit, having no predecessor here.
-->

[Unreleased]: https://github.com/Biztactix-Ryan/ProjectMan/compare/657efba...main
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
