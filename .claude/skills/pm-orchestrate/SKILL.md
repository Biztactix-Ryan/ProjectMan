---
name: pm-orchestrate
description: Drive the active sprint to done by dispatching worker subagents task-by-task and independently validating their work. Use when the user says "run the sprint", "work through the sprint", "orchestrate", or wants tasks executed autonomously.
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--orchestrator-model <m>] [--executor-model <m>] [--dry-run] [--auto]"
---

# /pm-orchestrate — Sprint Orchestrator

You are the **orchestrator**, not a worker. You read the sprint, pick the next ready task, hand it to a worker subagent, then **independently validate** the worker's output before accepting it. You do **not** implement tasks yourself, and you do **not** trust a worker's self-report.

## Flags

- `--sprint <id>` — Drive a specific sprint instead of the active one
- `--max <n>` — Stop after `n` worker dispatches, including retries (safety budget; default no limit)
- `--orchestrator-model <m>` — Model to run orchestration/validation on. You are already running in a fixed session model, so this is advisory: if the session model differs, the skill notes it once rather than switching. Default **Fable 5**.
- `--executor-model <m>` — Model each spawned worker runs on (passed as the `model` argument to the `Agent` tool). Default **Opus 4.8** → `model="opus"`.
- `--dry-run` — Show the execution plan and stop. Do not spawn any workers.
- `--auto` — Skip the pre-flight confirmation. Still stops on audit errors and reports at the end.

## Operating Model

- **Concurrency**: sequential — one worker at a time. (Parallel workers require atomic task claiming in the store; until then, sequential is a correctness requirement, not a preference.)
- **Commits**: stage-only. Neither you nor workers run `git commit`, `git push`, `pm_commit`, or `pm_push`. The user reviews and commits at the end.
- **Failures park, they don't halt.** A task that fails validation twice is parked (left in `review` with a run-log record) and the loop moves on to the next ready task. Only systemic problems stop the run.
- **Every attempt is logged** as a run-log entry — the verdict verbs (`pm_accept`, `pm_retry`, `pm_park`, `pm_review`) append one structurally and cannot be called without a note, so no verdict lands without a record; `pm_run_log(id)` reads the history. The evidence rides along as structured fields (files, tests, DoD), not prose, so it stays queryable: `pm_run_log(id, has_evidence=true)` returns only the attempts that proved something, `has_evidence=false` only those that did not, and `pm_audit` raises `done-without-evidence` as a **warning** when a task is done with no evidence on its log. Failures stay visible to future sessions and audits.

## Phase 0 — Model Selection

Big model orchestrates, cheaper model executes. Resolve both models **before** pre-flight and use the executor model for every worker spawn.

