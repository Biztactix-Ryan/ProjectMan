# Tasks

| ID | Title | Status | Points | Tags | Assignee | Depends On | Story |
| -- | ----- | ------ | ------ | ---- | -------- | ---------- | ----- |
| [US-PM-1-1](tasks/US-PM-1-1.md) | Test: Oversized notes are truncated server-side with a visible marker rather than rejected;The response carries a not... | ✅ done | — |  | — | — | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-2](tasks/US-PM-1-2.md) | Truncate oversized run-log notes instead of raising | ✅ done | 1 |  | claude | — | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-3](tasks/US-PM-1-3.md) | Return a note_truncated flag on the update response | ✅ done | 1 |  | claude | US-PM-1-2 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-4](tasks/US-PM-1-4.md) | Test: oversized note truncates and the status write still lands | ✅ done | 1 |  | claude | US-PM-1-2 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-1-5](tasks/US-PM-1-5.md) | Test: note_truncated flag and boundary lengths | ✅ done | 1 |  | claude | US-PM-1-3 | [US-PM-1](stories/US-PM-1.md) |
| [US-PM-10-1](tasks/US-PM-10-1.md) | Test: pm_get and pm_grab accept a fields parameter selecting returned keys | ⚪ todo | — |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-2](tasks/US-PM-10-2.md) | Test: A status-only verification fetch costs a small fraction of the full payload | ⚪ todo | — |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-3](tasks/US-PM-10-3.md) | Test: pm_batch_get and pm_list_sprints support a brief or projected mode | ⚪ todo | — |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-4](tasks/US-PM-10-4.md) | Test: Default behaviour is unchanged when no projection is requested | ⚪ todo | — |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-5](tasks/US-PM-10-5.md) | Test: pm-orchestrate uses projection for its validation read | ⚪ todo | — |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-6](tasks/US-PM-10-6.md) | Add a fields parameter to pm_get and pm_grab | ⚪ todo | 3 |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-7](tasks/US-PM-10-7.md) | Add a brief mode to pm_batch_get and pm_list_sprints | ⚪ todo | 2 |  | — | — | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-10-8](tasks/US-PM-10-8.md) | Use projection for the orchestrator validation read | ⚪ todo | — |  | — | US-PM-10-6 | [US-PM-10](stories/US-PM-10.md) |
| [US-PM-11-1](tasks/US-PM-11-1.md) | Test: pm_audit returns a digest identifying the current project state | ⚪ todo | — |  | — | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-2](tasks/US-PM-11-2.md) | Test: pm_audit accepts a since parameter and answers cheaply when nothing changed | ⚪ todo | — |  | — | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-3](tasks/US-PM-11-3.md) | Test: The health check still detects new ERROR-level findings promptly | ⚪ todo | — |  | — | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-4](tasks/US-PM-11-4.md) | Test: pm-orchestrate passes the previous digest on its periodic health check | ⚪ todo | — |  | — | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-5](tasks/US-PM-11-5.md) | Return a state digest from pm_audit | ⚪ todo | 2 |  | — | — | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-6](tasks/US-PM-11-6.md) | Accept a since parameter and short-circuit when unchanged | ⚪ todo | — |  | — | US-PM-11-5 | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-11-7](tasks/US-PM-11-7.md) | Pass the previous digest from the orchestrator health check | ⚪ todo | — |  | — | US-PM-11-6 | [US-PM-11](stories/US-PM-11.md) |
| [US-PM-12-1](tasks/US-PM-12-1.md) | Test: A bulk update accepts either a uniform patch over an ID list or per-item patches | ⚪ todo | — |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-2](tasks/US-PM-12-2.md) | Test: Bulk archive accepts an explicit ID list | ⚪ todo | — |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-3](tasks/US-PM-12-3.md) | Test: Partial failure reports which IDs succeeded and which did not | ⚪ todo | — |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-4](tasks/US-PM-12-4.md) | Test: The four measured bulk patterns are each expressible in one call | ⚪ todo | — |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-5](tasks/US-PM-12-5.md) | Test: Longest consecutive-run length drops sharply in the next telemetry baseline | ⚪ todo | — |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-6](tasks/US-PM-12-6.md) | Add pm_update_many | ⚪ todo | 3 |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-7](tasks/US-PM-12-7.md) | Add bulk archive with an explicit ID list | ⚪ todo | 2 |  | — | — | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-12-8](tasks/US-PM-12-8.md) | Define partial-failure semantics | ⚪ todo | — |  | — | US-PM-12-6, US-PM-12-7 | [US-PM-12](stories/US-PM-12.md) |
| [US-PM-13-1](tasks/US-PM-13-1.md) | Test: The worker prompt template includes project architecture context | ⚪ todo | 1 |  | — | US-PM-13-5 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-2](tasks/US-PM-13-2.md) | Test: The scoping and estimation workflows consult pm_estimate before writing points | ⚪ todo | 1 |  | — | US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-3](tasks/US-PM-13-3.md) | Test: Skill files name the step at which each guidance tool is called | ⚪ todo | 1 |  | — | US-PM-13-5, US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-4](tasks/US-PM-13-4.md) | Test: Usage of both tools is visible in the next telemetry baseline | ⚪ todo | 1 |  | — | US-PM-13-5, US-PM-13-6 | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-5](tasks/US-PM-13-5.md) | Add project context to the worker prompt template | ⚪ todo | 1 |  | — | — | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-13-6](tasks/US-PM-13-6.md) | Call pm_estimate before writing points in the scoping workflows | ⚪ todo | 1 |  | — | — | [US-PM-13](stories/US-PM-13.md) |
| [US-PM-14-1](tasks/US-PM-14-1.md) | Test: An interrupted run can identify which claims it owned | ⚪ todo | — |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-2](tasks/US-PM-14-2.md) | Test: Stale claims are identifiable without asking a human | ⚪ todo | — |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-3](tasks/US-PM-14-3.md) | Test: The final report is built from the activity log rather than from memory | ⚪ todo | — |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-4](tasks/US-PM-14-4.md) | Test: pm-orchestrate has a documented resume path | ⚪ todo | — |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-5](tasks/US-PM-14-5.md) | Add claim ownership and staleness metadata | ⚪ todo | 2 |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-6](tasks/US-PM-14-6.md) | Replace the Phase 1 ownership guess with an activity query | ⚪ todo | — |  | — | US-PM-14-5 | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-7](tasks/US-PM-14-7.md) | Build the final report from the activity log | ⚪ todo | — |  | — | — | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-14-8](tasks/US-PM-14-8.md) | Document a resume path in pm-orchestrate | ⚪ todo | — |  | — | US-PM-14-6 | [US-PM-14](stories/US-PM-14.md) |
| [US-PM-15-1](tasks/US-PM-15-1.md) | Test: Changeset and web tool families are hidden unless enabled by config | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-2](tasks/US-PM-15-2.md) | Test: Repair and restore tooling is hidden from the agent tool list but reachable via CLI | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-3](tasks/US-PM-15-3.md) | Test: pm_activity and pm_context and pm_estimate remain exposed | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-4](tasks/US-PM-15-4.md) | Test: Tool-list payload size drops measurably with default config | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-5](tasks/US-PM-15-5.md) | Add config flags for the changeset and web tool families | ⚪ todo | 2 |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-6](tasks/US-PM-15-6.md) | Move repair and restore tooling off the agent tool list | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-15-7](tasks/US-PM-15-7.md) | Measure the tool-list payload reduction | ⚪ todo | — |  | — | — | [US-PM-15](stories/US-PM-15.md) |
| [US-PM-16-1](tasks/US-PM-16-1.md) | Test: Archiving a task no longer sets its status to done | ✅ done | 1 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-2](tasks/US-PM-16-2.md) | Test: Archived tasks are excluded from completion percentage and burndown | ✅ done | 1 |  | claude | US-PM-16-6 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-3](tasks/US-PM-16-3.md) | Test: Sprint velocity counts only genuinely completed points | ✅ done | 1 |  | claude | US-PM-16-6 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-4](tasks/US-PM-16-4.md) | Test: Existing archived-as-done tasks can be identified and corrected by a migration | ✅ done | 1 |  | claude | US-PM-16-7 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-5](tasks/US-PM-16-5.md) | Add an archived state for tasks | ✅ done | 2 |  | claude | — | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-6](tasks/US-PM-16-6.md) | Exclude archived items from completion and velocity math | ✅ done | 2 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-16-7](tasks/US-PM-16-7.md) | Migrate existing archived-as-done tasks | ✅ done | 2 |  | claude | US-PM-16-5 | [US-PM-16](stories/US-PM-16.md) |
| [US-PM-2-1](tasks/US-PM-2-1.md) | Test: Tool failures raise a real MCP error rather than returning an error string body;is_error is set on every failur... | ✅ done | — |  | — | — | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-2](tasks/US-PM-2-2.md) | Inventory every error-string return path | ✅ done | 2 |  | claude | — | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-3](tasks/US-PM-2-3.md) | Raise genuine failures as real MCP errors | ✅ done | 2 |  | claude | US-PM-2-2 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-4](tasks/US-PM-2-4.md) | Keep expected-negative results as successful responses | ✅ done | 2 |  | claude | US-PM-2-2 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-5](tasks/US-PM-2-5.md) | Test: every known failure class sets is_error | ✅ done | 1 |  | claude | US-PM-2-3 | [US-PM-2](stories/US-PM-2.md) |
| [US-PM-2-6](tasks/US-PM-2-6.md) | Test: expected negatives are not errors | ✅ done | 1 |  | claude | US-PM-2-4 | [US-PM-2](stories/US-PM-2.md) |
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
| [US-PM-7-1](tasks/US-PM-7-1.md) | Test: Releasing a task is expressible without an empty-string or null sentinel | ⚪ todo | 1 |  | — | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-2](tasks/US-PM-7-2.md) | Test: Claiming uses compare-and-swap so two concurrent workers cannot both win | ⚪ todo | 1 |  | — | US-PM-7-7 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-3](tasks/US-PM-7-3.md) | Test: Clearing depends_on and tags has an explicit affordance | ⚪ todo | 1 |  | — | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-4](tasks/US-PM-7-4.md) | Test: pm-orchestrate SKILL.md no longer instructs the unspellable update | ⚪ todo | 1 |  | — | US-PM-7-9 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-5](tasks/US-PM-7-5.md) | Test: Concurrent claim attempts are covered by a test | ⚪ todo | 1 |  | — | US-PM-7-7 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-6](tasks/US-PM-7-6.md) | Design the claim and release contract | ✅ done | 2 |  | claude | — | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-7](tasks/US-PM-7-7.md) | Implement compare-and-swap claiming in the store | ⚪ todo | 3 |  | claude | US-PM-7-6 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-8](tasks/US-PM-7-8.md) | Implement release and the field-clear affordances | ⚪ todo | 3 |  | — | US-PM-7-6 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-7-9](tasks/US-PM-7-9.md) | Rewrite the SKILL.md release instructions | ⚪ todo | 1 |  | — | US-PM-7-8 | [US-PM-7](stories/US-PM-7.md) |
| [US-PM-8-1](tasks/US-PM-8-1.md) | Test: Each of the four verdicts has a verb that sets status and outcome structurally | ⚪ todo | 1 |  | — | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-2](tasks/US-PM-8-2.md) | Test: Outcome cannot be omitted on a terminal verdict | ⚪ todo | 1 |  | — | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-3](tasks/US-PM-8-3.md) | Test: pm-orchestrate SKILL.md uses the verdict verbs throughout | ⚪ todo | 1 |  | — | US-PM-8-9 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-4](tasks/US-PM-8-4.md) | Test: Existing pm_update status writes keep working for backwards compatibility | ⚪ todo | 1 |  | — | US-PM-8-8 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-5](tasks/US-PM-8-5.md) | Test: Measured share of completions lacking a run-log entry drops to zero | ⚪ todo | 1 |  | — | US-PM-8-9 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-6](tasks/US-PM-8-6.md) | Specify the four verdict verbs | ⚪ todo | 2 |  | — | — | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-7](tasks/US-PM-8-7.md) | Implement the verdict verbs | ⚪ todo | 3 |  | — | US-PM-8-6, US-PM-7-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-8](tasks/US-PM-8-8.md) | Keep generic pm_update working for compatibility | ⚪ todo | 2 |  | — | — | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-8-9](tasks/US-PM-8-9.md) | Rewrite pm-orchestrate to use the verdict verbs | ⚪ todo | 2 |  | — | US-PM-8-7 | [US-PM-8](stories/US-PM-8.md) |
| [US-PM-9-1](tasks/US-PM-9-1.md) | Test: Run-log entries accept structured evidence separate from the prose note | ⚪ todo | 1 |  | — | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-2](tasks/US-PM-9-2.md) | Test: Evidence records files changed and tests run with results and DoD items met | ⚪ todo | 1 |  | — | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-3](tasks/US-PM-9-3.md) | Test: Completions carrying no evidence are detectable via query or audit | ⚪ todo | 1 |  | — | US-PM-9-8 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-4](tasks/US-PM-9-4.md) | Test: pm-orchestrate records evidence structurally rather than in the note | ⚪ todo | 1 |  | — | US-PM-9-9 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-5](tasks/US-PM-9-5.md) | Test: Median note length drops well below the cap | ⚪ todo | 1 |  | — | US-PM-9-9 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-6](tasks/US-PM-9-6.md) | Design the evidence schema | ⚪ todo | 2 |  | — | — | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-7](tasks/US-PM-9-7.md) | Store and return evidence on run-log entries | ⚪ todo | 3 |  | — | US-PM-9-6 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-8](tasks/US-PM-9-8.md) | Detect completions with no evidence | ⚪ todo | 2 |  | — | US-PM-9-7 | [US-PM-9](stories/US-PM-9.md) |
| [US-PM-9-9](tasks/US-PM-9-9.md) | Update pm-orchestrate to record evidence structurally | ⚪ todo | 2 |  | — | US-PM-8-9 | [US-PM-9](stories/US-PM-9.md) |
