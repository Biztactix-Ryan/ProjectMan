# Skills Reference

ProjectMan installs 8 Claude Code skills (slash commands) via `projectman setup-claude` — `/pm`, `/pm-status`, `/pm-plan`, `/pm-do`, `/pm-orchestrate`, `/pm-autoscope`, `/pm-cleanup` and `/pm-next`. These provide the primary interface for interacting with ProjectMan from Claude Code. This page is the single place that states the count; other docs point here rather than repeating it.

## Routing and access

Every `/pm-*` entry on this page routes through the same path: the `/pm` skill hands the request to the **pm agent** (`.claude/agents/pm.md`), and the agent calls the MCP tools. The named entry points (`/pm-status`, `/pm-plan`, `/pm-do`, `/pm-orchestrate`, `/pm-autoscope`, `/pm-cleanup`, `/pm-next`) are shortcuts into that same path, not separate programs. Anything written as `/pm <word> <args>` — `/pm scope US-PRJ-1`, `/pm board`, `/pm commit` — is an *argument to `/pm`*, never a standalone command of its own. The `projectman` CLI is a separate surface, and it deliberately covers setup and git plumbing only: most project operations have no CLI equivalent at all.

| Operation | CLI command | MCP tool | Skill invocation |
| --- | --- | --- | --- |
| Status dashboard | — | `pm_status` | `/pm-status`, or `/pm` with no arguments |
| Board of available / in-progress work | — | `pm_board` | `/pm board` |
| Create a story | — | `pm_create_story` | `/pm create story "<title>" "<description>"` |
| Scope a story into tasks | — | `pm_scope` | `/pm scope <story-id>`, or `/pm-autoscope` in bulk |
| Estimate an item | — | `pm_estimate` | `/pm estimate <id>` |
| Commit the store | `projectman commit` | `pm_commit` | `/pm commit` |
| Push the store branch | `projectman push` | `pm_push` | `/pm push` |
| Plan a sprint | — | `pm_create_sprint` | `/pm-plan` |
| Orchestrate the active sprint | — | — (the loop drives `pm_grab`, `pm_accept`, `pm_retry`, `pm_park`, `pm_review`) | `/pm-orchestrate` |
| Note for the next session | — | `pm_next` | `/pm-next` |

A `—` means the operation has no equivalent on that surface. Two more rows worth knowing: drift detection is `projectman audit` / `pm_audit` / `/pm audit`, and store git state is `projectman git-status` / `pm_git_status` / `/pm git status`. The full CLI surface is in [`cli.md`](cli.md); the full tool surface, with every argument, is in [`mcp-tools.md`](mcp-tools.md).

## /pm

