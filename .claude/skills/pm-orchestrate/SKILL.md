---
name: pm-orchestrate
description: Drive the active sprint to done — dispatch and validate workers.
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--lanes <1|2>] [--orchestrator-model|--executor-model <m>] [--resume <run-id>] [--dry-run] [--auto]"
---

# /pm-orchestrate

Dispatch each task, then **independently validate** it. Why: `docs/reference/orchestrate-design.md`.

## Flags

- `--resume <run-id>` — adopt a dead run's claims.
- `--lanes <1|2>` — lanes A and B, default 1.

**No push**: never `git push`, `pm_push`, `pm_commit`. **Every verdict is logged**: verbs need a note and a run-log entry (`pm_run_log(id, has_evidence=true)`). **Reads**: store tools and files a verdict needs, never memory under `~/.claude` or transcripts.

## Phase 0

### Run id

Mint `orch-<YYYY-MM-DD>-<4 hex>`; the `orch-` prefix is load-bearing. Pass `run_id=<this run>` on every claim, verdict, `pm_update*` and prompt; 22 reads `pm_activity(run_id=<this run>)`.

### Run branch

Dirt outside `.project/` (`git status --short`) **stops the run**: report the dirty list. Else `git branch orch/<this run> HEAD` (`<rb>`), `git worktree add <scratch>/orch-<this run> <rb>` (`<rw>`, merges); `<tb>` = `<rb>/<task-id>`.

### Heartbeat

`CronCreate(cron="13,43 * * * *", prompt="Heartbeat <this run>: worker out → reply in five words, no tools; no run in flight → CronDelete this job")`, session-only: a cheap read every 30 min, so a worker wait past 1h never re-sends the prompt; 24 deletes it.

## Phase 1 — Pre-flight

1. Sprint: `--sprint <id>` → `pm_get_sprint(id)`, else `pm_list_sprints(status="active", brief=True)`. None → stop (`/pm-plan`); several → ask (`--auto`: latest).
2. `pm_status`, then `pm_audit`: ERROR-level findings **stop** the run, even under `--auto`. Keep its `digest: <16 hex>` as the **last audit digest** (21).
3. **Classify in-progress claims from the data.** `pm_board(brief=True)` and `pm_active` give `claimed_by_run`, `claim_age`, `stale: true` (2 h, `stale_after=<hours>`), `stale_tasks`. By that:
   - another `orch-` run, stale or silent since its claim (`pm_activity(item_id=<task-id>, event_type="update")`) → `pm_grab(<task-id>, run_id=<this run>)` + `pm_update(<task-id>, outcome="info", note="recovered from run <old-run-id>")`; still emitting → live: skip under `--auto`.
   - a human, or any id without the `orch-` prefix — **never touch it**.
4. `git status --short` — the modified list, `.project/` after Phase 0. Over **200** entries: warn — step 23 and every dispatch walk it; commit or clean first. `--auto` continues; report in Phase 4.

## Phase 2 — Plan

5. Stories: `pm_batch_get(ids=<story ids>, fields="title,status,points,depends_on,acceptance_criteria,body")`.
6-10. Keep `{todo, in-progress, review, blocked}`, order by `depends_on`, flag out-of-sprint blockers; `--dry-run` stops, else confirm unless `--auto`.

## Phase 3 — Execution

11. `pm_accept` returned `next` → use it, skip to 13; else `pm_board`; for lane B `pm_board(lane_compatible_with=<A's task>)`, first `available` in plan order (the filter already bars a dependency in flight); none → B idles till A is accepted.
12. Else the first plan `todo`, dependency-clear, unassigned or step 3 recoverable: `pm_grab(<id>, run_id=<this run>)`; never one held elsewhere; none → exit.
13. `--max` exceeded (retries too; both lanes count) → stop, report, release any pre-claimed task in either lane: `pm_release(<id>, note="<why>", run_id=<this run>)`.
14. Note lane and `<tb>` before **each** dispatch; `--lanes 2`: one claim per lane, by run id — A and B, each with task, `<tb>`, returned?
15. `Agent`: `subagent_type: general-purpose`, `model:` `--executor-model` else `opus`, `isolation: "worktree"`, branch `orch/<this run>/<task-id>` off `<rb>`; prompt below, in the background (a notification marks it done). Two in flight: take the first notification to land through 16-19 while the other worker runs — one lane validated or merged at a time — then refill it (11/12, compatible with the task in flight) and wait.

