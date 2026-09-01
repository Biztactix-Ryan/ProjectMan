---
name: pm-orchestrate
description: Drive the active sprint to done by dispatching worker subagents task-by-task and independently validating their work. Use when the user says "run the sprint", "work through the sprint", "orchestrate", or wants tasks executed autonomously.
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--orchestrator-model <m>] [--executor-model <m>] [--resume <run-id>] [--dry-run] [--auto]"
---

# /pm-orchestrate — Sprint Orchestrator

You are the **orchestrator**, not a worker. You read the sprint, pick the next ready task, hand it to a worker subagent, then **independently validate** the worker's output before accepting it. You do **not** implement tasks yourself, and you do **not** trust a worker's self-report.

## Flags

- `--sprint <id>` — Drive a specific sprint instead of the active one
- `--max <n>` — Stop after `n` worker dispatches, including retries (safety budget; default no limit)
- `--orchestrator-model <m>` — Model to run orchestration/validation on. You are already running in a fixed session model, so this is advisory: if the session model differs, the skill notes it once rather than switching. Default **Fable 5**.
- `--executor-model <m>` — Model each spawned worker runs on (passed as the `model` argument to the `Agent` tool). Default **Opus 4.8** → `model="opus"`.
- `--resume <run-id>` — Pick up after a run that died mid-loop: adopt the claims that run id still holds, instead of leaving step 3 to infer them one task at a time. This run still mints its own id; the old one is carried as lineage. Full procedure under **Resume — Picking Up an Interrupted Run**.
- `--dry-run` — Show the execution plan and stop. Do not spawn any workers.
- `--auto` — Skip the pre-flight confirmation. Still stops on audit errors and reports at the end.

## Operating Model

- **Concurrency**: sequential — one worker at a time. (Parallel workers require atomic task claiming in the store; until then, sequential is a correctness requirement, not a preference.)
- **Commits**: stage-only. Neither you nor workers run `git commit`, `git push`, `pm_commit`, or `pm_push`. The user reviews and commits at the end.
- **Failures park, they don't halt.** A task that fails validation twice is parked (left in `review` with a run-log record) and the loop moves on to the next ready task. Only systemic problems stop the run.
- **Every attempt is logged** as a run-log entry — the verdict verbs (`pm_accept`, `pm_retry`, `pm_park`, `pm_review`) append one structurally and cannot be called without a note, so no verdict lands without a record; `pm_run_log(id)` reads the history. The evidence rides along as structured fields (files, tests, DoD), not prose, so it stays queryable: `pm_run_log(id, has_evidence=true)` returns only the attempts that proved something, `has_evidence=false` only those that did not, and `pm_audit` raises `done-without-evidence` as a **warning** when a task is done with no evidence on its log. Failures stay visible to future sessions and audits.

## Phase 0 — Model Selection and Run Identity

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

### Run id — mint it here, spend it everywhere

Mint one opaque id for this run before pre-flight: `orch-<YYYY-MM-DD>-<4 random hex>` (e.g. `orch-2026-08-22-7f3a`). The `orch-` prefix is load-bearing — step 3 reads it to tell an orchestrator's claim from a human's — and the random tail must differ run to run, so a restart never collides with the run it is recovering from.

Pass it as `run_id=<this run>` on **every** call that takes or clears a claim: `pm_grab`, `pm_release`, and the verdict verbs (`pm_accept`, `pm_retry`, `pm_park`, `pm_review`). Paste it into every worker prompt as well, so a worker's own `pm_grab` claims under the same id. The store records it on the task as `claimed_by_run`, and `pm_activity` renders it as `run <id>` after the actor — together those are what make a crashed run's claims recoverable instead of a matter of opinion.

`--resume <old-run-id>` does not change any of this: a resuming run mints a fresh id like every other run and spends it on its own claims, and the run it is recovering from is recorded as lineage rather than reused — see **Resume — Picking Up an Interrupted Run**.

The same id is what the final report is built from: `pm_activity(run_id=<this run>)` returns every event this run produced — claims, releases, verdicts, the story closures those triggered, and any `pm_update` / `pm_update_many` / `pm_update_sprint` you tagged with `run_id=` — so Phase 4 reconstructs what happened from the log instead of from your memory of it. Tag the writes that are not claims (the step 3 recovery note, the step 24 sprint close) with the same `run_id=` or they will be missing from that slice.

