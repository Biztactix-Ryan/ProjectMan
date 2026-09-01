# Skills Reference

ProjectMan installs 5 Claude Code skills (slash commands) via `projectman setup-claude`. These provide the primary interface for interacting with ProjectMan from Claude Code.

## /pm

General entry point for project management. Routes to the appropriate MCP tools based on your request, including scope, audit, fix, and other subcommands.

```
/pm                          # Interactive — Claude asks what you need
/pm create story "Title"     # Route to story creation
/pm show US-PRJ-1            # Route to pm_get
/pm scope US-PRJ-1           # Decompose story into tasks
/pm audit                    # Run drift detection
/pm fix                      # Fix malformed files
/pm web start                # Launch the web dashboard
/pm web stop                 # Stop the web server
```

## /pm-status

Quick project dashboard. Shows story/task counts, points, completion percentage, and highlights blockers.

```
/pm-status
```

**What it does:**
1. Calls `pm_status` to get the compact index
2. Calls `pm_active` to show in-progress work
3. Highlights blockers or items needing attention
4. Suggests `/pm audit` if drift is detected

## /pm-plan

Guided sprint planning workflow. Walks through the full planning process.

```
/pm-plan
```

**Workflow:**
1. `pm_status` — current state
2. `pm_audit` — check for drift
3. `pm_active` — what's in-flight
4. `pm_burndown` — velocity trend
5. Review and prioritize backlog
6. Scope unscoped stories (`pm_scope`)
7. Estimate unestimated stories (`pm_estimate`)
8. Assign stories to sprint
9. Sprint summary with point target (20-30 for solo dev with AI)

## /pm-do

Pick up and execute a specific task. This is the "do the work" command.

```
/pm-do US-PRJ-1-1
```

**Workflow (3 phases):**

1. **Claim & Context** — Auto-grabs the task via `pm_grab` with readiness validation. Loads task context including parent story, related files, and definition of done.
2. **Execute** — Implements the work described in the task. Follows implementation steps and verifies definition-of-done items as they are completed.
3. **Complete** — Reviews task status, detects sibling task completion (whether all tasks under the parent story are now done), and updates status via `pm_update`.

**Auto-spawn:** When using `/pm grab` in a Web UI environment (with `CLAUDE_WEB_PORT` set), a focused task session is automatically spawned via the PostToolUse activity hook — no need to manually run `/pm-do`. In CLI-only mode, `/pm-do` is suggested as a fallback.

**Note:** This skill has `disable-model-invocation: true` — it only runs when you explicitly invoke it with `/pm-do`, never automatically. This is because it performs real code changes.

## /pm-autoscope

Automated bulk scoping. Discovers what needs scoping and walks through creation.

```
/pm-autoscope
/pm-autoscope full
/pm-autoscope incremental
```

**Two modes** (auto-detected):

- **Full scan** (no epics/stories exist): Reads codebase signals (docs, build files, source tree), proposes epics, stories, and tasks for user approval, then creates them all.
- **Incremental** (stories exist without tasks): Fetches undecomposed stories in paginated batches (default 5), scopes each with `pm_scope`, proposes 2-6 tasks, gets user approval, and creates them in bulk via `pm_create_tasks`. Loops through batches until done.

Also accessible via `/pm autoscope` or natural language like "scope everything".

## /pm-orchestrate

Drive the active sprint to done by dispatching worker subagents task-by-task and independently validating their work. Used when you want tasks executed autonomously rather than one at a time.

```
/pm-orchestrate
/pm-orchestrate --sprint SPRINT-PRJ-2
/pm-orchestrate --max 5 --dry-run
/pm-orchestrate --auto
/pm-orchestrate --resume orch-2026-08-21-9c2f
```

**Flags:**

- `--sprint <id>` — Drive a specific sprint instead of the active one
- `--max <n>` — Stop after `n` worker dispatches (safety budget; default no limit)
- `--resume <run-id>` — Pick up after a run that died mid-loop: adopt the claims that run id still holds
- `--dry-run` — Show the execution plan and stop without spawning workers
- `--auto` — Skip the pre-flight confirmation

**Operating model:** The skill acts as an orchestrator, not a worker — it picks the next ready task, hands it to a worker subagent, then independently validates the output before accepting it. Workers run sequentially (one at a time), changes are staged but never committed, and failing tasks are parked in `review` with a run-log record so the loop keeps moving. Every attempt is recorded via a run-log entry, and every claim, release and verdict is stamped with the run id — which is what lets Phase 4 rebuild the final report from the activity log rather than from memory.