16. **Status check**: `pm_get(task_id, fields="status,assignee")` — deliberate: `status` `in-progress`/`review`, `assignee` `claude`.
17. **Validation**: an `Agent` (`subagent_type: general-purpose`, step 15's model, foreground, no worktree) with the Validator Prompt Template returns files, tests, DoD — **never run them yourself**.
18. Missing or malformed verdict = one failure: re-run the validator once, then `pm_park(task_id, note="validator returned no verdict")`.
19. **Verdict** — its `verdict` picks the verb; the object minus `verdict`/`note` is `evidence`, its `note` the note: **ONE line, at most 200 characters** (`note_long: true` = over).
    - **Accept**: `pm_accept(task_id, note="<one line>", run_id=<this run>, evidence={"files":[...],"tests":[{"command":"...","passed":true}],"dod_met":[...]})` → `done`; `story_closed` on the last task; `next` claimed else `no_next_task`. Merge in `<rw>` before the next dispatch: `git merge --ff-only <tb>` else `--no-ff -m "<task-id>"`; on conflict `merge --abort` + `pm_retry` (paths in `evidence.files`, note "rebase onto `<rb>`"); a second conflict parks. Merge order is acceptance order, never dispatch order: B was cut before A's merge, so a conflict is expected; that retry keeps its lane and `<tb>`, and is not a new dispatch for `--max`.
    - **Retry** (first failure): `pm_retry(task_id, note="<why>", evidence={"tests":[<failing>]})` → `todo`; dispatch **one** retry worker.
    - **Park** (second failure/blocker): `pm_park(task_id, note="<why>", evidence={"tests":[<failing>],"dod_unmet":[...]})`; continue.
    - **Accept-as-review** (human needed): `pm_review(task_id, note="<why>", evidence={"dod_met":[...],"dod_unmet":[...]})`.
20. Only `pm_accept` closes a task, never a worker.
21. **Health check** every 3 accepted tasks, both lanes: `pm_audit(since=<last audit digest>)`: `unchanged: true` passes; else **stop** on new ERROR-level findings; `digest:` is the new last audit digest.

## Phase 4 — Report

22. **From the log**: `pm_activity(run_id=<this run>)`, page `offset` while `has_more: true`: **Accepted** (`→ done`), **Retried** (`→ todo`, `failed`), **Parked**/**accept-as-review** (`→ review`, `pm_run_log(<id>)`: `blocked`/`partial`), **Recovered claims** (`claimed_by_run` → `<this run>`), **Released** (`info`), **Stories closed**, **Points moved** (`pm_get(<ids>, fields="points")`), **Untouched**. Notes cross-check; on disagreement **the log wins**.
23. **Branches**: `<rb>`; `git branch --list 'orch/<this run>/*'` vs `git branch --merged <rb>`: **merged**, **unmerged** (parked/review), **abandoned** (released) — per 22's log. `git diff --stat HEAD...<rb>` (code); `git status --short -- .project/` (store).
24. `CronDelete` the heartbeat. All tasks `done` → `pm_update_sprint(sprint_id, status="completed", run_id=<this run>)`.

## Resume

`--resume` only. Mint a new id; never reuse the old. `pm_activity(run_id=<old-run-id>)`, page `offset` while `has_more: true`. Adopt only tasks still `in-progress` and `claimed_by_run: <old-run-id>`: `pm_grab(<task-id>, run_id=<this run>)` + `pm_update(..., outcome="info", note="recovered from run <old-run-id>", run_id=<this run>)`; leave the rest. Adopted tasks go out as **retries** (`<on resume: ...>`). **Never adopt** a claim without the `orch-` prefix, or from a live run.

## Worker Prompt Template

```
You are executing a single ProjectMan task; pm_grab(<task-id>,
run_id=<this run>) returns its context.

Task: <task-id>; Run id: <this run>
Criteria: <criteria>; DoD: <dod items>
<on retry: "last attempt failed: <failures>; fix on the same branch; after a
merge conflict `git rebase orch/<this run>` first">
<on resume: "run <old-run-id> died mid-task; validate the working tree first">

First `git switch -c orch/<this run>/<task-id> orch/<this run>` (retry: plain
`git switch`), then /pm-do with `<task-id>` — without --complete.

Rules:
- Never run git checkout, git restore, git stash, or git reset.
- Never call pm_create_* or any Store write outside a tmp_path-isolated fixture.
- Edit tracked files directly with the Edit tool; do not stage code through scratchpad files.
- Mutation tests: they must end byte-identical — the branch diff shows it.
- Git plumbing must never run the new command against the real repo.
- Finish: `git add -A -- <code paths>` (code only, never .project), one commit titled `<task-id>`, worktree left in place. No git push, pm_commit, pm_push.
- Do NOT mark the task done, run pm_done_next or pass --complete; pm_accept
  closes it (a worker-set done answers already_done). Blockers:
  pm_update(note=...).

Report back under 1500 chars, no code or logs: files changed
(paths only); tests as `command -> pass|fail (n passed)`; DoD met; DoD unmet;
blockers; branch, sha and worktree path.
```

## Validator Prompt Template

```
Validate task <task-id>, run <this run>; change nothing.
DoD: <dod items>. Criteria: <criteria>.
Branches <run branch>/<task branch>, worktree <path>, sha <sha>. Worker
report: <report>.
Run `git diff --stat <run branch>...<task branch>` and `git diff --name-only`;
forbidden files come from that list. Run the DoD tests in the worktree
(`cd <path>`).
Other lane in flight: <other task> — its files are out of scope; a diff touching
them is a retry, not a park.
Worker rules: no checkout/restore/stash/reset, one commit, no Store write.
One JSON object <1500 chars, no prose:
{"verdict":"accept|retry|park|review","files":[...],"tests":[{"command":"",
"passed":true}],"dod_met":[...],"dod_unmet":[...],
"note":"one line, <=200 chars"}
```

## Stop Conditions

Stop when all sprint tasks are `done` or parked, `--max` is reached, `pm_audit` finds a new ERROR-level finding (`unchanged: true` never is), or `--resume` named a live run. Run Phase 4 first, releasing any pre-claimed unstarted task in either lane: `pm_release(<id>, note="<why>", run_id=<this run>)`. Merged: `git worktree remove <path>`, `git branch -d <tb>`; parked/review keep both; remove `<rw>` last, after 23's list. Print `git merge --no-ff <rb>`.

## What This Skill Does NOT Do

- **No scoping or planning** (→ `/pm-plan`), **no claim it does not own**, **no implementing**.