## Phase 1 — Pre-flight

1. Resolve target sprint:
   - `--sprint <id>` given → `pm_get_sprint(id)`.
   - Otherwise `pm_list_sprints(status="active")` — left unprojected on purpose: the active list is one or two sprints and `brief=True` would drop the goal you want for the pre-flight summary. None → stop: "No active sprint. Run `/pm-plan` first." Multiple → list them and ask which (with `--auto`, pick the one with the latest start date and say so).
2. Call `pm_status` and `pm_audit`. If `pm_audit` returns ERROR-level findings (dependency cycles, done-story-with-incomplete-tasks), **stop** and show them — these need a human even under `--auto`. Then record the `digest: <16 hex>` line under the report's title as the **last audit digest**: step 21 passes it back as `since=` so an unchanged health check answers in a few bytes instead of a full report.
3. **Classify every in-progress claim — from the data, never a guess.** Call `pm_board` and `pm_active`. Each in-progress task carries `claimed_by_run` (the run holding the claim), `claim_age` (seconds since it was claimed) and `stale: true` once that age passes `stale_after_hours` (config `stale_claim_hours`, default 2; override for one call with `pm_active(stale_after=<hours>)`), and the response names the stale ids outright under `stale_tasks`. For each in-progress task in the sprint, branch on `claimed_by_run`:
   - **This run's id** — impossible on a fresh start, since you minted it in Phase 0. Treat it as the previous-run case below.
   - **A previous orchestrator run** (`claimed_by_run` starts with `orch-`) — call `pm_activity(item_id=<task-id>, event_type="update")` and read the newest entries: claim, release and verdict events render `run <id>` after the actor, so the log says which run last acted on the task and when. **Reclaim** it when the task is `stale: true`, or when that run is known-dead — no activity entry carries its `run_id` after its last claim on the task. Reclaiming is `pm_grab(<task-id>, run_id=<this run>)`: a different run under the same `claude` assignee takes the claim and resets `claimed_at`. Then put the recovery on the record — `pm_update(<task-id>, outcome="info", note="recovered from run <old-run-id>", run_id=<this run>)` — so the next reader sees it too, and so step 22 finds the recovery in this run's own slice of the log. Not stale and still emitting events → that run may still be live: list the task in the report and, under `--auto`, skip it this run rather than racing it.
   - **A human, or any run id without the `orch-` prefix** — never touch it, however old the claim. List it in the report as someone else's work.
   No warning, no confirmation prompt: `claimed_by_run`, `claim_age` and `stale` decide every case the old step referred to a human. The single exception is a genuinely ambiguous *human* claim — an unattributable non-`orch-` id sitting on a task the plan needs — which is worth one question, and is skipped under `--auto`.
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
12. Pick the next task: first plan entry with status `todo`, all `depends_on` done, and no assignee — or one step 3 classified as recoverable, which `pm_grab(<id>, run_id=<this run>)` takes back (a re-claim by your own run id is idempotent and keeps the original `claimed_at`; a dead run's claim changes hands and resets it). Never pick a task step 3 left with someone else. If none are ready and none are retryable → exit the loop.
13. Check the `--max` budget (dispatches + retries). Exceeded → stop and report; if you are holding a pre-claimed, unstarted task from `pm_accept`, release it first: `pm_release(<id>, note="<why it was released>", run_id=<this run>)`.
14. Record the pre-task diff state: `git status --short` (you will diff against this in validation).
15. **Spawn the worker** via the `Agent` tool — `subagent_type: general-purpose`, `model:` the resolved executor tier from Phase 0 (default `"opus"`), foreground (you need the result before validating), no worktree isolation (sequential + stage-only). Use the Worker Prompt below, with this run's id pasted in so the worker's own `pm_grab` claims under it rather than under an anonymous per-process id.

### Validation — your own judgment, not the worker's word

After every worker returns, run this check yourself before accepting the task:

16. **Status check**: `pm_get(task_id, fields="status,assignee")` — the read is deliberate (trust-but-verify; never remove it) and projection makes it nearly free, tens of chars instead of thousands, so there is no reason to skip it. Check both fields: `status` should be `done` (or `review`, whose reason lives in the worker's report and the run log, not in this projected read — `pm_run_log(task_id, limit=1)` if you need it back), and `assignee` should still be the worker's `claude` — an unexpected assignee means someone else touched the task while it ran.
17. **Diff check**: `git status --short` and `git diff --stat` against the pre-task snapshot. Ask: did files actually change, and do the changed files plausibly match the task scope? A "done" task with an empty diff is a failure unless the task is genuinely non-code (docs, config decisions) — read the diff, don't just count files. **Keep the list of changed files** as you read it; it is the `files` list step 19 records.
18. **DoD check**: read the task's DoD checklist. For each criterion, find concrete evidence in the diff or the worker's report. If the task names a test command or test file, **run the tests yourself** and require them to pass. Do not accept "tests pass" as a claim. **Keep two more lists as you go**: every test command you ran with its pass/fail result and a short summary, and every DoD criterion you found evidence for versus the ones you did not. With all three lists in hand, step 19 is a transcription, not a recollection.
19. **Verdict** — each of the four verdicts has its own verb, and the verb fixes status and outcome; the note and the evidence are yours to write. Status and run-log entry land in one call, and the note is required, so a verdict cannot be passed without saying why. **The note is ONE line, at most 200 characters — a human summary of what happened.** The three lists you collected in steps 17–18 go in `evidence` (`files`, `tests` with `command`/`passed`/`summary`, `dod_met`, `dod_unmet`), never in the note: prose is not the container for a list. If a response comes back with `note_long: true` you over-wrote the note — move that detail into `evidence` next time.
    - **Accept** — status `done`, diff matches scope, DoD evidenced, named tests pass. `pm_accept(task_id, note="<one line>", run_id=<this run>, evidence={...})` — the note summarises, the evidence proves:

      ```
      pm_accept(task_id, note="all DoD met; 47 tests pass", run_id=<this run>,
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
21. **Health check** every 3 accepted tasks: re-run `pm_audit(since=<last audit digest>)`.
    - Answer contains `unchanged: true` → the check **passes**. Nothing the audit reads has changed, so the findings are necessarily the ones you already cleared; there is no report to read and the last audit digest stays as it is.
    - Otherwise you get the full report: **stop** on new ERROR-level findings as before, and if there are none, record the report's `digest:` as the new last audit digest before continuing.
    - A stale or unknown `since` is never an error — it simply misses and you get the full audit.
    - *Note for reviewers*: the repeated `pm_audit` calls that the usage studies flagged as waste (byte-identical repeats within one session) are **this health check working as designed** — it is what catches drift mid-run. Caching `pm_audit` per session would disable it. `since=` is the right fix: it keeps the poll and removes the cost.

## Phase 4 — Final Report

When the loop exits (success, budget, nothing-ready, or systemic stop):

22. **Rebuild the report from the activity log — it is the record, your memory is only the cross-check.** Call `pm_activity(run_id=<this run>, limit=100)` and keep paging with `offset` while the response reports `has_more: true`, until you hold every event this run produced. One filtered query is the whole record: the run id is stamped on every claim, release and verdict, on the story closures `pm_accept` triggered, and on whatever you tagged by hand. Derive the report's sections from those entries, not from what you remember doing:
    - **Accepted** — task entries ending `status: ... → done`. The evidence one-liner for each is its run-log note: `pm_run_log(<id>, limit=1)`, which is where step 19 wrote it.
    - **Retried** — task entries ending `status: ... → todo` whose `pm_run_log(<id>, limit=1)` outcome is `failed`: that is `pm_retry` putting the task back in the pool.
    - **Parked** and **accept-as-review** — both land on `status: ... → review`, so the log cannot separate them on its own: read `pm_run_log(<id>, limit=1)` and split on the outcome — `blocked` is parked, `partial` is accept-as-review.
    - **Recovered claims** — task entries whose change reads `claimed_by_run: <another orch- id> → <this run>`: a claim step 3 took back from a dead run, or one `--resume` adopted wholesale. Report each as "recovered from run `<old-id>`", and when this was a `--resume` run, name the resumed run id and count the claims adopted from it (see **Resume**, R5).
    - **Released** — the *other* `status: ... → todo` entries: the claim is cleared with no verdict beside it, so the newest run-log outcome is `info`, or there is no entry at all — a pre-claimed task handed back unstarted (step 13, or the stop-condition release). `pm_retry` and `pm_release` write the identical activity entry; only that outcome tells them apart.
    - **Stories closed** — the `UPDATE story <id> ... (status: ... → done)` entries. They carry this run id because `pm_accept` stamps the closure with the run that caused it, so no separate bookkeeping is needed.
    - **Points moved** — one `pm_get(<all accepted ids>, fields="points")` call over the accepted list, summed. Do not total remembered numbers.
    - **Untouched** — the step 5–8 plan minus every id above, each with the reason you already have: blocked by an out-of-sprint dependency, left with someone else by step 3, or never reached before the `--max` budget or a stop condition.
    Now compare that against the lists you kept while looping. **Where the two disagree, the log wins** — report the log's version *and* name the disagreement outright ("I recorded US-X-1 accepted; the log has no verdict for it"), because a mismatch is evidence of a write that never landed or a verdict you believe you passed and did not. Silently preferring either side hides the failure.
23. Show `git diff --stat` vs the step 4 pre-flight snapshot, separating code changes from `.project/` status changes. This is the half of the report the activity log cannot give you: it records what changed in the project store, never what changed in the repository — so the log answers "which tasks moved" and the diff answers "which files moved", and the report needs both.
24. **Sprint close-out**: if every sprint task is `done`, propose completing the sprint with `pm_update_sprint(sprint_id, status="completed", run_id=<this run>)` — under `--auto`, do it and report the sprint's completed points as this sprint's velocity. Pass the run id so the close is part of this run's slice of the log too.
25. Suggest next actions (do not execute): review the diff, commit code, `/pm commit all` for project state, re-run `/pm-orchestrate` to continue, or handle parked tasks.

## Resume — Picking Up an Interrupted Run

A run that dies mid-loop leaves claims behind with no record of intent. `--resume <old-run-id>` is how the next run picks them up deliberately, as one decision over one run's whole record, instead of leaving Phase 1 step 3 to infer them one task at a time. **Without `--resume`, none of this applies** — step 3's classification runs exactly as written, and a stale `orch-` claim is recovered case by case. The building blocks are the same either way: the run id minted in Phase 0, `claimed_by_run` / `claim_age` / `stale` from `pm_active`, and the activity log.

**R1. Mint a new id; carry the old one as lineage.** `--resume` does **not** reuse the old id. Phase 0 mints `orch-<YYYY-MM-DD>-<4 hex>` as it always does, and this run spends that new id on every claim, verdict and release it makes. Each claim it adopts gets the lineage written down instead: `pm_update(<task-id>, outcome="info", note="recovered from run <old-run-id>", run_id=<this run>)`. Reusing the old id would merge two processes into one `pm_activity(run_id=)` slice and leave Phase 4 unable to say which run did what; a lineage note keeps the slices per-process and still links them.

**R2. Read the dead run's record before touching anything.** Call `pm_activity(run_id=<old-run-id>, limit=100)`, paging with `offset` while the response reports `has_more: true`. That is everything the dead run did — its claims, verdicts, releases and story closures. Take the task ids out of it and check each one's current state (`pm_get(<id>, fields="status,assignee,claimed_by_run")`, or the `pm_active` call step 3 already makes), then sort:
   - **Still `in-progress` and still `claimed_by_run: <old-run-id>`** → **adopt**. `pm_grab(<task-id>, run_id=<this run>)` takes the claim — a cross-run re-claim under the same `claude` assignee is allowed and resets `claimed_at` — then write the R1 lineage note. Adopted tasks join this run's plan and are dispatched under R3.
   - **Already `done`** → **leave it**. The dead run's verdict landed; there is nothing to redo and it is not this run's work. Name it on the resume line of the report, not in the accepted list.
   - **Released, parked, or back in `todo`** → **leave the claim alone, and report it**. A `pm_release` or a `pm_park` was a decision that run made on purpose: a parked task is waiting on a human, and a released one is back in the pool where the ordinary step 12 pick will find it if it is ready. Adopting either would overrule a decision that was already made.
   - **Claimed, but `claimed_by_run` is now some other id** → another run already recovered it. Leave it and report it.

**R3. An adopted task is dispatched as a retry, never as fresh work.** Its worker may have died with half-written files in the working tree, and the store records nothing about how far it got. So: snapshot `git status --short` first (step 14, unchanged — that is what lets validation separate this worker's edits from the ones already sitting there), then dispatch through the normal step 15 spawn with the worker prompt's `<on resume: ...>` line filled in — "previous run `<old-run-id>` died mid-task; validate the working tree state first". The dispatch counts against `--max` like any other. If the adopted task then fails validation it is a *first* failure: retry once, then park.

**R4. Claims belonging to runs other than the resumed one stay step 3's business.** `--resume` narrows nothing. After R2, step 3 still classifies every remaining in-progress claim in the sprint exactly as written: stale `orch-` claims recovered with the same `recovered from run <old>` note, live ones listed and skipped under `--auto`, human claims never touched. `--resume <old-run-id>` buys certainty about *one* run's claims; it does not suppress the rest.

**R5. The report says what was adopted, and from whom.** Phase 4 step 22 needs no extra bookkeeping: the adopted claims are exactly the `claimed_by_run: <old-run-id> → <this run>` entries in this run's own slice of the log, and each carries its lineage note. Report them under **Recovered claims** with the resumed run id stated outright — "resumed run `orch-2026-08-21-9c2f`; adopted 2 of its claims" — followed by the tasks R2 chose to leave and the reason for each.

**When NOT to resume.** `--resume` is an instruction to adopt claims, so it is the wrong move whenever the claim is not yours to take:
   - **A human holds it** — any `claimed_by_run` without the `orch-` prefix. Never adopt it, `--resume` or not; that is step 3's rule and the flag does not override it. If that is the only claim the old run left, there is nothing to resume.
   - **The old run's last event is a verdict on a task that is now `done`.** The run finished its last task before it died, so the "claim" you would adopt is a completed one. Report it and fall through to the ordinary loop.
   - **The old run is still emitting events.** It is not dead, it is slow — adopting its claims races a live process. Say so and stop; under `--auto`, skip the adoption and continue with the ordinary plan rather than racing it.
   - **`pm_activity(run_id=<old-run-id>)` returns nothing.** The id is a typo or belongs to another project. Report that the id matched no events and fall back to plain step 3 classification instead of guessing which claims were meant.

## Worker Prompt Template

Each worker gets a self-contained prompt — it has no prior context. Include the story context and DoD inline so the worker doesn't have to rediscover it:

```
You are executing a single ProjectMan task. The orchestrator has verified this
task is ready (dependencies done). Claim it with
pm_grab(<task-id>, run_id=<this run>) first — if the orchestrator already
pre-claimed it for you, pm_grab succeeds anyway and returns the same context.

Task: <task-id> — <task-title>
Story: <story-id> — <story-title>
Orchestrator run id: <this run>
Acceptance criteria (from story): <criteria>

Project context (bounded pm_context excerpt, fetched once for this run —
architecture, security, and conventions only; the active epic/story lists are
omitted because pm_grab already hands you the story context):
<architecture / security / conventions excerpt>

Task DoD checklist: <dod items>
<on retry: "A previous attempt failed validation: <specific failures>. Fix these.">
<on resume: "previous run <old-run-id> died mid-task; validate the working
 tree state first — a partial edit from that attempt may already be there.">

Run the /pm-do skill with arguments: `<task-id> --complete`

Rules:
- Implement the task fully; run any tests the task names and make them pass.
- Pass run_id=<this run> on your pm_grab so the claim is attributable to this
  orchestrator run and recoverable if this run dies.
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
- `pm_audit` produces a new ERROR-level finding mid-run (an `unchanged: true` health check never does — it means the digest matched, so the findings are identical to the last full report)
- No ready tasks remain (everything blocked by out-of-sprint dependencies)
- `--resume <run-id>` named a run that is still emitting events — adopting a live run's claims would race it (see **Resume**, when NOT to resume). Under `--auto` this is not a stop: skip the adoption and drive the ordinary plan instead.

In every case, run Phase 4 before exiting — and if a `pm_accept` pre-claimed task is left unstarted, release it first: `pm_release(<id>, note="<why it was released>", run_id=<this run>)` — and list it as untouched.

## What This Skill Does NOT Do

- **No parallel workers** — sequential until the store supports atomic claiming.
- **No worktrees, no branches, no commits, no pushes** — stage-only.
- **No scoping or planning** — undecomposed or unestimated sprint content → stop and direct to `/pm-plan`.
- **No blind re-run of a dead run's task** — an adopted claim is dispatched as a resume-retry with the working-tree warning in the prompt, never as fresh work.
- **No adopting a claim it does not own** — human claims, and any `claimed_by_run` without the `orch-` prefix, are listed and left alone whatever `--resume` says.
- **No implementing** — always delegate, even trivial tasks; your context stays clean for validation.