**Run id and claim recovery:** Phase 0 mints one run id for the run — `orch-<date>-<random>` — and passes it as `run_id=` on every `pm_grab`, `pm_release` and verdict verb, including the id pasted into each worker prompt. The store keeps it on the task as `claimed_by_run` and stamps it on the activity-log event. Pre-flight step 3 then classifies every in-progress task from that data instead of asking a human: `pm_active` reports `claimed_by_run`, `claim_age`, `stale: true` and a `stale_tasks` list (threshold `stale_claim_hours`, default 2, overridable per call with `stale_after=`). A claim held by an earlier `orch-` run that is stale, or whose run id stops appearing in `pm_activity(item_id=..., event_type="update")` after its last claim, is taken back with `pm_grab(<id>, run_id=<this run>)` and logged as `recovered from run <old>`; a claim that is fresh and still active is listed and left alone (skipped under `--auto`); a claim held by a human or any non-`orch-` id is never touched. See [`pm_active`](mcp-tools.md#pm_activeproject-tag-limit-offset-stale_after) and [claim ownership](file-formats.md#claim-ownership--claimed_at--claimed_by_run).

**Final report, rebuilt from the log:** Phase 4 does not summarise from the orchestrator's memory of a loop that may have run for hours. Step 22 calls `pm_activity(run_id=<this run>)` — paging with `offset` while the response reports `has_more: true` — and derives every section of the report from the returned entries: accepted (`status: ... → done`, with the evidence one-liner read back from `pm_run_log`), retried (`→ todo`), parked versus accept-as-review (both `→ review`, separated by the run-log outcome `blocked` vs `partial`), recovered claims (`claimed_by_run: <old run> → <this run>`), releases, stories closed (`pm_accept` stamps the closure with the run that caused it), points moved (one projected `pm_get` over the accepted ids) and untouched tasks (the plan minus all of the above). The lists the orchestrator kept while looping are a **cross-check, not the source**: where the two disagree the log wins and the disagreement is reported outright, since a mismatch means a write that never landed. Step 23 keeps `git diff --stat` against the pre-flight snapshot — the log records which items moved, never which files did. Edits that are not claims or verdicts (the step 3 recovery note, the step 24 sprint close) are tagged with the same `run_id=` so they land in that slice too. See [`pm_activity`](mcp-tools.md#pm_activityitem_id-event_type-from_date-to_date-actor-run_id-limit-offset-project).

**Resume after a crash (`--resume <run-id>`):** A run that dies mid-loop leaves claims behind, so the skill has a documented resume path (section *Resume — Picking Up an Interrupted Run*). `--resume <old-run-id>` adopts that run's claims as one decision instead of leaving step 3 to infer them task by task; without the flag, step 3's per-claim classification applies unchanged. The resuming run **mints its own fresh id** rather than reusing the old one — reuse would merge two processes into one `pm_activity(run_id=)` slice — and records the lineage on each adopted claim as a `recovered from run <old>` run-log note. It reads the dead run's record with `pm_activity(run_id=<old>)`, paging on `has_more`, and sorts what it finds: tasks still `in-progress` under the old id are **adopted** (`pm_grab(<id>, run_id=<this run>)`, which resets `claimed_at`), tasks already `done` are **left** (the verdict landed), and tasks released, parked or back in `todo` are **left and reported** — those were deliberate decisions of the dead run. An adopted task is re-dispatched as a **retry**, never as fresh work: its worker may have left partial edits, so the worker prompt carries an `<on resume: ...>` line telling it that the previous run died mid-task and to validate the working-tree state first. Claims held by other runs remain step 3's business, and a claim held by a human — or any `claimed_by_run` without the `orch-` prefix — is never adopted. Phase 4 names the resumed run id and lists the adopted claims. Do not resume when a human holds the claim, when the old run's last event is a verdict on a task that is now done, when the old run is still emitting events (it is alive, not dead), or when the id matches no activity entries at all.

**Health check:** Pre-flight runs `pm_audit` and records the `digest: <16 hex>` line from the report as the *last audit digest*. Every 3 accepted tasks the loop re-runs `pm_audit(since=<last audit digest>)`: an `unchanged: true` answer (under 100 bytes, no checks run) passes the check outright, and anything else is a full report — the run stops on a new ERROR-level finding, otherwise the digest is refreshed and the loop continues. The repeat is the point: it is what catches drift mid-run, so `pm_audit` is never cached per session — `since` removes the cost without removing the poll. See [`pm_audit`](mcp-tools.md#pm_auditinclude_info-project-since).

**Note:** Has `disable-model-invocation: true` — only runs when explicitly invoked with `/pm-orchestrate`.

## /pm-cleanup

Archive completed epics, stories, tasks, and old sprints to reduce context noise when looking for active items.

```
/pm-cleanup
```

**Workflow:**

1. Reads current state via `pm_status`
2. Identifies archive candidates — done epics (with all stories done), done stories outside active epics, and completed sprints older than two weeks
3. Presents an archive plan and **asks for explicit approval before proceeding**
4. Archives in order (tasks → stories → epics) via `pm_archive`, then rebuilds indexes with `pm_reindex`
5. Suggests committing the archive and planning the next sprint

Also accessible via natural language like "clean up" or "archive done work".

## Web Dashboard via /pm

The `/pm` skill routes web-related commands to the MCP web tools:

```
/pm web                  # Start the web dashboard (default 127.0.0.1:8000)
/pm web start 0.0.0.0    # Bind to all interfaces
/pm web stop             # Stop the server
/pm web status           # Check if it's running
```

If a port is already in use, Claude automatically retries with the next available port. The web dashboard provides:

- Project overview with clickable stat cards
- Kanban board with drag-drop status updates
- Epic, story, and task detail views
- Search across all items
- Burndown and audit views
- Documentation editor

Requires the `web` extra: `pip install projectman[web]` or `pipx install projectman[all]`.

## Customization

All skills are installed as markdown files in `.claude/skills/<name>/SKILL.md`. You can edit them to:

- Add project-specific conventions
- Modify workflow steps
- Change tool usage patterns
- Add additional context or rules

Skills are version-controlled with your project, so customizations are shared with your team.
