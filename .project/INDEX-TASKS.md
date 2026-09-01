# Tasks

| ID | Title | Status | Points | Tags | Assignee | Depends On | Story |
| -- | ----- | ------ | ------ | ---- | -------- | ---------- | ----- |
| [US-PM-1-1](tasks/US-PM-1-1.md) | Test: Oversized notes are truncated server-side with a visible marker rather than rejected;The response carries a not... | ✅ done | — |  | — | — | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-2](tasks/US-PM-1-2.md) | Truncate oversized run-log notes instead of raising | ✅ done | 1 |  | claude | — | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-3](tasks/US-PM-1-3.md) | Return a note_truncated flag on the update response | ✅ done | 1 |  | claude | US-PM-1-2 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-4](tasks/US-PM-1-4.md) | Test: oversized note truncates and the status write still lands | ✅ done | 1 |  | claude | US-PM-1-2 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-5](tasks/US-PM-1-5.md) | Test: note_truncated flag and boundary lengths | ✅ done | 1 |  | claude | US-PM-1-3 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-6](tasks/US-PM-1-6.md) | Clear the stale port-forward markers left by the 0.8.15 rebase | ✅ done | 1 |  | claude | — | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-10-1](tasks/US-PM-10-1.md) | Test: pm_get and pm_grab accept a fields parameter selecting returned keys | ✅ done | 1 |  | claude | US-PM-10-6 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-2](tasks/US-PM-10-2.md) | Test: A status-only verification fetch costs a small fraction of the full payload | ✅ done | 1 |  | claude | US-PM-10-6 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-3](tasks/US-PM-10-3.md) | Test: pm_batch_get and pm_list_sprints support a brief or projected mode | ✅ done | 1 |  | claude | US-PM-10-7 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-4](tasks/US-PM-10-4.md) | Test: Default behaviour is unchanged when no projection is requested | ✅ done | 1 |  | claude | US-PM-10-6, US-PM-10-7 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-5](tasks/US-PM-10-5.md) | Test: pm-orchestrate uses projection for its validation read | ✅ done | 1 |  | claude | US-PM-10-8 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-6](tasks/US-PM-10-6.md) | Add a fields parameter to pm_get and pm_grab | ✅ done | 3 |  | claude | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-7](tasks/US-PM-10-7.md) | Add a brief mode to pm_batch_get and pm_list_sprints | ✅ done | 2 |  | claude | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-8](tasks/US-PM-10-8.md) | Use projection for the orchestrator validation read | ✅ done | 1 |  | claude | US-PM-10-6 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-11-1](tasks/US-PM-11-1.md) | Test: pm_audit returns a digest identifying the current project state | ✅ done | 1 |  | claude | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-2](tasks/US-PM-11-2.md) | Test: pm_audit accepts a since parameter and answers cheaply when nothing changed | ✅ done | 1 |  | claude | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-3](tasks/US-PM-11-3.md) | Test: The health check still detects new ERROR-level findings promptly | ✅ done | 1 |  | claude | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-4](tasks/US-PM-11-4.md) | Test: pm-orchestrate passes the previous digest on its periodic health check | ✅ done | 1 |  | claude | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-5](tasks/US-PM-11-5.md) | Return a state digest from pm_audit | ✅ done | 2 |  | claude | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-6](tasks/US-PM-11-6.md) | Accept a since parameter and short-circuit when unchanged | ✅ done | 1 |  | claude | US-PM-11-5 | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-7](tasks/US-PM-11-7.md) | Pass the previous digest from the orchestrator health check | ✅ done | 1 |  | claude | US-PM-11-6 | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-12-1](tasks/US-PM-12-1.md) | Test: A bulk update accepts either a uniform patch over an ID list or per-item patches | ✅ done | 1 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-2](tasks/US-PM-12-2.md) | Test: Bulk archive accepts an explicit ID list | ✅ done | 1 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-3](tasks/US-PM-12-3.md) | Test: Partial failure reports which IDs succeeded and which did not | ✅ done | 1 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-4](tasks/US-PM-12-4.md) | Test: The four measured bulk patterns are each expressible in one call | ✅ done | 1 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-5](tasks/US-PM-12-5.md) | Test: Longest consecutive-run length drops sharply in the next telemetry baseline | 🔍 review | 1 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-6](tasks/US-PM-12-6.md) | Add pm_update_many | ✅ done | 3 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-7](tasks/US-PM-12-7.md) | Add bulk archive with an explicit ID list | ✅ done | 2 |  | claude | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-8](tasks/US-PM-12-8.md) | Define partial-failure semantics | ✅ done | 2 |  | claude | US-PM-12-6, US-PM-12-7 | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-13-1](tasks/US-PM-13-1.md) | Test: The worker prompt template includes project architecture context | ✅ done | 1 |  | claude | US-PM-13-5 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-2](tasks/US-PM-13-2.md) | Test: The scoping and estimation workflows consult pm_estimate before writing points | ✅ done | 1 |  | claude | US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-3](tasks/US-PM-13-3.md) | Test: Skill files name the step at which each guidance tool is called | ✅ done | 1 |  | claude | US-PM-13-5, US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-4](tasks/US-PM-13-4.md) | Test: Usage of both tools is visible in the next telemetry baseline | ✅ done | 1 |  | claude | US-PM-13-5, US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-5](tasks/US-PM-13-5.md) | Add project context to the worker prompt template | ✅ done | 1 |  | claude | — | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-6](tasks/US-PM-13-6.md) | Call pm_estimate before writing points in the scoping workflows | ✅ done | 1 |  | claude | — | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-14-1](tasks/US-PM-14-1.md) | Test: An interrupted run can identify which claims it owned | ✅ done | 1 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-2](tasks/US-PM-14-2.md) | Test: Stale claims are identifiable without asking a human | ✅ done | 1 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-3](tasks/US-PM-14-3.md) | Test: The final report is built from the activity log rather than from memory | ✅ done | 1 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-4](tasks/US-PM-14-4.md) | Test: pm-orchestrate has a documented resume path | ✅ done | 1 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-5](tasks/US-PM-14-5.md) | Add claim ownership and staleness metadata | ✅ done | 2 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-6](tasks/US-PM-14-6.md) | Replace the Phase 1 ownership guess with an activity query | ✅ done | 2 |  | claude | US-PM-14-5 | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-7](tasks/US-PM-14-7.md) | Build the final report from the activity log | ✅ done | 2 |  | claude | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-8](tasks/US-PM-14-8.md) | Document a resume path in pm-orchestrate | ✅ done | 1 |  | claude | US-PM-14-6 | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-15-1](tasks/US-PM-15-1.md) | Test: Changeset and web tool families are hidden unless enabled by config | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-2](tasks/US-PM-15-2.md) | Test: Repair and restore tooling is hidden from the agent tool list but reachable via CLI | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-3](tasks/US-PM-15-3.md) | Test: pm_activity and pm_context and pm_estimate remain exposed | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-4](tasks/US-PM-15-4.md) | Test: Tool-list payload size drops measurably with default config | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-5](tasks/US-PM-15-5.md) | Add config flags for the changeset and web tool families | ✅ done | 2 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-6](tasks/US-PM-15-6.md) | Move repair and restore tooling off the agent tool list | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-7](tasks/US-PM-15-7.md) | Measure the tool-list payload reduction | ✅ done | 1 |  | claude | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-16-1](tasks/US-PM-16-1.md) | Test: Archiving a task no longer sets its status to done | ✅ done | 1 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-2](tasks/US-PM-16-2.md) | Test: Archived tasks are excluded from completion percentage and burndown | ✅ done | 1 |  | claude | US-PM-16-6 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-3](tasks/US-PM-16-3.md) | Test: Sprint velocity counts only genuinely completed points | ✅ done | 1 |  | claude | US-PM-16-6 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-4](tasks/US-PM-16-4.md) | Test: Existing archived-as-done tasks can be identified and corrected by a migration | ✅ done | 1 |  | claude | US-PM-16-7 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-5](tasks/US-PM-16-5.md) | Add an archived state for tasks | ✅ done | 2 |  | claude | — | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-6](tasks/US-PM-16-6.md) | Exclude archived items from completion and velocity math | ✅ done | 2 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-7](tasks/US-PM-16-7.md) | Migrate existing archived-as-done tasks | ✅ done | 2 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-17-1](tasks/US-PM-17-1.md) | Test: A task completed in a single todo-to-done write is never a migration candidate | ✅ done | 1 |  | claude | US-PM-17-7 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-2](tasks/US-PM-17-2.md) | Test: Applying the migration cannot move a task out of done without a positive archive signal | ✅ done | 1 |  | claude | US-PM-17-7 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-3](tasks/US-PM-17-3.md) | Test: The known legacy archives in this repo are still handled or explicitly documented as unrecoverable | ✅ done | 1 |  | claude | US-PM-17-9 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-4](tasks/US-PM-17-4.md) | Test: The module docstring's safety claim matches actual behaviour | ✅ done | 1 |  | claude | US-PM-17-7 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-5](tasks/US-PM-17-5.md) | Test: Regression test covers single-write completion alongside the in-progress path | ✅ done | 1 |  | claude | US-PM-17-8 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-6](tasks/US-PM-17-6.md) | Decide and document how an archive is positively identified | ✅ done | 2 |  | claude | — | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-7](tasks/US-PM-17-7.md) | Implement the chosen detection change in migrations.py | ✅ done | 2 |  | claude | US-PM-17-6 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-8](tasks/US-PM-17-8.md) | Add regression tests for single-write completion | ✅ done | 2 |  | claude | US-PM-17-7 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-17-9](tasks/US-PM-17-9.md) | Resolve the four live candidates in this repo | ✅ done | 1 |  | claude | US-PM-17-7 | [US-PM-17](stories/US-PM-17.md) |
| [US-PM-18-1](tasks/US-PM-18-1.md) | Test: A criterion containing commas is stored as one criterion via pm_create_story | ✅ done | 1 |  | claude | US-PM-18-6 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-2](tasks/US-PM-18-2.md) | Test: A criterion containing commas is stored as one criterion via pm_update | ✅ done | 1 |  | claude | US-PM-18-6 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-3](tasks/US-PM-18-3.md) | Test: pm_update criteria edits still reconcile auto-generated test tasks correctly | ✅ done | 1 |  | claude | US-PM-18-6 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-4](tasks/US-PM-18-4.md) | Test: Tool docstrings no longer instruct comma-separated criteria | ✅ done | 1 |  | claude | US-PM-18-6 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-5](tasks/US-PM-18-5.md) | Test: Regression tests cover comma-bearing criteria on both tools | ✅ done | 1 |  | claude | US-PM-18-7 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-6](tasks/US-PM-18-6.md) | Switch acceptance_criteria params to list input in pm_create_story and pm_update | ✅ done | 3 |  | claude | — | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-18-7](tasks/US-PM-18-7.md) | Add regression tests for comma-bearing acceptance criteria | ✅ done | 2 |  | claude | US-PM-18-6 | [US-PM-18](stories/US-PM-18.md) |
| [US-PM-19-1](tasks/US-PM-19-1.md) | Test: Running the migration leaves .project mounted as a worktree on an orphan projectman branch | ✅ done | 1 |  | claude | US-PM-19-7 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-2](tasks/US-PM-19-2.md) | Test: main stops tracking .project and gains a .gitignore entry for it | ✅ done | 1 |  | claude | US-PM-19-7 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-3](tasks/US-PM-19-3.md) | Test: All existing PM files survive the migration intact | ✅ done | 1 |  | claude | US-PM-19-7 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-4](tasks/US-PM-19-4.md) | Test: Migration refuses to run on a dirty working tree | ✅ done | 1 |  | claude | US-PM-19-8 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-5](tasks/US-PM-19-5.md) | Test: Migration refuses when a projectman branch already exists and points at attach | ✅ done | 1 |  | claude | US-PM-19-8 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-6](tasks/US-PM-19-6.md) | Test: The projectman branch is pushed to origin when a remote exists | ✅ done | 1 |  | claude | US-PM-19-9 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-7](tasks/US-PM-19-7.md) | Implement migrate-worktree command core | ✅ done | 5 |  | claude | — | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-8](tasks/US-PM-19-8.md) | Add safety rails: dirty-tree and existing-branch refusal | ✅ done | 2 |  | claude | US-PM-19-7 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-19-9](tasks/US-PM-19-9.md) | Handle remotes and document the history-preserving variant | ✅ done | 2 |  | claude | US-PM-19-7 | [US-PM-19](stories/US-PM-19.md) |
| [US-PM-2-1](tasks/US-PM-2-1.md) | Test: Tool failures raise a real MCP error rather than returning an error string body;is_error is set on every failur... | ✅ done | — |  | — | — | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-2](tasks/US-PM-2-2.md) | Inventory every error-string return path | ✅ done | 2 |  | claude | — | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-3](tasks/US-PM-2-3.md) | Raise genuine failures as real MCP errors | ✅ done | 2 |  | claude | US-PM-2-2 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-4](tasks/US-PM-2-4.md) | Keep expected-negative results as successful responses | ✅ done | 2 |  | claude | US-PM-2-2 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-5](tasks/US-PM-2-5.md) | Test: every known failure class sets is_error | ✅ done | 1 |  | claude | US-PM-2-3 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-6](tasks/US-PM-2-6.md) | Test: expected negatives are not errors | ✅ done | 1 |  | claude | US-PM-2-4 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-20-1](tasks/US-PM-20-1.md) | Test: projectman attach mounts the projectman branch as the .project worktree on a fresh clone | ✅ done | 1 |  | claude | US-PM-20-5 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-20-2](tasks/US-PM-20-2.md) | Test: projectman init detects origin/projectman and attaches instead of scaffolding a new store | ✅ done | 1 |  | claude | US-PM-20-6 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-20-3](tasks/US-PM-20-3.md) | Test: Attach is a friendly no-op when the worktree is already mounted | ✅ done | 1 |  | claude | US-PM-20-5 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-20-4](tasks/US-PM-20-4.md) | Test: Attach fails with an actionable message when .project holds untracked content instead of clobbering it | ✅ done | 1 |  | claude | US-PM-20-5 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-20-5](tasks/US-PM-20-5.md) | Implement projectman attach command | ✅ done | 3 |  | claude | US-PM-19-7 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-20-6](tasks/US-PM-20-6.md) | Teach projectman init to detect origin/projectman and attach | ✅ done | 2 |  | claude | US-PM-20-5 | [US-PM-20](stories/US-PM-20.md) |
| [US-PM-21-1](tasks/US-PM-21-1.md) | Test: pm_commit lands commits on the projectman branch without dirtying main | ⚪ todo | — |  | — | US-PM-21-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-2](tasks/US-PM-21-2.md) | Test: pm_push pushes only the projectman branch | ⚪ todo | — |  | — | US-PM-21-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-3](tasks/US-PM-21-3.md) | Test: pm_git_status reports the .project worktree state distinctly from main | ⚪ todo | — |  | — | US-PM-21-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-4](tasks/US-PM-21-4.md) | Test: Hub mode introduces no submodule-pointer noise in the parent repo | ⚪ todo | — |  | — | US-PM-21-8 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-5](tasks/US-PM-21-5.md) | Test: Docs cover git clean behaviour and the ignored-but-precious nature of .project | ⚪ todo | — |  | — | US-PM-21-9 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-6](tasks/US-PM-21-6.md) | Test: Docs describe the private sibling-repo variant for public repos | ⚪ todo | — |  | — | US-PM-21-9 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-7](tasks/US-PM-21-7.md) | Integration tests: pm git ops against a worktree-mounted .project | ⚪ todo | 5 |  | — | US-PM-19-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-8](tasks/US-PM-21-8.md) | Hub-mode regression check for worktree stores | ⚪ todo | 3 |  | — | US-PM-21-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-21-9](tasks/US-PM-21-9.md) | Document worktree rough edges and the private sibling-repo variant | ⚪ todo | 2 |  | — | US-PM-19-7 | [US-PM-21](stories/US-PM-21.md) |
| [US-PM-3-1](tasks/US-PM-3-1.md) | Test: Every tool taking a typed ID also accepts the generic id parameter | ✅ done | 1 |  | claude | US-PM-3-6 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-2](tasks/US-PM-3-2.md) | Test: Tools taking id also accept the typed alias where one exists | ✅ done | 1 |  | claude | US-PM-3-6 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-3](tasks/US-PM-3-3.md) | Test: Passing both a typed ID and id with conflicting values is a clear error | ✅ done | 1 |  | claude | US-PM-3-5 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-4](tasks/US-PM-3-4.md) | Test: Test covers each aliased tool with both spellings | ✅ done | 1 |  | claude | US-PM-3-6 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-5](tasks/US-PM-3-5.md) | Add a shared ID-alias resolver | ✅ done | 2 |  | claude | — | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-6](tasks/US-PM-3-6.md) | Apply the resolver across all ID-taking tools | ✅ done | 2 |  | claude | US-PM-3-5 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-3-7](tasks/US-PM-3-7.md) | Sweep docstrings so the alias is discoverable | ✅ done | 1 |  | claude | US-PM-3-6 | [US-PM-3](stories/US-PM-3.md) |
| [US-PM-4-1](tasks/US-PM-4-1.md) | Test: Warnings that would fire on every item in a project are suppressed | ✅ done | 1 |  | claude | US-PM-4-6 | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-4-2](tasks/US-PM-4-2.md) | Test: Determine whether the templates or the checks are at fault before removing | ✅ done | 1 |  | claude | US-PM-4-5 | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-4-3](tasks/US-PM-4-3.md) | Test: Payload size for pm_grab drops measurably | ✅ done | 1 |  | claude | US-PM-4-6 | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-4-4](tasks/US-PM-4-4.md) | Test: Test asserts no warning has a 100 percent hit rate across a sample project | ✅ done | 1 |  | claude | US-PM-4-6 | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-4-5](tasks/US-PM-4-5.md) | Determine whether the templates or the checks are wrong | ✅ done | 1 |  | claude | — | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-4-6](tasks/US-PM-4-6.md) | Suppress warnings that fire on every item | ✅ done | 1 |  | claude | US-PM-4-5 | [US-PM-4](stories/US-PM-4.md) |
| [US-PM-5-1](tasks/US-PM-5-1.md) | Test: Editing acceptance criteria adds test tasks for new criteria | ✅ done | 1 |  | claude | US-PM-5-5 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-10](tasks/US-PM-5-10.md) | Keep flagged orphans visible and treat an unreadable run log as work | ✅ done | 2 |  | claude | — | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-2](tasks/US-PM-5-2.md) | Test: Test tasks for removed criteria are flagged rather than silently deleted if work has started | ✅ done | 1 |  | claude | US-PM-5-6 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-3](tasks/US-PM-5-3.md) | Test: Test task title and body stay in sync with the criterion text | ✅ done | 1 |  | claude | US-PM-5-5 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-4](tasks/US-PM-5-4.md) | Test: pm_audit reports a finding when a story has criteria without matching test tasks | ✅ done | 1 |  | claude | US-PM-5-7 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-5](tasks/US-PM-5-5.md) | Reconcile test tasks in store.update | ✅ done | 3 |  | claude | — | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-6](tasks/US-PM-5-6.md) | Decide the removal policy for orphaned test tasks | ✅ done | 1 |  | claude | US-PM-5-5 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-7](tasks/US-PM-5-7.md) | Add an audit check for criteria and test-task drift | ✅ done | 2 |  | claude | US-PM-5-5 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-8](tasks/US-PM-5-8.md) | Fix blank and trailing-whitespace criteria breeding duplicate test tasks | ✅ done | 2 |  | claude | — | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-5-9](tasks/US-PM-5-9.md) | Reconcile against archived test tasks so a live criterion is not duplicated | ✅ done | 2 |  | claude | US-PM-5-8 | [US-PM-5](stories/US-PM-5.md) |
| [US-PM-6-1](tasks/US-PM-6-1.md) | Test: Script walks Claude Code transcripts and joins tool calls to results by tool_use_id | ✅ done | 1 |  | claude | US-PM-6-6 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-2](tasks/US-PM-6-2.md) | Test: Reports hard errors and soft errors and malformed inputs separately | ✅ done | 1 |  | claude | US-PM-6-7 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-3](tasks/US-PM-6-3.md) | Test: Reports per-tool call counts and response bytes and consecutive-run lengths | ✅ done | 1 |  | claude | US-PM-6-8 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-4](tasks/US-PM-6-4.md) | Test: Match rate is asserted and the run fails loudly if it drops below 99 percent | ✅ done | 1 |  | claude | US-PM-6-6 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-5](tasks/US-PM-6-5.md) | Test: A baseline is captured and committed before other fixes land | ✅ done | 1 |  | claude | US-PM-6-9 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-6](tasks/US-PM-6-6.md) | Port the extraction pass into the repo | ✅ done | 2 |  | claude | — | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-7](tasks/US-PM-6-7.md) | Classify failures correctly across all three classes | ✅ done | 2 |  | claude | US-PM-6-6 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-8](tasks/US-PM-6-8.md) | Report call counts response bytes and run lengths | ✅ done | 1 |  | claude | US-PM-6-6 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-6-9](tasks/US-PM-6-9.md) | Capture and commit a pre-fix baseline | ✅ done | 1 |  | claude | US-PM-6-7, US-PM-6-8 | [US-PM-6](stories/US-PM-6.md) |
| [US-PM-7-1](tasks/US-PM-7-1.md) | Test: Releasing a task is expressible without an empty-string or null sentinel | ✅ done | 1 |  | claude | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-2](tasks/US-PM-7-2.md) | Test: Claiming uses compare-and-swap so two concurrent workers cannot both win | ✅ done | 1 |  | claude | US-PM-7-7 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-3](tasks/US-PM-7-3.md) | Test: Clearing depends_on and tags has an explicit affordance | ✅ done | 1 |  | claude | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-4](tasks/US-PM-7-4.md) | Test: pm-orchestrate SKILL.md no longer instructs the unspellable update | ✅ done | 1 |  | claude | US-PM-7-9 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-5](tasks/US-PM-7-5.md) | Test: Concurrent claim attempts are covered by a test | ✅ done | 1 |  | claude | US-PM-7-7 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-6](tasks/US-PM-7-6.md) | Design the claim and release contract | ✅ done | 2 |  | claude | — | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-7](tasks/US-PM-7-7.md) | Implement compare-and-swap claiming in the store | ✅ done | 3 |  | claude | US-PM-7-6 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-8](tasks/US-PM-7-8.md) | Implement release and the field-clear affordances | ✅ done | 3 |  | claude | US-PM-7-6 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-9](tasks/US-PM-7-9.md) | Rewrite the SKILL.md release instructions | ✅ done | 1 |  | claude | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-8-1](tasks/US-PM-8-1.md) | Test: Each of the four verdicts has a verb that sets status and outcome structurally | ✅ done | 1 |  | claude | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-2](tasks/US-PM-8-2.md) | Test: Outcome cannot be omitted on a terminal verdict | ✅ done | 1 |  | claude | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-3](tasks/US-PM-8-3.md) | Test: pm-orchestrate SKILL.md uses the verdict verbs throughout | ✅ done | 1 |  | claude | US-PM-8-9 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-4](tasks/US-PM-8-4.md) | Test: Existing pm_update status writes keep working for backwards compatibility | ✅ done | 1 |  | claude | US-PM-8-8 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-5](tasks/US-PM-8-5.md) | Test: Measured share of completions lacking a run-log entry drops to zero | ✅ done | 1 |  | claude | US-PM-8-9 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-6](tasks/US-PM-8-6.md) | Specify the four verdict verbs | ✅ done | 2 |  | claude | — | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-7](tasks/US-PM-8-7.md) | Implement the verdict verbs | ✅ done | 3 |  | claude | US-PM-8-6, US-PM-7-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-8](tasks/US-PM-8-8.md) | Keep generic pm_update working for compatibility | ✅ done | 2 |  | claude | — | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-9](tasks/US-PM-8-9.md) | Rewrite pm-orchestrate to use the verdict verbs | ✅ done | 2 |  | claude | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-9-1](tasks/US-PM-9-1.md) | Test: Run-log entries accept structured evidence separate from the prose note | ✅ done | 1 |  | claude | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-2](tasks/US-PM-9-2.md) | Test: Evidence records files changed and tests run with results and DoD items met | ✅ done | 1 |  | claude | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-3](tasks/US-PM-9-3.md) | Test: Completions carrying no evidence are detectable via query or audit | ✅ done | 1 |  | claude | US-PM-9-8 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-4](tasks/US-PM-9-4.md) | Test: pm-orchestrate records evidence structurally rather than in the note | ✅ done | 1 |  | claude | US-PM-9-9 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-5](tasks/US-PM-9-5.md) | Test: Median note length drops well below the cap | ✅ done | 1 |  | claude | US-PM-9-9 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-6](tasks/US-PM-9-6.md) | Design the evidence schema | ✅ done | 2 |  | claude | — | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-7](tasks/US-PM-9-7.md) | Store and return evidence on run-log entries | ✅ done | 3 |  | claude | US-PM-9-6 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-8](tasks/US-PM-9-8.md) | Detect completions with no evidence | ✅ done | 2 |  | claude | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-9](tasks/US-PM-9-9.md) | Update pm-orchestrate to record evidence structurally | ✅ done | 2 |  | claude | US-PM-8-9 | [US-PM-9](stories/US-PM-9.md) |
| [US-PRJ-1-1](tasks/US-PRJ-1-1.md) | Test: Pain points documented with concrete scenarios | ✅ done | — |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-2](tasks/US-PRJ-1-2.md) | Test: Current workflow steps listed end-to-end | ✅ done | — |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-3](tasks/US-PRJ-1-3.md) | Test: Failure modes catalogued with severity | ✅ done | — |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-4](tasks/US-PRJ-1-4.md) | Map current end-to-end hub git workflow steps | ✅ done | 1 |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-5](tasks/US-PRJ-1-5.md) | Document submodule branch tracking drift scenarios | ✅ done | 2 |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-6](tasks/US-PRJ-1-6.md) | Document multi-developer hub ref conflict scenarios | ✅ done | 2 |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-1-7](tasks/US-PRJ-1-7.md) | Compile audit into final document with recommendations | ✅ done | 1 |  | claude | — | [US-PRJ-1](stories/US-PRJ-1.md) |
| [US-PRJ-10-1](tasks/US-PRJ-10-1.md) | Test: Changesets group related changes across N repos | ✅ done | — |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-10](tasks/US-PRJ-10-10.md) | Register changeset MCP tools and CLI commands | ✅ done | 2 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-11](tasks/US-PRJ-10-11.md) | Write tests for changeset lifecycle | ✅ done | 3 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-2](tasks/US-PRJ-10-2.md) | Test: PRs created together with cross-references | ✅ done | — |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-3](tasks/US-PRJ-10-3.md) | Test: Hub refs update only when all changeset PRs merge | ✅ done | — |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-4](tasks/US-PRJ-10-4.md) | Test: Partial merge state is clearly reported | ✅ done | — |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-5](tasks/US-PRJ-10-5.md) | Test: Changeset status visible in git status dashboard | ✅ done | 2 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-6](tasks/US-PRJ-10-6.md) | Define changeset data model and storage | ✅ done | 3 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-7](tasks/US-PRJ-10-7.md) | Implement changeset PR creation with cross-references | ✅ done | 3 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-8](tasks/US-PRJ-10-8.md) | Implement changeset merge tracking and hub ref gating | ✅ done | 3 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-10-9](tasks/US-PRJ-10-9.md) | Add changeset status to git status dashboard | ✅ done | 2 |  | claude | — | [US-PRJ-10](stories/US-PRJ-10.md) |
| [US-PRJ-11-1](tasks/US-PRJ-11-1.md) | Test: Hub auto-rebases submodule ref updates on push conflict | ✅ done | 3 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-10](tasks/US-PRJ-11-10.md) | Write tests for hub conflict resolution | ✅ done | 3 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-2](tasks/US-PRJ-11-2.md) | Test: Fast-forwardable ref conflicts resolved automatically | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-3](tasks/US-PRJ-11-3.md) | Test: Non-fast-forward conflicts flagged clearly for manual resolution | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-4](tasks/US-PRJ-11-4.md) | Test: Push retried after successful rebase | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-5](tasks/US-PRJ-11-5.md) | Test: Ref update history logged for audit | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-6](tasks/US-PRJ-11-6.md) | Implement hub ref update logging for auditability | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-7](tasks/US-PRJ-11-7.md) | Implement auto-rebase for hub push conflicts | ✅ done | 3 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-8](tasks/US-PRJ-11-8.md) | Implement fast-forward check for conflicting submodule refs | ✅ done | 3 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-11-9](tasks/US-PRJ-11-9.md) | Wire auto-rebase into coordinated_push and push_hub | ✅ done | 2 |  | claude | — | [US-PRJ-11](stories/US-PRJ-11.md) |
| [US-PRJ-12-1](tasks/US-PRJ-12-1.md) | Test: TaskFrontmatter has tags field with default empty list | ✅ done | — |  | claude | — | [US-PRJ-12](stories/US-PRJ-12.md) |
| [US-PRJ-12-2](tasks/US-PRJ-12-2.md) | Test: IndexEntry includes optional tags field | ✅ done | — |  | claude | — | [US-PRJ-12](stories/US-PRJ-12.md) |
| [US-PRJ-12-3](tasks/US-PRJ-12-3.md) | Test: Existing task files without tags still load without errors | ✅ done | — |  | claude | — | [US-PRJ-12](stories/US-PRJ-12.md) |
| [US-PRJ-13-1](tasks/US-PRJ-13-1.md) | Test: pm_create_story accepts comma-separated tags parameter | ✅ done | — |  | claude | — | [US-PRJ-13](stories/US-PRJ-13.md) |
| [US-PRJ-13-2](tasks/US-PRJ-13-2.md) | Test: pm_create_task accepts comma-separated tags parameter | ✅ done | — |  | claude | — | [US-PRJ-13](stories/US-PRJ-13.md) |
| [US-PRJ-13-3](tasks/US-PRJ-13-3.md) | Test: pm_update exposes tags as explicit parameter for all item types | ✅ done | 2 |  | claude | — | [US-PRJ-13](stories/US-PRJ-13.md) |
| [US-PRJ-13-4](tasks/US-PRJ-13-4.md) | Test: store.create_story passes tags to frontmatter | ✅ done | 1 |  | claude | — | [US-PRJ-13](stories/US-PRJ-13.md) |
| [US-PRJ-13-5](tasks/US-PRJ-13-5.md) | Test: store.create_task and create_tasks pass tags to frontmatter | ✅ done | 1 |  | claude | — | [US-PRJ-13](stories/US-PRJ-13.md) |
| [US-PRJ-14-1](tasks/US-PRJ-14-1.md) | Test: pm_board accepts optional tag filter and only shows matching items | ✅ done | 2 |  | claude | — | [US-PRJ-14](stories/US-PRJ-14.md) |
| [US-PRJ-14-2](tasks/US-PRJ-14-2.md) | Test: pm_search supports tag-based filtering | ✅ done | 2 |  | claude | — | [US-PRJ-14](stories/US-PRJ-14.md) |
| [US-PRJ-14-3](tasks/US-PRJ-14-3.md) | Test: pm_active accepts optional tag filter | ✅ done | 2 |  | claude | — | [US-PRJ-14](stories/US-PRJ-14.md) |
| [US-PRJ-14-4](tasks/US-PRJ-14-4.md) | Test: Tags are included in search embedding text for semantic relevance | ✅ done | 1 |  | claude | — | [US-PRJ-14](stories/US-PRJ-14.md) |
| [US-PRJ-15-1](tasks/US-PRJ-15-1.md) | Test: CreateStoryRequest and CreateTaskRequest schemas include optional tags field | ✅ done | 2 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-15-2](tasks/US-PRJ-15-2.md) | Test: TaskResponse schema includes tags field | ✅ done | 1 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-15-3](tasks/US-PRJ-15-3.md) | Test: stories.html has tag input in create form and tags column in table | ✅ done | 2 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-15-4](tasks/US-PRJ-15-4.md) | Test: story_detail.html displays and allows editing tags | ✅ done | 2 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-15-5](tasks/US-PRJ-15-5.md) | Test: task_detail.html displays and allows editing tags | ✅ done | 2 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-15-6](tasks/US-PRJ-15-6.md) | Test: Web API routes pass tags through on create | ✅ done | 2 |  | claude | — | [US-PRJ-15](stories/US-PRJ-15.md) |
| [US-PRJ-16-1](tasks/US-PRJ-16-1.md) | Test: INDEX-EPICS.md table includes Tags column | ✅ done | 1 |  | claude | — | [US-PRJ-16](stories/US-PRJ-16.md) |
| [US-PRJ-16-2](tasks/US-PRJ-16-2.md) | Test: INDEX-STORIES.md table includes Tags column | ✅ done | 1 |  | claude | — | [US-PRJ-16](stories/US-PRJ-16.md) |
| [US-PRJ-16-3](tasks/US-PRJ-16-3.md) | Test: INDEX-TASKS.md table includes Tags column | ✅ done | 1 |  | claude | — | [US-PRJ-16](stories/US-PRJ-16.md) |
| [US-PRJ-16-4](tasks/US-PRJ-16-4.md) | Test: Tags rendered as comma-separated in index tables | ✅ done | 1 |  | claude | — | [US-PRJ-16](stories/US-PRJ-16.md) |
| [US-PRJ-17-1](tasks/US-PRJ-17-1.md) | Test: Log entry schema defined with all required fields | ✅ done | 1 |  | claude | — | [US-PRJ-17](stories/US-PRJ-17.md) |
| [US-PRJ-17-2](tasks/US-PRJ-17-2.md) | Test: Append-only writer function that atomically appends entries | ✅ done | 2 |  | claude | — | [US-PRJ-17](stories/US-PRJ-17.md) |
| [US-PRJ-17-3](tasks/US-PRJ-17-3.md) | Test: Storage format is JSONL (one JSON object per line) for easy parsing | ✅ done | 1 |  | claude | — | [US-PRJ-17](stories/US-PRJ-17.md) |
| [US-PRJ-17-4](tasks/US-PRJ-17-4.md) | Test: Entries include ISO 8601 timestamps | ✅ done | 1 |  | claude | — | [US-PRJ-17](stories/US-PRJ-17.md) |
| [US-PRJ-17-5](tasks/US-PRJ-17-5.md) | Test: File created automatically on first write | ✅ done | 1 |  | claude | — | [US-PRJ-17](stories/US-PRJ-17.md) |
| [US-PRJ-18-1](tasks/US-PRJ-18-1.md) | Test: All Store.create_* methods emit "created" log entries | ✅ done | 2 |  | claude | — | [US-PRJ-18](stories/US-PRJ-18.md) |
| [US-PRJ-18-2](tasks/US-PRJ-18-2.md) | Test: Store.update() emits "updated" entries with before/after field diffs | ✅ done | 2 |  | claude | — | [US-PRJ-18](stories/US-PRJ-18.md) |
| [US-PRJ-18-3](tasks/US-PRJ-18-3.md) | Test: Store.archive() emits "archived" entries | ✅ done | 2 |  | claude | — | [US-PRJ-18](stories/US-PRJ-18.md) |
| [US-PRJ-18-4](tasks/US-PRJ-18-4.md) | Test: Logging does not break existing functionality (transparent) | ✅ done | 2 |  | claude | — | [US-PRJ-18](stories/US-PRJ-18.md) |
| [US-PRJ-18-5](tasks/US-PRJ-18-5.md) | Test: Actor field populated when available (e.g. from git config or env var) | ✅ done | 1 |  | claude | — | [US-PRJ-18](stories/US-PRJ-18.md) |
| [US-PRJ-19-1](tasks/US-PRJ-19-1.md) | Test: pm_activity tool registered and callable via MCP | ✅ done | 2 |  | claude | — | [US-PRJ-19](stories/US-PRJ-19.md) |
| [US-PRJ-19-2](tasks/US-PRJ-19-2.md) | Test: Supports filtering by item_id and event_type and date range | ✅ done | 2 |  | claude | — | [US-PRJ-19](stories/US-PRJ-19.md) |
| [US-PRJ-19-3](tasks/US-PRJ-19-3.md) | Test: Returns formatted human-readable output with timestamps | ✅ done | 2 |  | claude | — | [US-PRJ-19](stories/US-PRJ-19.md) |
| [US-PRJ-19-4](tasks/US-PRJ-19-4.md) | Test: Handles empty or missing log file gracefully | ✅ done | 1 |  | claude | — | [US-PRJ-19](stories/US-PRJ-19.md) |
| [US-PRJ-19-5](tasks/US-PRJ-19-5.md) | Test: Pagination via limit/offset parameters | ✅ done | 1 |  | claude | — | [US-PRJ-19](stories/US-PRJ-19.md) |
| [US-PRJ-2-1](tasks/US-PRJ-2-1.md) | Test: Pre-push check validates submodule branch matches .gitmodules tracking | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-2](tasks/US-PRJ-2-2.md) | Test: Clear error message on branch mismatch showing expected vs actual | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-3](tasks/US-PRJ-2-3.md) | Test: Can be run standalone as a validation command | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-4](tasks/US-PRJ-2-4.md) | Implement validate_branches() core function in hub/registry.py | ✅ done | 3 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-5](tasks/US-PRJ-2-5.md) | Add validate-branches CLI command and MCP tool | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-6](tasks/US-PRJ-2-6.md) | Integrate pre-push validation into sync() and coordinated push path | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-2-7](tasks/US-PRJ-2-7.md) | Write tests for validate_branches using tmp_hub fixture | ✅ done | 2 |  | claude | — | [US-PRJ-2](stories/US-PRJ-2.md) |
| [US-PRJ-20-1](tasks/US-PRJ-20-1.md) | Test: Activity feed visible on web dashboard | ✅ done | 3 |  | claude | — | [US-PRJ-20](stories/US-PRJ-20.md) |
| [US-PRJ-20-2](tasks/US-PRJ-20-2.md) | Test: Entries show event type icon and item ID linked to detail view | ✅ done | 2 |  | claude | — | [US-PRJ-20](stories/US-PRJ-20.md) |
| [US-PRJ-20-3](tasks/US-PRJ-20-3.md) | Test: Relative timestamps displayed | ✅ done | 1 |  | claude | — | [US-PRJ-20](stories/US-PRJ-20.md) |
| [US-PRJ-20-4](tasks/US-PRJ-20-4.md) | Test: Feed loads recent entries with scroll/pagination | ✅ done | 2 |  | claude | — | [US-PRJ-20](stories/US-PRJ-20.md) |
| [US-PRJ-20-5](tasks/US-PRJ-20-5.md) | Test: API endpoint serves activity data as JSON | ✅ done | 2 |  | claude | — | [US-PRJ-20](stories/US-PRJ-20.md) |
| [US-PRJ-21-1](tasks/US-PRJ-21-1.md) | Test: depends_on field added to TaskFrontmatter with [] default | ✅ done | 2 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-2](tasks/US-PRJ-21-2.md) | Test: Field validator checks task ID format | ✅ done | 1 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-3](tasks/US-PRJ-21-3.md) | Test: Topological sort produces correct ordering for chains and diamonds | ✅ done | 2 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-4](tasks/US-PRJ-21-4.md) | Test: Cycle detection catches self-refs and multi-node cycles | ✅ done | 2 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-5](tasks/US-PRJ-21-5.md) | Test: Backward compatible with existing tasks lacking depends_on | ✅ done | 2 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-6](tasks/US-PRJ-21-6.md) | Test: All deps.py functions have unit tests | ✅ done | 2 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-7](tasks/US-PRJ-21-7.md) | Add depends_on field to TaskFrontmatter | ✅ done | 1 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-21-8](tasks/US-PRJ-21-8.md) | Create deps.py with graph algorithms | ✅ done | 5 |  | claude | — | [US-PRJ-21](stories/US-PRJ-21.md) |
| [US-PRJ-22-1](tasks/US-PRJ-22-1.md) | Test: create_task accepts depends_on param and validates | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-2](tasks/US-PRJ-22-2.md) | Test: create_tasks batch supports depends_on per entry with cycle check | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-3](tasks/US-PRJ-22-3.md) | Test: update validates depends_on for tasks and rejects cycles | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-4](tasks/US-PRJ-22-4.md) | Test: Invalid deps (self-ref or non-sibling or cycle) raise ValueError | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-5](tasks/US-PRJ-22-5.md) | Test: Store tests cover all validation cases | ✅ done | 3 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-6](tasks/US-PRJ-22-6.md) | Wire depends_on through create_task | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-7](tasks/US-PRJ-22-7.md) | Wire depends_on through create_tasks batch | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-22-8](tasks/US-PRJ-22-8.md) | Wire depends_on through update | ✅ done | 2 |  | claude | — | [US-PRJ-22](stories/US-PRJ-22.md) |
| [US-PRJ-23-1](tasks/US-PRJ-23-1.md) | Test: Tasks with incomplete deps appear in not_ready on board | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-2](tasks/US-PRJ-23-2.md) | Test: Board available section sorted by topological order within each story | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-3](tasks/US-PRJ-23-3.md) | Test: pm_grab returns error when task has incomplete dependencies | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-4](tasks/US-PRJ-23-4.md) | Test: pm_grab includes dependency_status in response showing dep titles and statuses | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-5](tasks/US-PRJ-23-5.md) | Test: Readiness blocker message lists specific incomplete dep IDs | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-6](tasks/US-PRJ-23-6.md) | Add dependency blocker to readiness checks | ✅ done | 2 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-7](tasks/US-PRJ-23-7.md) | Add topological sort to pm_board ordering | ✅ done | 3 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-23-8](tasks/US-PRJ-23-8.md) | Add dependency_status to pm_grab response | ✅ done | 1 |  | claude | — | [US-PRJ-23](stories/US-PRJ-23.md) |
| [US-PRJ-24-1](tasks/US-PRJ-24-1.md) | Test: pm_create_task accepts comma-separated depends_on | ✅ done | 1 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-2](tasks/US-PRJ-24-2.md) | Test: pm_update accepts comma-separated depends_on for tasks | ✅ done | 2 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-3](tasks/US-PRJ-24-3.md) | Test: pm_create_tasks docstring documents depends_on key | ✅ done | 1 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-4](tasks/US-PRJ-24-4.md) | Test: Web CreateTaskRequest and UpdateItemRequest include depends_on | ✅ done | 2 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-5](tasks/US-PRJ-24-5.md) | Test: Web TaskResponse includes depends_on | ✅ done | 1 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-6](tasks/US-PRJ-24-6.md) | Test: Server tests cover MCP tool parameter parsing | ✅ done | 2 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-7](tasks/US-PRJ-24-7.md) | Add depends_on to MCP tool signatures | ✅ done | 2 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-24-8](tasks/US-PRJ-24-8.md) | Add depends_on to web API schemas and routes | ✅ done | 1 |  | claude | — | [US-PRJ-24](stories/US-PRJ-24.md) |
| [US-PRJ-25-1](tasks/US-PRJ-25-1.md) | Test: Scoper guidance includes depends_on in rules and template | ✅ done | 2 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-2](tasks/US-PRJ-25-2.md) | Test: Audit detects dependency cycles as error | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-3](tasks/US-PRJ-25-3.md) | Test: Audit detects orphaned dependency references as warning | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-4](tasks/US-PRJ-25-4.md) | Test: Index task table includes Depends On column | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-5](tasks/US-PRJ-25-5.md) | Test: All three modules updated with minimal changes | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-6](tasks/US-PRJ-25-6.md) | Update scoper guidance with depends_on | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-7](tasks/US-PRJ-25-7.md) | Add dependency audit checks | ✅ done | 2 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-25-8](tasks/US-PRJ-25-8.md) | Add Depends On column to indexer | ✅ done | 1 |  | claude | — | [US-PRJ-25](stories/US-PRJ-25.md) |
| [US-PRJ-26-1](tasks/US-PRJ-26-1.md) | Test: Store holds parsed frontmatter in memory after first load | ✅ done | 2 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-10](tasks/US-PRJ-26-10.md) | Test: Cache is per-Store instance with module-level shared dict | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-11](tasks/US-PRJ-26-11.md) | Test: Sub-second response for listing tasks of a story with 50+ tasks | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-2](tasks/US-PRJ-26-2.md) | Test: Subsequent list_tasks/list_stories/list_epics calls return from cache not disk | ✅ done | 2 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-3](tasks/US-PRJ-26-3.md) | Test: Cache is per-Store instance with a module-level shared cache dict | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-4](tasks/US-PRJ-26-4.md) | Test: Sub-second response for listing tasks of a story with 50+ tasks | ✅ done | 2 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-5](tasks/US-PRJ-26-5.md) | Add module-level cache dict and cache-aware list methods to Store | ✅ done | 3 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-6](tasks/US-PRJ-26-6.md) | Add cache-aware get methods to Store | ✅ done | 2 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-7](tasks/US-PRJ-26-7.md) | Add cache stats and clear_cache() utility | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-8](tasks/US-PRJ-26-8.md) | Test: Store holds parsed frontmatter in memory after first load | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-26-9](tasks/US-PRJ-26-9.md) | Test: Subsequent list calls return from cache not disk | ✅ done | 1 |  | claude | — | [US-PRJ-26](stories/US-PRJ-26.md) |
| [US-PRJ-27-1](tasks/US-PRJ-27-1.md) | Test: All Store mutation methods (create_story/task/epic update archive) invalidate or update the relevant cache entries | ✅ done | — |  | — | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-10](tasks/US-PRJ-27-10.md) | Test: No stale data after any mutation sequence | ✅ done | 1 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-2](tasks/US-PRJ-27-2.md) | Test: Cache invalidation is surgical — only affected entries are evicted not the whole cache | ✅ done | — |  | — | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-3](tasks/US-PRJ-27-3.md) | Test: write_index reuses cached data instead of re-reading from disk | ✅ done | — |  | — | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-4](tasks/US-PRJ-27-4.md) | Test: No stale data observed after any mutation sequence | ✅ done | — |  | — | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-5](tasks/US-PRJ-27-5.md) | Add cache invalidation to all Store write methods | ✅ done | 3 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-6](tasks/US-PRJ-27-6.md) | Make write_index and build_index use cached data | ✅ done | 1 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-7](tasks/US-PRJ-27-7.md) | Test: All mutation methods invalidate/update cache entries | ✅ done | 1 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-8](tasks/US-PRJ-27-8.md) | Test: Cache invalidation is surgical, not full-clear | ✅ done | 1 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-27-9](tasks/US-PRJ-27-9.md) | Test: write_index reuses cached data | ✅ done | 1 |  | claude | — | [US-PRJ-27](stories/US-PRJ-27.md) |
| [US-PRJ-28-1](tasks/US-PRJ-28-1.md) | Test: Server._store() returns a cached Store instance per project instead of creating a new one each call | ✅ done | 1 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-10](tasks/US-PRJ-28-10.md) | Test: Cache hit behavior across sequential tool calls | ✅ done | 1 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-2](tasks/US-PRJ-28-2.md) | Test: Cache persists across MCP tool invocations within the same server process | ✅ done | 2 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-3](tasks/US-PRJ-28-3.md) | Test: Memory usage stays bounded — cache doesn't grow unbounded with archived items | ✅ done | 2 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-4](tasks/US-PRJ-28-4.md) | Test: Tests verify cache hit behavior across multiple sequential tool calls | ✅ done | 2 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-5](tasks/US-PRJ-28-5.md) | Convert Server._store() to return cached Store instances | ✅ done | 2 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-6](tasks/US-PRJ-28-6.md) | Add cache eviction policy for bounded memory | ✅ done | 2 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-7](tasks/US-PRJ-28-7.md) | Test: Server._store() returns cached Store instance per project | ✅ done | 1 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-8](tasks/US-PRJ-28-8.md) | Test: Cache persists across MCP tool invocations | ✅ done | 1 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-28-9](tasks/US-PRJ-28-9.md) | Test: Memory stays bounded with archived items | ✅ done | 1 |  | claude | — | [US-PRJ-28](stories/US-PRJ-28.md) |
| [US-PRJ-29-1](tasks/US-PRJ-29-1.md) | Test: store.py _check_dependency_cycles uses deps.py detect_cycle() | ✅ done | 1 |  | claude | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-2](tasks/US-PRJ-29-2.md) | Test: Cycle errors show full path (A -> B -> C -> A) everywhere | ✅ done | — |  | — | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-3](tasks/US-PRJ-29-3.md) | Test: validate_dependencies() either removed or integrated into store layer | ✅ done | — |  | — | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-4](tasks/US-PRJ-29-4.md) | Test: All existing tests pass | ✅ done | — |  | — | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-5](tasks/US-PRJ-29-5.md) | Test: No new test regressions | ✅ done | — |  | — | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-6](tasks/US-PRJ-29-6.md) | Refactor store.py _check_dependency_cycles to use deps.detect_cycle() | ✅ done | 2 |  | claude | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-7](tasks/US-PRJ-29-7.md) | Remove or integrate validate_dependencies() from deps.py | ✅ done | 1 |  | claude | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-29-8](tasks/US-PRJ-29-8.md) | Verify cycle error messages show full path end-to-end | ✅ done | 1 |  | claude | — | [US-PRJ-29](stories/US-PRJ-29.md) |
| [US-PRJ-3-1](tasks/US-PRJ-3-1.md) | Test: pm_commit tool commits .project/ changes with auto-generated message | ✅ done | 3 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-2](tasks/US-PRJ-3-2.md) | Test: pm_push tool pushes with branch validation | ✅ done | 3 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-3](tasks/US-PRJ-3-3.md) | Test: Hub vs subproject scope is configurable | ✅ done | 2 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-4](tasks/US-PRJ-3-4.md) | Test: Integrates with existing MCP server | ✅ done | 2 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-5](tasks/US-PRJ-3-5.md) | Implement pm_commit() for hub and subproject PM data | ✅ done | 3 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-6](tasks/US-PRJ-3-6.md) | Implement pm_push() with scope and validation | ✅ done | 2 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-7](tasks/US-PRJ-3-7.md) | Register pm_commit and pm_push as MCP tools and CLI commands | ✅ done | 2 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-3-8](tasks/US-PRJ-3-8.md) | Write tests for pm_commit and pm_push | ✅ done | 2 |  | claude | — | [US-PRJ-3](stories/US-PRJ-3.md) |
| [US-PRJ-30-1](tasks/US-PRJ-30-1.md) | Test: load_config() uses module-level cache | ✅ done | 1 |  | claude | US-PRJ-30-6 | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-2](tasks/US-PRJ-30-2.md) | Test: Cache has TTL or explicit invalidation on config write | ✅ done | 1 |  | claude | US-PRJ-30-7 | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-3](tasks/US-PRJ-30-3.md) | Test: Repeated calls in same process return cached result | ✅ done | 1 |  | claude | US-PRJ-30-6 | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-4](tasks/US-PRJ-30-4.md) | Test: _save_config() invalidates the cache | ✅ done | 1 |  | claude | US-PRJ-30-7 | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-5](tasks/US-PRJ-30-5.md) | Test: All existing tests pass | ✅ done | 1 |  | claude | US-PRJ-30-6, US-PRJ-30-7, US-PRJ-30-8 | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-6](tasks/US-PRJ-30-6.md) | Add module-level config cache to config.py | ✅ done | 1 |  | claude | — | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-7](tasks/US-PRJ-30-7.md) | Invalidate config cache on _save_config() | ✅ done | 1 |  | claude | — | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-30-8](tasks/US-PRJ-30-8.md) | Add tests for config cache hit and invalidation | ✅ done | 1 |  | claude | — | [US-PRJ-30](stories/US-PRJ-30.md) |
| [US-PRJ-31-1](tasks/US-PRJ-31-1.md) | Test: pm_board output includes note distinguishing blocked vs not_ready | ⚪ todo | — |  | — | — | [US-PRJ-31](stories/US-PRJ-31.md) |
| [US-PRJ-31-2](tasks/US-PRJ-31-2.md) | Test: Board tool docstring clarifies the distinction | ⚪ todo | — |  | — | — | [US-PRJ-31](stories/US-PRJ-31.md) |
| [US-PRJ-31-3](tasks/US-PRJ-31-3.md) | Test: Forward references in batch create are documented in pm_create_tasks docstring | ⚪ todo | — |  | — | — | [US-PRJ-31](stories/US-PRJ-31.md) |
| [US-PRJ-31-4](tasks/US-PRJ-31-4.md) | Add blocked vs not_ready note to pm_board output | ⚪ todo | 1 |  | — | — | [US-PRJ-31](stories/US-PRJ-31.md) |
| [US-PRJ-31-5](tasks/US-PRJ-31-5.md) | Document forward references and blocked semantics in docstrings | ⚪ todo | 1 |  | — | — | [US-PRJ-31](stories/US-PRJ-31.md) |
| [US-PRJ-32-1](tasks/US-PRJ-32-1.md) | Test: pm_board avoids per-task get_task() body reads where possible | ✅ done | — |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-10](tasks/US-PRJ-32-10.md) | Wire pre-loaded context through pm_board readiness loop | ✅ done | 1 |  | — | US-PRJ-32-8, US-PRJ-32-9 | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-11](tasks/US-PRJ-32-11.md) | Add performance test for 100+ task board | ✅ done | 1 |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-2](tasks/US-PRJ-32-2.md) | Test: Readiness checks use pre-loaded story and sibling data instead of per-task lookups | ✅ done | — |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-3](tasks/US-PRJ-32-3.md) | Test: Total file I/O for 100 tasks reduced by at least 50% | ✅ done | — |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-4](tasks/US-PRJ-32-4.md) | Test: All board tests pass with same output | ✅ done | — |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-5](tasks/US-PRJ-32-5.md) | Test: Performance test added for 100+ task board | ✅ done | — |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-6](tasks/US-PRJ-32-6.md) | Pre-load all task bodies in pm_board instead of per-task get_task() | ✅ done | 2 |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-7](tasks/US-PRJ-32-7.md) | Refactor check_readiness to accept pre-loaded context | ✅ done | 2 |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-8](tasks/US-PRJ-32-8.md) | Pre-load all task bodies in pm_board instead of per-task get_task() | ✅ done | 2 |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-32-9](tasks/US-PRJ-32-9.md) | Refactor check_readiness to accept pre-loaded context | ✅ done | 2 |  | — | — | [US-PRJ-32](stories/US-PRJ-32.md) |
| [US-PRJ-33-1](tasks/US-PRJ-33-1.md) | Test: pm_epic loads all tasks once then filters by story_id in memory | ✅ done | — |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-33-2](tasks/US-PRJ-33-2.md) | Test: File I/O reduced from N list_tasks calls to 1 | ✅ done | — |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-33-3](tasks/US-PRJ-33-3.md) | Test: All epic tests pass | ✅ done | — |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-33-4](tasks/US-PRJ-33-4.md) | Test: Performance acceptable for epics with 20+ stories | ✅ done | — |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-33-5](tasks/US-PRJ-33-5.md) | Refactor pm_epic to load all tasks once then filter by story_id | ✅ done | 2 |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-33-6](tasks/US-PRJ-33-6.md) | Add performance test for epic with 20+ stories | ✅ done | 1 |  | — | — | [US-PRJ-33](stories/US-PRJ-33.md) |
| [US-PRJ-34-1](tasks/US-PRJ-34-1.md) | Test: rollup() uses ThreadPoolExecutor for parallel project scanning | ⚪ todo | — |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-34-2](tasks/US-PRJ-34-2.md) | Test: Max workers capped similar to git_status_all (min(projects 16)) | ⚪ todo | — |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-34-3](tasks/US-PRJ-34-3.md) | Test: Results identical to sequential version | ⚪ todo | — |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-34-4](tasks/US-PRJ-34-4.md) | Test: Performance improvement measurable on 5+ project hubs | ⚪ todo | — |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-34-5](tasks/US-PRJ-34-5.md) | Refactor rollup() to use ThreadPoolExecutor | ⚪ todo | 2 |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-34-6](tasks/US-PRJ-34-6.md) | Add test verifying parallel rollup matches sequential results | ⚪ todo | 1 |  | — | — | [US-PRJ-34](stories/US-PRJ-34.md) |
| [US-PRJ-35-1](tasks/US-PRJ-35-1.md) | Test: Search uses indexed vector lookup instead of full table scan | ⚪ todo | — |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-2](tasks/US-PRJ-35-2.md) | Test: Performance acceptable for 5000+ items | ⚪ todo | — |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-3](tasks/US-PRJ-35-3.md) | Test: Backward compatible with existing embeddings.db | ⚪ todo | — |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-4](tasks/US-PRJ-35-4.md) | Test: FAISS or similar lightweight solution (no heavy external DB) | ⚪ todo | — |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-5](tasks/US-PRJ-35-5.md) | Evaluate and select vector index library | ⚪ todo | 1 |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-6](tasks/US-PRJ-35-6.md) | Implement indexed vector search in embeddings.py | ⚪ todo | 3 |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-35-7](tasks/US-PRJ-35-7.md) | Add benchmark test for 5000+ item search | ⚪ todo | 1 |  | — | — | [US-PRJ-35](stories/US-PRJ-35.md) |
| [US-PRJ-36-1](tasks/US-PRJ-36-1.md) | Test: _cache_stats invalidations counter only tracks true invalidations | ⚪ todo | — |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-2](tasks/US-PRJ-36-2.md) | Test: Changesets cached following same pattern as stories/epics/tasks | ⚪ todo | — |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-3](tasks/US-PRJ-36-3.md) | Test: Single-threaded cache assumption documented in store.py | ⚪ todo | — |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-4](tasks/US-PRJ-36-4.md) | Test: Duplicate depends_on entries deduplicated in model validator | ⚪ todo | — |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-5](tasks/US-PRJ-36-5.md) | Fix _cache_stats counter naming and tracking | ⚪ todo | 1 |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-6](tasks/US-PRJ-36-6.md) | Add changeset caching following stories/epics/tasks pattern | ⚪ todo | 1 |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-7](tasks/US-PRJ-36-7.md) | Document single-threaded cache assumption in store.py | ⚪ todo | 1 |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-36-8](tasks/US-PRJ-36-8.md) | Add depends_on deduplication in TaskFrontmatter validator | ⚪ todo | 1 |  | — | — | [US-PRJ-36](stories/US-PRJ-36.md) |
| [US-PRJ-37-1](tasks/US-PRJ-37-1.md) | Test: Deep copies removed from all list/get cache returns | ✅ done | 2 |  | claude | — | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-37-2](tasks/US-PRJ-37-2.md) | Test: Benchmark shows 10x+ improvement for 1000-item lists | ✅ done | 2 |  | claude | — | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-37-3](tasks/US-PRJ-37-3.md) | Test: No mutation side effects from removing deep copy | ✅ done | 1 |  | claude | US-PRJ-37-5 | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-37-4](tasks/US-PRJ-37-4.md) | Test: Regression tests confirm cache integrity | ✅ done | 1 |  | claude | US-PRJ-37-6 | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-37-5](tasks/US-PRJ-37-5.md) | Audit cached-read call sites for caller mutation risk | ✅ done | 2 |  | claude | — | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-37-6](tasks/US-PRJ-37-6.md) | Add cache-integrity regression tests for list/get returns | ✅ done | 3 |  | claude | US-PRJ-37-5 | [US-PRJ-37](stories/US-PRJ-37.md) |
| [US-PRJ-38-1](tasks/US-PRJ-38-1.md) | Test: Vectors batch-decoded into numpy array once | ✅ done | 1 |  | claude | US-PRJ-38-5 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-2](tasks/US-PRJ-38-2.md) | Test: Cosine similarity uses np.dot(Q; all_vecs.T) instead of loop | ✅ done | 1 |  | claude | US-PRJ-38-6 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-3](tasks/US-PRJ-38-3.md) | Test: First search lazy-loads and caches decoded vectors | ✅ done | 1 |  | claude | US-PRJ-38-5, US-PRJ-38-7 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-4](tasks/US-PRJ-38-4.md) | Test: 10x+ improvement for 1000-item projects | ✅ done | 1 |  | claude | US-PRJ-38-6 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-5](tasks/US-PRJ-38-5.md) | Batch-decode embedding rows into one cached numpy matrix | ✅ done | 2 |  | claude | — | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-6](tasks/US-PRJ-38-6.md) | Replace the per-row similarity loop with a vectorised top-k | ✅ done | 2 |  | claude | US-PRJ-38-5 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-38-7](tasks/US-PRJ-38-7.md) | Invalidate the cached vector matrix on index writes and stale databases | ✅ done | 1 |  | claude | US-PRJ-38-5 | [US-PRJ-38](stories/US-PRJ-38.md) |
| [US-PRJ-39-1](tasks/US-PRJ-39-1.md) | Test: Secondary dict index maintained alongside cache list | ⚪ todo | — |  | — | — | [US-PRJ-39](stories/US-PRJ-39.md) |
| [US-PRJ-39-2](tasks/US-PRJ-39-2.md) | Test: Cache update/invalidation is O(1) by ID | ⚪ todo | — |  | — | — | [US-PRJ-39](stories/US-PRJ-39.md) |
| [US-PRJ-39-3](tasks/US-PRJ-39-3.md) | Test: Index stays consistent across append/update/invalidate operations | ⚪ todo | — |  | — | — | [US-PRJ-39](stories/US-PRJ-39.md) |
| [US-PRJ-4-1](tasks/US-PRJ-4-1.md) | Test: Single command pushes across hub + N subprojects | ✅ done | 3 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-10](tasks/US-PRJ-4-10.md) | Write tests for coordinated push workflow | ✅ done | 3 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-2](tasks/US-PRJ-4-2.md) | Test: Validates branch alignment before any push | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-3](tasks/US-PRJ-4-3.md) | Test: Subprojects pushed before hub ref update | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-4](tasks/US-PRJ-4-4.md) | Test: Clear report of what succeeded/failed | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-5](tasks/US-PRJ-4-5.md) | Test: No silent partial pushes | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-6](tasks/US-PRJ-4-6.md) | Implement pre-push preflight check aggregating all validations | ✅ done | 3 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-7](tasks/US-PRJ-4-7.md) | Implement push_subprojects() for ordered per-project push | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-8](tasks/US-PRJ-4-8.md) | Implement push_hub() for hub ref commit and push | ✅ done | 2 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-4-9](tasks/US-PRJ-4-9.md) | Implement coordinated_push() orchestrator and CLI command | ✅ done | 3 |  | claude | — | [US-PRJ-4](stories/US-PRJ-4.md) |
| [US-PRJ-40-1](tasks/US-PRJ-40-1.md) | Test: Dirty flag tracks which item types changed since last rebuild | ⚪ todo | — |  | — | — | [US-PRJ-40](stories/US-PRJ-40.md) |
| [US-PRJ-40-2](tasks/US-PRJ-40-2.md) | Test: Only affected markdown index files are regenerated | ⚪ todo | — |  | — | — | [US-PRJ-40](stories/US-PRJ-40.md) |
| [US-PRJ-40-3](tasks/US-PRJ-40-3.md) | Test: Full rebuild still available as fallback | ⚪ todo | — |  | — | — | [US-PRJ-40](stories/US-PRJ-40.md) |
| [US-PRJ-40-4](tasks/US-PRJ-40-4.md) | Test: Hub README rebuild skips unchanged subprojects | ⚪ todo | — |  | — | — | [US-PRJ-40](stories/US-PRJ-40.md) |
| [US-PRJ-41-1](tasks/US-PRJ-41-1.md) | Test: Status collection uses max 2 git calls per project instead of 4+ | ⚪ todo | — |  | — | — | [US-PRJ-41](stories/US-PRJ-41.md) |
| [US-PRJ-41-2](tasks/US-PRJ-41-2.md) | Test: ThreadPoolExecutor still used for parallelism | ⚪ todo | — |  | — | — | [US-PRJ-41](stories/US-PRJ-41.md) |
| [US-PRJ-41-3](tasks/US-PRJ-41-3.md) | Test: Results match current output format | ⚪ todo | — |  | — | — | [US-PRJ-41](stories/US-PRJ-41.md) |
| [US-PRJ-42-1](tasks/US-PRJ-42-1.md) | Test: All stories/tasks/epics loaded once at audit start | ⚪ todo | — |  | — | — | [US-PRJ-42](stories/US-PRJ-42.md) |
| [US-PRJ-42-2](tasks/US-PRJ-42-2.md) | Test: 15 checks run against pre-loaded data | ⚪ todo | — |  | — | — | [US-PRJ-42](stories/US-PRJ-42.md) |
| [US-PRJ-42-3](tasks/US-PRJ-42-3.md) | Test: No repeated list_stories or get_story calls | ⚪ todo | — |  | — | — | [US-PRJ-42](stories/US-PRJ-42.md) |
| [US-PRJ-42-4](tasks/US-PRJ-42-4.md) | Test: Duplicate doc check logic extracted to shared function | ⚪ todo | — |  | — | — | [US-PRJ-42](stories/US-PRJ-42.md) |
| [US-PRJ-43-1](tasks/US-PRJ-43-1.md) | Test: pm_board uses list_all or cache for task bodies instead of per-task get | ✅ done | 1 |  | claude | US-PRJ-43-5, US-PRJ-43-6 | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-2](tasks/US-PRJ-43-2.md) | Test: pm_epic pre-fetches all tasks and partitions by story_id locally | ✅ done | 1 |  | claude | US-PRJ-43-7 | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-3](tasks/US-PRJ-43-3.md) | Test: pm_search tag filter batch-loads metadata instead of individual gets | ✅ done | 1 |  | claude | US-PRJ-43-8 | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-4](tasks/US-PRJ-43-4.md) | Test: pm_active removes redundant list_stories call on line 252 | ✅ done | 1 |  | claude | US-PRJ-43-8 | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-5](tasks/US-PRJ-43-5.md) | Load task bodies once in pm_board instead of get_task per task | ✅ done | 2 |  | claude | — | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-6](tasks/US-PRJ-43-6.md) | Let check_readiness accept pre-loaded context and pass it from pm_board | ✅ done | 2 |  | claude | US-PRJ-43-5 | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-7](tasks/US-PRJ-43-7.md) | Partition one list_tasks call by story_id in pm_epic | ✅ done | 1 |  | claude | — | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-43-8](tasks/US-PRJ-43-8.md) | Batch the pm_search tag filter and drop the redundant list_stories in pm_active | ✅ done | 1 |  | claude | — | [US-PRJ-43](stories/US-PRJ-43.md) |
| [US-PRJ-44-1](tasks/US-PRJ-44-1.md) | Test: pm_batch_update accepts JSON array of update dicts | ✅ done | — |  | — | — | [US-PRJ-44](stories/US-PRJ-44.md) |
| [US-PRJ-44-2](tasks/US-PRJ-44-2.md) | Test: Each update applied via store.update with validation | ✅ done | — |  | — | — | [US-PRJ-44](stories/US-PRJ-44.md) |
| [US-PRJ-44-3](tasks/US-PRJ-44-3.md) | Test: Single auto-commit for entire batch | ✅ done | — |  | — | — | [US-PRJ-44](stories/US-PRJ-44.md) |
| [US-PRJ-44-4](tasks/US-PRJ-44-4.md) | Test: Returns list of updated items or per-item errors | ✅ done | — |  | — | — | [US-PRJ-44](stories/US-PRJ-44.md) |
| [US-PRJ-44-5](tasks/US-PRJ-44-5.md) | Test: Proper MCP annotations (destructive=false) | ✅ done | — |  | — | — | [US-PRJ-44](stories/US-PRJ-44.md) |
| [US-PRJ-45-1](tasks/US-PRJ-45-1.md) | Test: pm_batch_archive accepts comma-separated or list of IDs | ✅ done | — |  | — | — | [US-PRJ-45](stories/US-PRJ-45.md) |
| [US-PRJ-45-2](tasks/US-PRJ-45-2.md) | Test: Archives all items with single commit | ✅ done | — |  | — | — | [US-PRJ-45](stories/US-PRJ-45.md) |
| [US-PRJ-45-3](tasks/US-PRJ-45-3.md) | Test: Reports per-item success/failure | ✅ done | — |  | — | — | [US-PRJ-45](stories/US-PRJ-45.md) |
| [US-PRJ-45-4](tasks/US-PRJ-45-4.md) | Test: Proper destructive=true annotation | ✅ done | — |  | — | — | [US-PRJ-45](stories/US-PRJ-45.md) |
| [US-PRJ-46-1](tasks/US-PRJ-46-1.md) | Test: _next_task_id uses directory glob count instead of list_tasks | ⚪ todo | — |  | — | — | [US-PRJ-46](stories/US-PRJ-46.md) |
| [US-PRJ-46-2](tasks/US-PRJ-46-2.md) | Test: Batch create_tasks generates IDs without N list_tasks calls | ⚪ todo | — |  | — | — | [US-PRJ-46](stories/US-PRJ-46.md) |
| [US-PRJ-46-3](tasks/US-PRJ-46-3.md) | Test: Existing tests still pass | ⚪ todo | — |  | — | — | [US-PRJ-46](stories/US-PRJ-46.md) |
| [US-PRJ-47-1](tasks/US-PRJ-47-1.md) | Test: PR commands use subprocess list args or shlex.quote for all user input | ✅ done | 1 |  | claude | US-PRJ-47-5 | [US-PRJ-47](stories/US-PRJ-47.md) |
| [US-PRJ-47-2](tasks/US-PRJ-47-2.md) | Test: Cross-ref block renders newlines correctly in GitHub | ✅ done | 1 |  | claude | US-PRJ-47-5 | [US-PRJ-47](stories/US-PRJ-47.md) |
| [US-PRJ-47-3](tasks/US-PRJ-47-3.md) | Test: Titles and descriptions with quotes/backticks/semicolons are safe | ✅ done | 1 |  | claude | US-PRJ-47-5 | [US-PRJ-47](stories/US-PRJ-47.md) |
| [US-PRJ-47-4](tasks/US-PRJ-47-4.md) | Test: Tests cover special character edge cases | ✅ done | 1 |  | claude | US-PRJ-47-5 | [US-PRJ-47](stories/US-PRJ-47.md) |
| [US-PRJ-47-5](tasks/US-PRJ-47-5.md) | Build changeset PR commands from argv lists with shlex quoting | ✅ done | 2 | security, changesets | claude | — | [US-PRJ-47](stories/US-PRJ-47.md) |
| [US-PRJ-48-1](tasks/US-PRJ-48-1.md) | Test: Specific exception types caught where appropriate (FileNotFoundError; ValueError; etc.) | ⚪ todo | — |  | — | — | [US-PRJ-48](stories/US-PRJ-48.md) |
| [US-PRJ-48-2](tasks/US-PRJ-48-2.md) | Test: Error responses include error_code and message fields | ⚪ todo | — |  | — | — | [US-PRJ-48](stories/US-PRJ-48.md) |
| [US-PRJ-48-3](tasks/US-PRJ-48-3.md) | Test: Generic catch-all still exists as fallback | ⚪ todo | — |  | — | — | [US-PRJ-48](stories/US-PRJ-48.md) |
| [US-PRJ-48-4](tasks/US-PRJ-48-4.md) | Test: Existing error behavior preserved for backwards compatibility | ⚪ todo | — |  | — | — | [US-PRJ-48](stories/US-PRJ-48.md) |
| [US-PRJ-49-1](tasks/US-PRJ-49-1.md) | Test: pm_fix_malformed marked destructiveHint=True | ⚪ todo | — |  | — | — | [US-PRJ-49](stories/US-PRJ-49.md) |
| [US-PRJ-49-2](tasks/US-PRJ-49-2.md) | Test: pm_restore marked destructiveHint=True | ⚪ todo | — |  | — | — | [US-PRJ-49](stories/US-PRJ-49.md) |
| [US-PRJ-49-3](tasks/US-PRJ-49-3.md) | Test: pm_push and pm_push_all marked destructiveHint=True | ⚪ todo | — |  | — | — | [US-PRJ-49](stories/US-PRJ-49.md) |
| [US-PRJ-49-4](tasks/US-PRJ-49-4.md) | Test: All other tools reviewed for correct annotations | ⚪ todo | — |  | — | — | [US-PRJ-49](stories/US-PRJ-49.md) |
| [US-PRJ-5-1](tasks/US-PRJ-5-1.md) | Test: Config option to enable/disable auto-commit | ✅ done | 3 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-2](tasks/US-PRJ-5-2.md) | Test: Auto-generated commit messages from PM operations | ✅ done | 2 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-3](tasks/US-PRJ-5-3.md) | Test: Only commits .project/ files touched by the mutation | ✅ done | 2 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-4](tasks/US-PRJ-5-4.md) | Test: Does not auto-push | ✅ done | 2 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-5](tasks/US-PRJ-5-5.md) | Add auto_commit config option to ProjectConfig | ✅ done | 1 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-6](tasks/US-PRJ-5-6.md) | Add auto-commit hook into store.py mutation methods | ✅ done | 3 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-5-7](tasks/US-PRJ-5-7.md) | Write tests for auto-commit behavior | ✅ done | 2 |  | claude | — | [US-PRJ-5](stories/US-PRJ-5.md) |
| [US-PRJ-50-1](tasks/US-PRJ-50-1.md) | Test: Story ID regex enforces US-PREFIX-N pattern | ⚪ todo | — |  | — | — | [US-PRJ-50](stories/US-PRJ-50.md) |
| [US-PRJ-50-2](tasks/US-PRJ-50-2.md) | Test: Task ID regex enforces US-PREFIX-N-N pattern | ⚪ todo | — |  | — | — | [US-PRJ-50](stories/US-PRJ-50.md) |
| [US-PRJ-50-3](tasks/US-PRJ-50-3.md) | Test: Epic ID regex enforces EPIC-PREFIX-N pattern | ⚪ todo | — |  | — | — | [US-PRJ-50](stories/US-PRJ-50.md) |
| [US-PRJ-50-4](tasks/US-PRJ-50-4.md) | Test: Changeset ID regex enforces CS-PREFIX-N pattern | ⚪ todo | — |  | — | — | [US-PRJ-50](stories/US-PRJ-50.md) |
| [US-PRJ-50-5](tasks/US-PRJ-50-5.md) | Test: Existing valid IDs all pass new validation | ⚪ todo | — |  | — | — | [US-PRJ-50](stories/US-PRJ-50.md) |
| [US-PRJ-51-1](tasks/US-PRJ-51-1.md) | Test: ChangesetEntry.status uses same enum as ChangesetFrontmatter | ⚪ todo | — |  | — | — | [US-PRJ-51](stories/US-PRJ-51.md) |
| [US-PRJ-51-2](tasks/US-PRJ-51-2.md) | Test: All status assignments validated against enum values | ⚪ todo | — |  | — | — | [US-PRJ-51](stories/US-PRJ-51.md) |
| [US-PRJ-51-3](tasks/US-PRJ-51-3.md) | Test: Serialization/deserialization handles enum correctly | ⚪ todo | — |  | — | — | [US-PRJ-51](stories/US-PRJ-51.md) |
| [US-PRJ-52-1](tasks/US-PRJ-52-1.md) | Test: Update operations record old_value and new_value in changes dict | ⚪ todo | — |  | — | — | [US-PRJ-52](stories/US-PRJ-52.md) |
| [US-PRJ-52-2](tasks/US-PRJ-52-2.md) | Test: Status transitions logged with from/to states | ⚪ todo | — |  | — | — | [US-PRJ-52](stories/US-PRJ-52.md) |
| [US-PRJ-52-3](tasks/US-PRJ-52-3.md) | Test: Log rotation implemented (configurable max size or age) | ⚪ todo | — |  | — | — | [US-PRJ-52](stories/US-PRJ-52.md) |
| [US-PRJ-52-4](tasks/US-PRJ-52-4.md) | Test: Activity log query functions moved to dedicated module | ⚪ todo | — |  | — | — | [US-PRJ-52](stories/US-PRJ-52.md) |
| [US-PRJ-53-1](tasks/US-PRJ-53-1.md) | Test: installation.md embeddings row shows fastembed not sentence-transformers | ✅ done | 1 |  | claude | — | [US-PRJ-53](stories/US-PRJ-53.md) |
| [US-PRJ-53-2](tasks/US-PRJ-53-2.md) | Test: All other optional dependency entries verified against pyproject.toml | ✅ done | 1 |  | claude | — | [US-PRJ-53](stories/US-PRJ-53.md) |
| [US-PRJ-54-1](tasks/US-PRJ-54-1.md) | Test: CHANGELOG.md exists with entries for 0.8.0 through 0.8.3 | ⚪ todo | 1 |  | — | — | [US-PRJ-54](stories/US-PRJ-54.md) |
| [US-PRJ-54-2](tasks/US-PRJ-54-2.md) | Test: Each version lists added/changed/fixed items | ⚪ todo | — |  | — | — | [US-PRJ-54](stories/US-PRJ-54.md) |
| [US-PRJ-54-3](tasks/US-PRJ-54-3.md) | Test: Format follows Keep a Changelog convention | ⚪ todo | — |  | — | — | [US-PRJ-54](stories/US-PRJ-54.md) |
| [US-PRJ-54-4](tasks/US-PRJ-54-4.md) | Compile version history for 0.8.0 through 0.8.15 from git log | ⚪ todo | 2 |  | — | — | [US-PRJ-54](stories/US-PRJ-54.md) |
| [US-PRJ-54-5](tasks/US-PRJ-54-5.md) | Write CHANGELOG.md in Keep a Changelog format | ⚪ todo | 2 |  | — | — | [US-PRJ-54](stories/US-PRJ-54.md) |
| [US-PRJ-55-1](tasks/US-PRJ-55-1.md) | Test: docs/hub-mode/troubleshooting.md created | ⚪ todo | — |  | — | — | [US-PRJ-55](stories/US-PRJ-55.md) |
| [US-PRJ-55-2](tasks/US-PRJ-55-2.md) | Test: Covers submodule sync issues with resolution steps | ⚪ todo | — |  | — | — | [US-PRJ-55](stories/US-PRJ-55.md) |
| [US-PRJ-55-3](tasks/US-PRJ-55-3.md) | Test: Covers auto-rebase conflict resolution | ⚪ todo | — |  | — | — | [US-PRJ-55](stories/US-PRJ-55.md) |
| [US-PRJ-55-4](tasks/US-PRJ-55-4.md) | Test: Explains when to use pm repair vs manual fixes | ⚪ todo | — |  | — | — | [US-PRJ-55](stories/US-PRJ-55.md) |
| [US-PRJ-56-1](tasks/US-PRJ-56-1.md) | Test: Skills docs clarify all operations route through /pm | ⚪ todo | — |  | — | — | [US-PRJ-56](stories/US-PRJ-56.md) |
| [US-PRJ-56-2](tasks/US-PRJ-56-2.md) | Test: Quick reference table mapping operations to CLI/MCP/skill access | ⚪ todo | — |  | — | — | [US-PRJ-56](stories/US-PRJ-56.md) |
| [US-PRJ-56-3](tasks/US-PRJ-56-3.md) | Test: Daily workflow doc updated to remove standalone /pm scope references | ⚪ todo | — |  | — | — | [US-PRJ-56](stories/US-PRJ-56.md) |
| [US-PRJ-57-1](tasks/US-PRJ-57-1.md) | Test: All tool references in pm skill correspond to actual MCP tools | ✅ done | — |  | — | — | [US-PRJ-57](stories/US-PRJ-57.md) |
| [US-PRJ-57-2](tasks/US-PRJ-57-2.md) | Test: Non-existent tool references either implemented or removed | ✅ done | — |  | — | — | [US-PRJ-57](stories/US-PRJ-57.md) |
| [US-PRJ-57-3](tasks/US-PRJ-57-3.md) | Test: Skill tested to verify all routing targets exist | ✅ done | — |  | — | — | [US-PRJ-57](stories/US-PRJ-57.md) |
| [US-PRJ-58-1](tasks/US-PRJ-58-1.md) | Test: List-type params accepted alongside comma-separated strings for backwards compat | ⚪ todo | — |  | — | — | [US-PRJ-58](stories/US-PRJ-58.md) |
| [US-PRJ-58-2](tasks/US-PRJ-58-2.md) | Test: pm_create_story acceptance_criteria accepts list | ⚪ todo | — |  | — | — | [US-PRJ-58](stories/US-PRJ-58.md) |
| [US-PRJ-58-3](tasks/US-PRJ-58-3.md) | Test: pm_changeset_create projects accepts list | ⚪ todo | — |  | — | — | [US-PRJ-58](stories/US-PRJ-58.md) |
| [US-PRJ-58-4](tasks/US-PRJ-58-4.md) | Test: All affected tools documented with both input formats | ⚪ todo | — |  | — | — | [US-PRJ-58](stories/US-PRJ-58.md) |
| [US-PRJ-59-1](tasks/US-PRJ-59-1.md) | Test: pm-status includes epic rollup and blocker analysis steps | ⚪ todo | — |  | — | — | [US-PRJ-59](stories/US-PRJ-59.md) |
| [US-PRJ-59-2](tasks/US-PRJ-59-2.md) | Test: pm-plan includes prioritization guidance and task creation workflow | ⚪ todo | — |  | — | — | [US-PRJ-59](stories/US-PRJ-59.md) |
| [US-PRJ-59-3](tasks/US-PRJ-59-3.md) | Test: Both skills suggest actionable next steps based on findings | ⚪ todo | — |  | — | — | [US-PRJ-59](stories/US-PRJ-59.md) |
| [US-PRJ-6-1](tasks/US-PRJ-6-1.md) | Test: Daily workflow docs updated with git integration | ✅ done | 2 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-2](tasks/US-PRJ-6-2.md) | Test: Hub mode docs cover coordinated push | ✅ done | 1 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-3](tasks/US-PRJ-6-3.md) | Test: /pm skill routes commit/push commands | ✅ done | 1 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-4](tasks/US-PRJ-6-4.md) | Test: Auto-commit option documented | ✅ done | 1 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-5](tasks/US-PRJ-6-5.md) | Update daily-workflow.md with git integration steps | ✅ done | 2 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-6](tasks/US-PRJ-6-6.md) | Update hub mode docs with coordinated push and PR workflow | ✅ done | 2 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-6-7](tasks/US-PRJ-6-7.md) | Update /pm skill routing for git commands | ✅ done | 1 |  | claude | — | [US-PRJ-6](stories/US-PRJ-6.md) |
| [US-PRJ-60-1](tasks/US-PRJ-60-1.md) | Test: pm_tags tool lists all tags with usage counts | ⚪ todo | — |  | — | — | [US-PRJ-60](stories/US-PRJ-60.md) |
| [US-PRJ-60-2](tasks/US-PRJ-60-2.md) | Test: pm_rename_tag tool renames a tag across all items | ⚪ todo | — |  | — | — | [US-PRJ-60](stories/US-PRJ-60.md) |
| [US-PRJ-60-3](tasks/US-PRJ-60-3.md) | Test: pm_export tool exports to JSON format | ⚪ todo | — |  | — | — | [US-PRJ-60](stories/US-PRJ-60.md) |
| [US-PRJ-60-4](tasks/US-PRJ-60-4.md) | Test: All new tools have proper annotations and error handling | ⚪ todo | — |  | — | — | [US-PRJ-60](stories/US-PRJ-60.md) |
| [US-PRJ-61-1](tasks/US-PRJ-61-1.md) | Test: All 6 cache test files committed and tracked | ✅ done | — |  | — | — | [US-PRJ-61](stories/US-PRJ-61.md) |
| [US-PRJ-61-2](tasks/US-PRJ-61-2.md) | Test: Tests pass in CI | ✅ done | — |  | — | — | [US-PRJ-61](stories/US-PRJ-61.md) |
| [US-PRJ-61-3](tasks/US-PRJ-61-3.md) | Test: No duplicate test names or conflicts | ✅ done | — |  | — | — | [US-PRJ-61](stories/US-PRJ-61.md) |
| [US-PRJ-62-1](tasks/US-PRJ-62-1.md) | Test: test_search.py created with direct keyword_search tests | ⚪ todo | — |  | — | — | [US-PRJ-62](stories/US-PRJ-62.md) |
| [US-PRJ-62-2](tasks/US-PRJ-62-2.md) | Test: Snippet generation tested with various content lengths | ⚪ todo | — |  | — | — | [US-PRJ-62](stories/US-PRJ-62.md) |
| [US-PRJ-62-3](tasks/US-PRJ-62-3.md) | Test: Score calculation verified (title match vs content match) | ⚪ todo | — |  | — | — | [US-PRJ-62](stories/US-PRJ-62.md) |
| [US-PRJ-62-4](tasks/US-PRJ-62-4.md) | Test: Empty results and case-insensitive matching tested | ⚪ todo | — |  | — | — | [US-PRJ-62](stories/US-PRJ-62.md) |
| [US-PRJ-63-1](tasks/US-PRJ-63-1.md) | Test: test_performance_n1.py created | ✅ done | 1 |  | claude | US-PRJ-63-5 | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-63-2](tasks/US-PRJ-63-2.md) | Test: Tests verify pm_board uses batch loads not per-task fetches | ✅ done | 1 |  | claude | US-PRJ-63-6 | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-63-3](tasks/US-PRJ-63-3.md) | Test: Tests verify pm_epic uses single list_tasks call | ✅ done | 1 |  | claude | US-PRJ-63-6 | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-63-4](tasks/US-PRJ-63-4.md) | Test: Tests verify pm_search tag filter uses batch metadata loading | ✅ done | 1 |  | claude | US-PRJ-63-6 | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-63-5](tasks/US-PRJ-63-5.md) | Create test_performance_n1.py with a call-counting Store spy and a 100-task fixture | ✅ done | 1 |  | claude | — | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-63-6](tasks/US-PRJ-63-6.md) | Assert pm_board, pm_epic and pm_search make batch loads, not per-item calls | ✅ done | 2 |  | claude | US-PRJ-63-5, US-PRJ-43-5, US-PRJ-43-6, US-PRJ-43-7, US-PRJ-43-8 | [US-PRJ-63](stories/US-PRJ-63.md) |
| [US-PRJ-64-1](tasks/US-PRJ-64-1.md) | Test: Estimator tests cover empty history edge case | ⚪ todo | — |  | — | — | [US-PRJ-64](stories/US-PRJ-64.md) |
| [US-PRJ-64-2](tasks/US-PRJ-64-2.md) | Test: Large history (20+ items) tested | ⚪ todo | — |  | — | — | [US-PRJ-64](stories/US-PRJ-64.md) |
| [US-PRJ-64-3](tasks/US-PRJ-64-3.md) | Test: Mixed status combinations tested | ⚪ todo | — |  | — | — | [US-PRJ-64](stories/US-PRJ-64.md) |
| [US-PRJ-64-4](tasks/US-PRJ-64-4.md) | Test: Error conditions tested | ⚪ todo | — |  | — | — | [US-PRJ-64](stories/US-PRJ-64.md) |
| [US-PRJ-7-1](tasks/US-PRJ-7-1.md) | Test: Subproject changes create feature branches not direct commits to deploy | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-10](tasks/US-PRJ-7-10.md) | Add deploy branch protection validation | ✅ done | 2 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-11](tasks/US-PRJ-7-11.md) | Write tests for PR workflow end-to-end | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-2](tasks/US-PRJ-7-2.md) | Test: PR creation integrated into workflow (gh cli) | ✅ done | 2 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-3](tasks/US-PRJ-7-3.md) | Test: Hub only updates refs after PRs are merged | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-4](tasks/US-PRJ-7-4.md) | Test: Deploy branch is protected from direct pushes | ✅ done | 2 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-5](tasks/US-PRJ-7-5.md) | Test: Workflow supports simultaneous PRs across multiple subprojects | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-6](tasks/US-PRJ-7-6.md) | Add deploy_branch config to per-subproject config.yaml | ✅ done | 2 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-7](tasks/US-PRJ-7-7.md) | Implement create_feature_branch() for task-linked branching | ✅ done | 2 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-8](tasks/US-PRJ-7-8.md) | Implement create_pr() wrapping gh cli for subproject PRs | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-7-9](tasks/US-PRJ-7-9.md) | Implement update_hub_refs_after_merge() for post-PR hub sync | ✅ done | 3 |  | claude | — | [US-PRJ-7](stories/US-PRJ-7.md) |
| [US-PRJ-8-1](tasks/US-PRJ-8-1.md) | Test: Single command shows git state of all N submodules | ✅ done | 3 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-2](tasks/US-PRJ-8-2.md) | Test: Shows branch/dirty/ahead-behind/PR status per repo | ✅ done | 3 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-3](tasks/US-PRJ-8-3.md) | Test: Highlights mismatches and issues | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-4](tasks/US-PRJ-8-4.md) | Test: Scales to 20+ submodules without clutter | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-5](tasks/US-PRJ-8-5.md) | Implement git_status_all() core data collection | ✅ done | 3 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-6](tasks/US-PRJ-8-6.md) | Add PR status collection via gh cli | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-7](tasks/US-PRJ-8-7.md) | Add formatted CLI output with attention-priority sorting | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-8](tasks/US-PRJ-8-8.md) | Add pm_git_status MCP tool and /pm routing | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-8-9](tasks/US-PRJ-8-9.md) | Write tests for git status dashboard | ✅ done | 2 |  | claude | — | [US-PRJ-8](stories/US-PRJ-8.md) |
| [US-PRJ-9-1](tasks/US-PRJ-9-1.md) | Test: Deploy branch configurable per subproject in config | ⚪ todo | — |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-10](tasks/US-PRJ-9-10.md) | Write tests for conventions config and validation | ⚪ todo | 2 |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-2](tasks/US-PRJ-9-2.md) | Test: Feature branch naming convention enforced on create | ⚪ todo | — |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-3](tasks/US-PRJ-9-3.md) | Test: Direct pushes to deploy branch blocked | ⚪ todo | — |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-4](tasks/US-PRJ-9-4.md) | Test: Convention violations produce clear error messages | ⚪ todo | — |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-5](tasks/US-PRJ-9-5.md) | Test: Conventions stored in hub config and shared | ⚪ todo | — |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-6](tasks/US-PRJ-9-6.md) | Add hub-level conventions config schema | ⚪ todo | 2 |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-7](tasks/US-PRJ-9-7.md) | Implement validate_conventions() unified checker | ⚪ todo | 3 |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-8](tasks/US-PRJ-9-8.md) | Add commit message formatting helpers | ⚪ todo | 1 |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
| [US-PRJ-9-9](tasks/US-PRJ-9-9.md) | Wire convention checks into existing operations | ⚪ todo | 2 |  | — | — | [US-PRJ-9](stories/US-PRJ-9.md) |