General entry point for project management. Routes to the appropriate MCP tools based on your request, including scope, audit, fix, and other subcommands. Each line below is `/pm` plus arguments — `/pm scope US-PRJ-1` invokes the `/pm` skill with `scope US-PRJ-1`, and there is no separate `/pm scope` command.

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
9. Long-task check before activating — `pm_get_sprint` lists [`long_task_risk`](mcp-tools.md#long_task_risk): the sprint's open tasks whose points band has a measured `p90` above `orchestrate.max_task_minutes`. The skill lists each flagged task with its band `p90` and offers to re-scope it into smaller tasks (`pm_scope`), because a task that runs past the hour outlives the orchestrator's one-hour prompt cache and makes the next dispatch pay a full prefix rewrite. Accepting the risk and activating anyway is a valid answer.
10. Sprint summary with point target (20-30 for solo dev with AI)

## /pm-do

Pick up and execute a specific task. This is the "do the work" command.

```
/pm-do US-PRJ-1-1
```

**Workflow (3 phases):**

1. **Claim & Context** — Auto-grabs the task via `pm_grab` with readiness validation. Loads task context including parent story, related files, and definition of done.
2. **Execute** — Implements the work described in the task. Follows implementation steps and verifies definition-of-done items as they are completed.
3. **Complete** — Reviews task status, detects sibling task completion (whether all tasks under the parent story are now done), and updates status via `pm_update`. The closing report is bounded — under about 1,500 characters, no code and no log output — in a fixed order: files changed (paths only); tests as `command -> pass|fail (n passed)`; DoD met; DoD unmet; blockers. That is the shape `/pm-orchestrate` dispatches expect back, so an orchestrated worker and a hand-run one report identically, and it transcribes straight into the `evidence` argument of a verdict verb.

**Worker rules (orchestrated runs):** A worker `/pm-orchestrate` dispatches is running in a git worktree of its own on `orch/<run-id>/<task-id>`, so the skill states the rules that go with it: never `git checkout`, `restore`, `stash`, `reset` or `clean`, and never switch branches; commit only when the dispatch prompt asks for one, and only code paths — never `.project`, which is gitignored and not present in the worktree, so the store is reached through the `pm_*` tools instead. Hand-run invocations are unaffected: the rules bind whichever checkout the skill is followed in.

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
- `--lanes <1|2>` — Keep two independent tasks in flight instead of one (default 1)
- `--resume <run-id>` — Pick up after a run that died mid-loop: adopt the claims that run id still holds
- `--dry-run` — Show the execution plan and stop without spawning workers
- `--auto` — Skip the pre-flight confirmation

**Operating model:** The skill acts as an orchestrator, not a worker — it picks the next ready task, hands it to a worker subagent, then independently validates the output (via a second, separate subagent) before accepting it. Workers run one at a time by default — two with `--lanes 2`, see *Two lanes* below — each in a git worktree of its own committing code to a per-task branch, nothing is pushed and the store is never committed, and failing tasks are parked in `review` with a run-log record so the loop keeps moving. Every attempt is recorded via a run-log entry, and every claim, release and verdict is stamped with the run id — which is what lets Phase 4 rebuild the final report from the activity log rather than from memory.

**Isolation: a run branch and a worktree per task:** Phase 0 cuts the run branch `orch/<run-id>` from `HEAD` — dirt outside `.project/` stops the run before it starts, with the dirty list reported — and adds a run worktree beside it, which is where the merges happen. Step 15 then dispatches each worker with the `Agent` tool's `isolation: "worktree"` onto a task branch of its own, `orch/<run-id>/<task-id>`, cut from the run branch. The worker edits and commits **code only** there — never `.project`, which is gitignored and so is simply not present in a fresh worktree, leaving every store read and write to go through the `pm_*` tools against the primary checkout — and its report adds the branch, the sha and the worktree path to the usual five sections. This replaces the one shared checkout of the earlier stage-only model, where a pre-dispatch `git status --short` snapshot and a checksum list of the files a task must not touch stood in for a boundary between two tasks' edits; the branch diff now *is* that boundary. The trade is recorded in [ADR-005](../../.project/DECISIONS.md) and the reasoning is in [`orchestrate-design.md`](orchestrate-design.md) under *Isolation model*.

**Merging on accept:** A task's work reaches the run branch only when the verdict is `accept`. Step 19 merges the task branch in the run worktree — `git merge --ff-only <task branch>` first, else `--no-ff -m "<task-id>"` — before the next dispatch, so a dependent task's worker starts from a run branch that already carries its dependency's work. A conflict is not an accept: the merge is aborted and the task goes back out with `pm_retry`, the conflicting paths in `evidence.files` and a note to rebase onto the run branch; a second conflict parks it. Retried, parked and accept-as-review tasks keep their branches, unmerged, as the record of the attempt.

**Two lanes (`--lanes <1|2>`):** By default the loop keeps one task in flight. `--lanes 2` keeps two, in lanes A and B: lane A's task is picked as usual, and lane B's comes from `pm_board(lane_compatible_with=<lane A's task>)`, which returns only the tasks the store says can run beside it — a different story, neither task depending on the other or on the other's story, and the two stories not connected by `depends_on` in either direction. Both workers are dispatched in the background, and the orchestrator takes whichever returns first through validation and the merge while the other keeps running — **one validation at a time**, because that is the step that runs in the orchestrator's own context — then refills the freed lane. Merge order is acceptance order, never dispatch order: the second lane's branch was cut from the run branch before the first lane's merge landed on it, so its merge may conflict, which the ordinary conflict path above handles (abort, `pm_retry` with the conflicting paths, park on a second conflict) — and that retry keeps its lane and branch instead of spending `--max`. `--max` and the every-3-accepted-tasks health check both count across the two lanes. Nothing compatible on the board is not an error: lane B idles until lane A is accepted. The reasoning — the four compatibility rules, why two lanes and not three, and the merge-order rule — is in [`orchestrate-design.md`](orchestrate-design.md) under *Lanes*.

**Projected reads in pre-flight and planning:** The orchestrator's own reads are projected, because every one of them is charged to the run that has to survive a whole sprint. Pre-flight step 1 takes the sprint with `pm_list_sprints(status="active", brief=True)` (identity and state; the sprint goal is not something the loop acts on) and step 3 classifies claims from `pm_board(brief=True)`, which keeps `claimed_by_run`, `claim_age` and `stale` while dropping the story labels, readiness blockers and hints. Plan step 5 reads the sprint's stories in **one** projected call — `pm_batch_get(ids=<sprint story ids>, fields="title,status,points,depends_on,acceptance_criteria,body")` — instead of an unprojected `pm_get` per story: the plan needs bodies, acceptance criteria and the dependency/point wiring, and nothing else the full item carries. Pre-flight no longer fetches a per-run `pm_context` brief at all; `pm_grab` returns the task and story context a worker acts on, and a worker that needs the project docs is routed to them by `/pm-do`. The validation read at step 16 is projected for the same reason (`pm_get(<task-id>, fields="status,assignee")`), as is the points read in Phase 4.

**Worker prompt and report shape:** The prompt a worker is dispatched with carries the task and story ids and titles, the acceptance criteria, the DoD, the run id, the retry or resume line when there is one, and the safety rules — and no project-context excerpt: that paste was the bulk of the prompt and the same bytes every dispatch, while `pm_grab` already returns the task and story context the worker acts on and `/pm-do` routes it to the project docs if it needs them. The report is capped in the same spirit: **under about 1,500 characters, no code and no log output**, in a fixed order — files changed (paths only); tests as `command -> pass|fail (n passed)`; DoD met; DoD unmet; blockers. The first four map straight onto the `evidence` argument of the verdict verb, and the cap keeps a dispatch from leaving a page of pasted diffs and test output resident in the orchestrator's context for the rest of the sprint. `/pm-do` states the same shape, so a worker reports identically whether it was dispatched or invoked by hand.

**Reads discipline during a run:** Pre-flight step 4 reads `git status --short` — the modified list, which after Phase 0's clean-tree gate is `.project/` — and when that list runs past **200 entries** it warns and names the fix — commit or clean first — because step 23 and every dispatch walk it again; `--auto` continues past the warning and Phase 4 reports it. And for the whole run the orchestrator reads store tools and the files a verdict needs, **never memory files under `~/.claude` and never session transcripts**: they have no projection so they are read whole, and what they carry is a prior session's recollection of facts the store already holds. The reasoning for both is in [`orchestrate-design.md`](orchestrate-design.md) under *Pre-flight and claim classification*.

**Validation by a validator subagent:** After a worker returns, step 16 has the orchestrator read the task itself — `pm_get(<task-id>, fields="status,assignee")` — and then step 17 spawns a **second** subagent, the validator, on the same executor model, foreground and without a worktree. The validator is given the task id, the run id, the DoD list and the run branch, task branch, worktree path and sha the worker reported, and it is the one that runs `git diff --stat <run branch>...<task branch>` and `git diff --name-only` — the touched-path list the forbidden-file check is judged from — and the DoD's tests in the task's own worktree; the orchestrator never runs them itself. It answers with a single JSON object of at most ~1,500 characters — `{"verdict": "accept|retry|park|review", "files": [...], "tests": [{"command", "passed", "summary"}], "dod_met": [...], "dod_unmet": [...], "note": "<=200 chars"}` — and step 19 maps it straight through: `verdict` picks the verb (`pm_accept`, `pm_retry`, `pm_park`, `pm_review`), `note` becomes the note, and the remaining fields become the `evidence` argument. Independence is unchanged — the agent that wrote the code is still never the agent whose word is taken for it — but the test output and diff stats now land in a context that is discarded instead of accumulating in the orchestrator's for the rest of the sprint. A validator that returns nothing, prose, or JSON without a usable `verdict` counts as one validation failure: it is re-run once, and a second empty answer parks the task with the note `validator returned no verdict`. The reasoning is in [`orchestrate-design.md`](orchestrate-design.md) under *The validator subagent*.

**Run id and claim recovery:** Phase 0 mints one run id for the run — `orch-<date>-<random>` — and passes it as `run_id=` on every `pm_grab`, `pm_release` and verdict verb, including the id pasted into each worker prompt. The store keeps it on the task as `claimed_by_run` and stamps it on the activity-log event. Pre-flight step 3 then classifies every in-progress task from that data instead of asking a human: `pm_active` reports `claimed_by_run`, `claim_age`, `stale: true` and a `stale_tasks` list (threshold `stale_claim_hours`, default 2, overridable per call with `stale_after=`). A claim held by an earlier `orch-` run that is stale, or whose run id stops appearing in `pm_activity(item_id=..., event_type="update")` after its last claim, is taken back with `pm_grab(<id>, run_id=<this run>)` and logged as `recovered from run <old>`; a claim that is fresh and still active is listed and left alone (skipped under `--auto`); a claim held by a human or any non-`orch-` id is never touched. See [`pm_active`](mcp-tools.md#pm_activetag-limit-offset-stale_after) and [claim ownership](file-formats.md#claim-ownership--claimed_at--claimed_by_run).

**Final report, rebuilt from the log:** Phase 4 does not summarise from the orchestrator's memory of a loop that may have run for hours. Step 22 calls `pm_activity(run_id=<this run>)` — paging with `offset` while the response reports `has_more: true` — and derives every section of the report from the returned entries: accepted (`status: ... → done`, with the evidence one-liner read back from `pm_run_log`), retried (`→ todo`), parked versus accept-as-review (both `→ review`, separated by the run-log outcome `blocked` vs `partial`), recovered claims (`claimed_by_run: <old run> → <this run>`), releases, stories closed (`pm_accept` stamps the closure with the run that caused it), points moved (one projected `pm_get` over the accepted ids) and untouched tasks (the plan minus all of the above). The lists the orchestrator kept while looping are a **cross-check, not the source**: where the two disagree the log wins and the disagreement is reported outright, since a mismatch means a write that never landed. Step 23 covers what the log cannot — it records which items moved, never which files did: `git diff --stat HEAD...<run branch>` for the code the run produced and `git status --short -- .project/` for the store, plus the run's branches sorted into **merged**, **unmerged** (parked or accept-as-review) and **abandoned** (released), by reading `git branch --list 'orch/<run-id>/*'` against `git branch --merged <run branch>`. Edits that are not claims or verdicts (the step 3 recovery note, the step 24 sprint close) are tagged with the same `run_id=` so they land in that slice too. See [`pm_activity`](mcp-tools.md#pm_activityitem_id-event_type-from_date-to_date-actor-run_id-limit-offset).

**Resume after a crash (`--resume <run-id>`):** A run that dies mid-loop leaves claims behind, so the skill has a documented resume path (section *Resume*, with the reasoning in `docs/reference/orchestrate-design.md`). `--resume <old-run-id>` adopts that run's claims as one decision instead of leaving step 3 to infer them task by task; without the flag, step 3's per-claim classification applies unchanged. The resuming run **mints its own fresh id** rather than reusing the old one — reuse would merge two processes into one `pm_activity(run_id=)` slice — and records the lineage on each adopted claim as a `recovered from run <old>` run-log note. It reads the dead run's record with `pm_activity(run_id=<old>)`, paging on `has_more`, and sorts what it finds: tasks still `in-progress` under the old id are **adopted** (`pm_grab(<id>, run_id=<this run>)`, which resets `claimed_at`), tasks already `done` are **left** (the verdict landed), and tasks released, parked or back in `todo` are **left and reported** — those were deliberate decisions of the dead run. An adopted task is re-dispatched as a **retry**, never as fresh work: its worker may have left partial edits, so the worker prompt carries an `<on resume: ...>` line telling it that the previous run died mid-task and to validate the working-tree state first. Claims held by other runs remain step 3's business, and a claim held by a human — or any `claimed_by_run` without the `orch-` prefix — is never adopted. Phase 4 names the resumed run id and lists the adopted claims. Do not resume when a human holds the claim, when the old run's last event is a verdict on a task that is now done, when the old run is still emitting events (it is alive, not dead), or when the id matches no activity entries at all.

**Health check:** Pre-flight runs `pm_audit` and records the `digest: <16 hex>` line from the report as the *last audit digest*. Every 3 accepted tasks the loop re-runs `pm_audit(since=<last audit digest>)`: an `unchanged: true` answer (under 100 bytes, no checks run) passes the check outright, and anything else is a full report — the run stops on a new ERROR-level finding, otherwise the digest is refreshed and the loop continues. The repeat is the point: it is what catches drift mid-run, so `pm_audit` is never cached per session — `since` removes the cost without removing the poll. See [`pm_audit`](mcp-tools.md#pm_auditinclude_info-since).

**Cleanup and hand-off:** Once Phase 4 has listed the branches, the Stop Conditions clean up after the run: the worktree and branch of every merged task are removed (`git worktree remove <path>`, `git branch -d <task branch>`), a parked or accept-as-review task keeps both so a human can read or salvage the attempt, and the run worktree goes last, after the listing that named it. The run then prints the one-line merge instruction — `git merge --no-ff <run branch>` — because its product is a branch the user reads and merges, never a push.

**Note:** Has `disable-model-invocation: true` — only runs when explicitly invoked with `/pm-orchestrate`.

**Design rationale:** why the loop runs at most two lanes with one worktree per task, why the run id is minted and spent the way it is, why validation is delegated to a subagent whose context is discarded and why its report is bounded and JSON-shaped, what each worker safety rule was bought with, and the full resume protocol are in [`orchestrate-design.md`](orchestrate-design.md). The skill itself is instruction only.

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

## /pm-next

Read, save or clear the short note the next session should see first — the one that carries "we decided to fix X by doing Y and Z" across a context clear.

```
/pm-next                          # read the note back
/pm-next we decided to fix the    # save a note (replaces what is there)
        cache by keying on digest
/pm-next also check the retry path  # "also"/"add" appends under a dated heading
/pm-next clear                    # delete the note
```

**Workflow:**

1. No arguments — calls [`pm_next`](mcp-tools.md#pm_nexttext-append-clear), restates the note in a sentence or two, proposes the first concrete step it implies, and asks whether to start
2. With text — `pm_next(text=...)`, confirming what was saved; `append=true` when the user says "add" or "also"
3. `clear` — `pm_next(clear=true)`, confirming the note is gone
4. Offers to clear the note once the work it describes is finished

The note is scratch text with one owner and a short life: plain markdown in `.project/NEXT.md`, deliberately not a story or an epic, not indexed, not audited, not returned by `pm_search`. It is committed with the rest of `.project/`, so it travels with the project. `pm_context` returns it ahead of everything else under `next_time`, so a fresh session sees it without anyone remembering it exists — `/pm-next` is for writing it, reading it back on demand, and retiring it. See [A note to the next session](../user-guide/daily-workflow.md#a-note-to-the-next-session).

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