**Defaults (current as of this skill's authoring):**

| Role | Default | How it's applied |
|------|---------|------------------|
| **Orchestrator** (this session — planning + validation) | **Fable 5** | Session model — advisory, see below |
| **Executor** (spawned workers — implementation) | **Opus 4.8** | `Agent(..., model="opus")` |

The `Agent` tool's `model` override only accepts coarse tiers — `fable`, `opus`, `sonnet`, `haiku` — not point releases. Map the resolved executor model to its tier (Opus 4.8 → `opus`, Sonnet 5 → `sonnet`, etc.).

- **Executor** — use `--executor-model` if given, else the default (`opus`). This tier is passed to every `Agent` call in step 15.
- **Orchestrator** — use `--orchestrator-model` if given, else the default (Fable 5). You cannot switch the running session's model, so this is advisory: if the current session model is weaker than the resolved orchestrator model, say so once ("For best results, run `/pm-orchestrate` on Fable 5") and continue — do not stop.
- **Newer-model check** — the defaults above assume Fable 5 / Opus 4.8 are the top two tiers. If you are aware of a model **newer or more capable** than either default, do **not** silently fall back to the default: call `AskUserQuestion` to let the user choose the orchestrator and executor models, offering the newer model as an option. Skip this prompt (and use the resolved defaults/flags) when `--auto` is set or when both `--orchestrator-model` and `--executor-model` are explicitly provided. If the defaults are still the newest models available, run silently.

State the resolved orchestrator/executor pair in the pre-flight summary.

## Phase 1 — Pre-flight

1. Resolve target sprint:
   - `--sprint <id>` given → `pm_get_sprint(id)`.
   - Otherwise `pm_list_sprints(status="active")` — left unprojected on purpose: the active list is one or two sprints and `brief=True` would drop the goal you want for the pre-flight summary. None → stop: "No active sprint. Run `/pm-plan` first." Multiple → list them and ask which (with `--auto`, pick the one with the latest start date and say so).
2. Call `pm_status` and `pm_audit`. If `pm_audit` returns ERROR-level findings (dependency cycles, done-story-with-incomplete-tasks), **stop** and show them — these need a human even under `--auto`.
3. Call `pm_board` and `pm_active`. If sprint tasks are `in-progress` and assigned to someone that isn't a previous orchestrator run, warn and ask before proceeding.
4. Snapshot the working tree: run `git status --short` and save the list of pre-existing modified files, so the final report can separate orchestrator-caused changes from prior local edits.
4b. **Project context — fetched once, reused by every worker**: call `pm_context(max_doc_chars=2000, limit=5)` once, here in pre-flight. Keep the architecture / security / conventions portion of the result — hub architecture plus `PROJECT.md`, `INFRASTRUCTURE.md`, `SECURITY.md` — as the verbatim excerpt you will paste into every worker prompt's `Project context:` section. Drop the active epic/story lists: each worker already receives its story context from `pm_grab`. The bounds are the point — at most five docs are embedded, so 2,000 chars each holds the whole return near 10k, and `limit=5` keeps the list section short; an unbounded `pm_context` returned 48,588 chars in one study, and that is a per-worker cost this step exists to avoid. Fetch it **once per run** and reuse the same excerpt for every worker, including retries — never re-fetch per worker.

## Phase 2 — Build the Execution Plan

5. For each story in the sprint, `pm_get(story_id)` and capture each task's `id`, `title`, `status`, `assignee`, `depends_on`, `points`, and its DoD checklist. No `fields=` projection here: the plan is built out of the task bodies and their DoD checklists, so this one genuinely needs the full item.
6. Filter to tasks needing work: status in `{todo, in-progress, review, blocked}`. Skip `done`.
7. Topologically order by `depends_on` (intra- and cross-story). Flag tasks blocked by incomplete dependencies **outside** the sprint — they can never become ready in this run.
8. Present the plan as a numbered list with per-task readiness, points, and blockers.
9. **If `--dry-run`** → stop here.
10. **Unless `--auto`** → confirm before starting.

## Phase 3 — Execution Loop

Repeat until no dispatchable tasks remain:

11. If the previous Accept's `pm_accept` returned a `next` task, use it — it is already claimed, with task body, DoD, and story context in the response — and skip to step 13. Otherwise refresh the ready pool with `pm_board`.
12. Pick the next task: first plan entry with status `todo`, all `depends_on` done, and no assignee (or still assigned `claude` by a previous orchestrator run — `pm_grab` re-claims your own tasks idempotently). If none are ready and none are retryable → exit the loop.
13. Check the `--max` budget (dispatches + retries). Exceeded → stop and report; if you are holding a pre-claimed, unstarted task from `pm_accept`, release it first: `pm_release(<id>, note="<why it was released>")`.
14. Record the pre-task diff state: `git status --short` (you will diff against this in validation).
15. **Spawn the worker** via the `Agent` tool — `subagent_type: general-purpose`, `model:` the resolved executor tier from Phase 0 (default `"opus"`), foreground (you need the result before validating), no worktree isolation (sequential + stage-only). Use the Worker Prompt below.

### Validation — your own judgment, not the worker's word

After every worker returns, run this check yourself before accepting the task:

16. **Status check**: `pm_get(task_id, fields="status,assignee")` — the read is deliberate (trust-but-verify; never remove it) and projection makes it nearly free, tens of chars instead of thousands, so there is no reason to skip it. Check both fields: `status` should be `done` (or `review`, whose reason lives in the worker's report and the run log, not in this projected read — `pm_run_log(task_id, limit=1)` if you need it back), and `assignee` should still be the worker's `claude` — an unexpected assignee means someone else touched the task while it ran.
17. **Diff check**: `git status --short` and `git diff --stat` against the pre-task snapshot. Ask: did files actually change, and do the changed files plausibly match the task scope? A "done" task with an empty diff is a failure unless the task is genuinely non-code (docs, config decisions) — read the diff, don't just count files. **Keep the list of changed files** as you read it; it is the `files` list step 19 records.
18. **DoD check**: read the task's DoD checklist. For each criterion, find concrete evidence in the diff or the worker's report. If the task names a test command or test file, **run the tests yourself** and require them to pass. Do not accept "tests pass" as a claim. **Keep two more lists as you go**: every test command you ran with its pass/fail result and a short summary, and every DoD criterion you found evidence for versus the ones you did not. With all three lists in hand, step 19 is a transcription, not a recollection.
19. **Verdict** — each of the four verdicts has its own verb, and the verb fixes status and outcome; the note and the evidence are yours to write. Status and run-log entry land in one call, and the note is required, so a verdict cannot be passed without saying why. **The note is ONE line, at most 200 characters — a human summary of what happened.** The three lists you collected in steps 17–18 go in `evidence` (`files`, `tests` with `command`/`passed`/`summary`, `dod_met`, `dod_unmet`), never in the note: prose is not the container for a list. If a response comes back with `note_long: true` you over-wrote the note — move that detail into `evidence` next time.
    - **Accept** — status `done`, diff matches scope, DoD evidenced, named tests pass. `pm_accept(task_id, note="<one line>", evidence={...})` — the note summarises, the evidence proves:

      ```
      pm_accept(task_id, note="all DoD met; 47 tests pass",
                evidence={"files": ["src/projectman/store.py", "tests/test_store.py"],
                          "tests": [{"command": "uv run pytest tests/test_store.py",
                                     "passed": true, "summary": "47 passed"}],
                          "dod_met": ["evidence stored on entry", "old lines still parse"]})
      ```

      It appends the run log, closes the story automatically if this was its last open task (`story_closed` in the result), and returns `next`: the following ready task in the same story, already claimed and with full context for the next dispatch. `same_story_only` now defaults to **true**, which is what you want — it keeps the pick inside the sprint (there is no sprint filter; sibling tasks are always in-sprint). When the story is exhausted the result is the expected negative `no_next_task` with `next: null` — the completion still landed; fall back to the plan via step 11. Continue.
    - **Retry** — work is missing, wrong, or tests fail, and this is the first attempt. `pm_retry(task_id, note="<what was wrong>", evidence={"tests": [{"command": "uv run pytest -q", "passed": false, "summary": "3 failed"}]})` — carry the failing test entries so the next attempt inherits them; it resets the task to `todo` and clears the assignee — then dispatch **one** retry worker whose prompt includes your specific validation failures.
    - **Park** — second failure, or the worker reported an unresolvable blocker. `pm_park(task_id, note="<why>", evidence={"tests": [<the failing entries>], "dod_unmet": ["<criterion still open>"]})` so it's visibly awaiting a human and the gap is on record, add it to the parked list, and **continue with the next task**.
    - **Accept-as-review** — worker legitimately set `review` (e.g. a criterion needs human judgment). `pm_review(task_id, note="<what needs review>", evidence={"dod_met": ["<what you verified>"], "dod_unmet": ["<what needs human judgment>"]})` and continue.
20. **Story rollup**: automatic — `pm_accept` closes the story when its last task completes (`story_closed` in the result). Note closed stories in the report.
21. **Health check** every 3 accepted tasks: re-run `pm_audit`; stop on new ERROR-level findings.

## Phase 4 — Final Report

When the loop exits (success, budget, nothing-ready, or systemic stop):

22. Summarize: tasks accepted (with evidence one-liners — read them back from `pm_run_log(id)` rather than from memory, since step 19 recorded them structurally), tasks parked and why, tasks retried, tasks untouched and why; points moved; stories completed.
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

Project context (bounded pm_context excerpt, fetched once for this run —
architecture, security, and conventions only; the active epic/story lists are
omitted because pm_grab already hands you the story context):
<architecture / security / conventions excerpt>

Task DoD checklist: <dod items>
<on retry: "A previous attempt failed validation: <specific failures>. Fix these.">

Run the /pm-do skill with arguments: `<task-id> --complete`

Rules:
- Implement the task fully; run any tests the task names and make them pass.
- The Project context above is a bounded excerpt; if you need more of a
  document than it shows, call pm_context(max_doc_chars=...) yourself.
- DO NOT run `git commit`, `git push`, `pm_commit`, or `pm_push`. Leave all
  changes in the working tree. pm_update status changes are expected.
- When done, set the task status via pm_update: `done` if every DoD item is
  met with evidence, otherwise `review` with a note explaining what's unmet.

Report back (under 200 words): final task status, then three explicit lists —
files changed, each test command you ran with pass/fail, and DoD items met vs
unmet — plus any blockers. Give them as lists, not prose: the orchestrator
transcribes them into structured evidence. Your report will be independently
verified — claims without evidence are treated as failures.
```

## Stop Conditions (systemic — parked tasks do NOT stop the loop)

- All sprint tasks `done` (or parked)
- `--max` budget reached
- `pm_audit` produces a new ERROR-level finding mid-run
- No ready tasks remain (everything blocked by out-of-sprint dependencies)

In every case, run Phase 4 before exiting — and if a `pm_accept` pre-claimed task is left unstarted, release it first: `pm_release(<id>, note="<why it was released>")` — and list it as untouched.

## What This Skill Does NOT Do

- **No parallel workers** — sequential until the store supports atomic claiming.
- **No worktrees, no branches, no commits, no pushes** — stage-only.
- **No scoping or planning** — undecomposed or unestimated sprint content → stop and direct to `/pm-plan`.
- **No implementing** — always delegate, even trivial tasks; your context stays clean for validation.
