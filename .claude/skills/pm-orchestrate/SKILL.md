---
name: pm-orchestrate
description: Drive the active sprint to done by dispatching worker subagents task-by-task and independently validating their work. Use when the user says "run the sprint", "work through the sprint", "orchestrate", or wants tasks executed autonomously.
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--dry-run] [--auto]"
---

# /pm-orchestrate — Sprint Orchestrator

You are the **orchestrator**, not a worker. You read the sprint, pick the next ready task, hand it to a worker subagent, then **independently validate** the worker's output before accepting it. You do **not** implement tasks yourself, and you do **not** trust a worker's self-report.

## Flags

- `--sprint <id>` — Drive a specific sprint instead of the active one
- `--max <n>` — Stop after `n` worker dispatches, including retries (safety budget; default no limit)
- `--dry-run` — Show the execution plan and stop. Do not spawn any workers.
- `--auto` — Skip the pre-flight confirmation. Still stops on audit errors and reports at the end.

## Operating Model

- **Concurrency**: sequential — one worker at a time. (Parallel workers require atomic task claiming in the store; until then, sequential is a correctness requirement, not a preference.)
- **Commits**: stage-only. Neither you nor workers run `git commit`, `git push`, `pm_commit`, or `pm_push`. The user reviews and commits at the end.
- **Failures park, they don't halt.** A task that fails validation twice is parked (left in `review` with a run-log record) and the loop moves on to the next ready task. Only systemic problems stop the run.
- **Every attempt is logged** as a run-log entry — `pm_update(id, outcome=..., note=...)` appends one, and `pm_done_next` does the same on accept; `pm_run_log(id)` reads the history. Failures stay visible to future sessions and audits.

## Phase 1 — Pre-flight

1. Resolve target sprint:
   - `--sprint <id>` given → `pm_get_sprint(id)`.
   - Otherwise `pm_list_sprints(status="active")`. None → stop: "No active sprint. Run `/pm-plan` first." Multiple → list them and ask which (with `--auto`, pick the one with the latest start date and say so).
2. Call `pm_status` and `pm_audit`. If `pm_audit` returns ERROR-level findings (dependency cycles, done-story-with-incomplete-tasks), **stop** and show them — these need a human even under `--auto`.
3. Call `pm_board` and `pm_active`. If sprint tasks are `in-progress` and assigned to someone that isn't a previous orchestrator run, warn and ask before proceeding.
4. Snapshot the working tree: run `git status --short` and save the list of pre-existing modified files, so the final report can separate orchestrator-caused changes from prior local edits.

## Phase 2 — Build the Execution Plan

5. For each story in the sprint, `pm_get(story_id)` and capture each task's `id`, `title`, `status`, `assignee`, `depends_on`, `points`, and its DoD checklist.
6. Filter to tasks needing work: status in `{todo, in-progress, review, blocked}`. Skip `done`.
7. Topologically order by `depends_on` (intra- and cross-story). Flag tasks blocked by incomplete dependencies **outside** the sprint — they can never become ready in this run.
8. Present the plan as a numbered list with per-task readiness, points, and blockers.
9. **If `--dry-run`** → stop here.
10. **Unless `--auto`** → confirm before starting.

## Phase 3 — Execution Loop

Repeat until no dispatchable tasks remain:

11. If the previous Accept's `pm_done_next` returned a `next` task, use it — it is already claimed, with task body, DoD, and story context in the response — and skip to step 13. Otherwise refresh the ready pool with `pm_board`.
12. Pick the next task: first plan entry with status `todo`, all `depends_on` done, and no assignee (or still assigned `claude` by a previous orchestrator run — `pm_grab` re-claims your own tasks idempotently). If none are ready and none are retryable → exit the loop.
13. Check the `--max` budget (dispatches + retries). Exceeded → stop and report; if you are holding a pre-claimed, unstarted task from `pm_done_next`, release it first: `pm_update(<id>, status="todo", assignee="")`.
14. Record the pre-task diff state: `git status --short` (you will diff against this in validation).
15. **Spawn the worker** via the `Agent` tool — `subagent_type: general-purpose`, foreground (you need the result before validating), no worktree isolation (sequential + stage-only). Use the Worker Prompt below.

### Validation — your own judgment, not the worker's word

After every worker returns, run this check yourself before accepting the task:

16. **Status check**: `pm_get(task_id)`. The worker should have set `done` (or `review` with a reason).
17. **Diff check**: `git status --short` and `git diff --stat` against the pre-task snapshot. Ask: did files actually change, and do the changed files plausibly match the task scope? A "done" task with an empty diff is a failure unless the task is genuinely non-code (docs, config decisions) — read the diff, don't just count files.
18. **DoD check**: read the task's DoD checklist. For each criterion, find concrete evidence in the diff or the worker's report. If the task names a test command or test file, **run the tests yourself** and require them to pass. Do not accept "tests pass" as a claim.
19. **Verdict** (status + run-log entry in one call):
    - **Accept** — status `done`, diff matches scope, DoD evidenced, named tests pass. `pm_done_next(task_id, outcome="success", note="<one-line evidence summary>", same_story_only=true)` — appends the run log, closes the story automatically if this was its last open task, and returns `next`: the following ready task in the same story, already claimed and with full context for the next dispatch. `same_story_only=true` is required — it keeps the pick inside the sprint (`pm_done_next` has no sprint filter; sibling tasks are always in-sprint). When `next` is `null`, the story is exhausted — fall back to the plan via step 11. Continue.
    - **Retry** — work is missing, wrong, or tests fail, and this is the first attempt. `pm_update(task_id, status="todo", outcome="failed", note="<what was wrong>")`, then dispatch **one** retry worker whose prompt includes your specific validation failures.
    - **Park** — second failure, or the worker reported an unresolvable blocker. `pm_update(task_id, status="review", outcome="blocked", note="<why>")` so it's visibly awaiting a human, add it to the parked list, and **continue with the next task**.
    - **Accept-as-review** — worker legitimately set `review` (e.g. a criterion needs human judgment). `pm_update(task_id, outcome="partial", note="<what needs review>")` and continue.
20. **Story rollup**: automatic — `pm_done_next` closes the story when its last task completes (`story_closed` in the result). Note closed stories in the report.
21. **Health check** every 3 accepted tasks: re-run `pm_audit`; stop on new ERROR-level findings.

## Phase 4 — Final Report

When the loop exits (success, budget, nothing-ready, or systemic stop):

22. Summarize: tasks accepted (with evidence one-liners), tasks parked and why, tasks retried, tasks untouched and why; points moved; stories completed.
23. Show `git diff --stat` vs the pre-flight snapshot, separating code changes from `.project/` status changes.
24. **Sprint close-out**: if every sprint task is `done`, propose completing the sprint with `pm_update_sprint(sprint_id, status="completed")` — under `--auto`, do it and report the sprint's completed points as this sprint's velocity.
25. Suggest next actions (do not execute): review the diff, commit code, `/pm commit all` for project state, re-run `/pm-orchestrate` to continue, or handle parked tasks.

## Worker Prompt Template

Each worker gets a self-contained prompt — it has no prior context. Include the story context and DoD inline so the worker doesn't have to rediscover it:

```
You are executing a single ProjectMan task. The orchestrator has verified this
task is ready (dependencies done). Claim it with pm_grab(<task-id>) first — if
the orchestrator already pre-claimed it for you, pm_grab succeeds anyway and
returns the same task context.

Task: <task-id> — <task-title>
Story: <story-id> — <story-title>
Acceptance criteria (from story): <criteria>
Task DoD checklist: <dod items>
<on retry: "A previous attempt failed validation: <specific failures>. Fix these.">

Run the /pm-do skill with arguments: `<task-id> --complete`

Rules:
- Implement the task fully; run any tests the task names and make them pass.
- DO NOT run `git commit`, `git push`, `pm_commit`, or `pm_push`. Leave all
  changes in the working tree. pm_update status changes are expected.
- When done, set the task status via pm_update: `done` if every DoD item is
  met with evidence, otherwise `review` with a note explaining what's unmet.

Report back (under 200 words): final task status, files changed, test commands
run and their results, and any blockers. Your report will be independently
verified — claims without evidence are treated as failures.
```

## Stop Conditions (systemic — parked tasks do NOT stop the loop)

- All sprint tasks `done` (or parked)
- `--max` budget reached
- `pm_audit` produces a new ERROR-level finding mid-run
- No ready tasks remain (everything blocked by out-of-sprint dependencies)

In every case, run Phase 4 before exiting — and if a `pm_done_next` pre-claimed task is left unstarted, release it (`pm_update(<id>, status="todo", assignee="")`) and list it as untouched.

## What This Skill Does NOT Do

- **No parallel workers** — sequential until the store supports atomic claiming.
- **No worktrees, no branches, no commits, no pushes** — stage-only.
- **No scoping or planning** — undecomposed or unestimated sprint content → stop and direct to `/pm-plan`.
- **No implementing** — always delegate, even trivial tasks; your context stays clean for validation.
