---
name: pm-orchestrate
description: Drive the active sprint to done — dispatch worker subagents and independently validate their work. Use for "run the sprint" or "orchestrate".
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--orchestrator-model <m>] [--executor-model <m>] [--resume <run-id>] [--dry-run] [--auto]"
---

# /pm-orchestrate — Sprint Orchestrator

Orchestrator, not worker: dispatch each task to a worker subagent, then **independently validate** it. Rationale: `docs/reference/orchestrate-design.md`.

## Flags

- `--sprint <id>` — the sprint
- `--max <n>` — stop after `n` dispatches, retries too
- `--orchestrator-model <m>` — advisory; default Fable 5
- `--executor-model <m>` — `model` per `Agent` spawn; default `model="opus"`
- `--resume <run-id>` — adopt a dead run's claims
- `--dry-run` — plan only
- `--auto` — no confirmation; audit errors stop

## Operating Model

**Sequential**, one worker at a time. **Stage-only**: no `git commit`, `git push`, `pm_commit`, `pm_push`. **Park, don't halt** — a twice-failed task is parked and the loop continues. **Every verdict is logged** — the verbs need a note and append a run-log entry (`pm_run_log(id, has_evidence=true)`).

## Phase 0 — Models and Run Id

Executor: `--executor-model` else `opus`. Orchestrator: `--orchestrator-model` else Fable 5.

### Run id

Mint `orch-<YYYY-MM-DD>-<4 random hex>` first; the `orch-` prefix is load-bearing. Pass `run_id=<this run>` on `pm_grab`, `pm_release`, `pm_accept`, `pm_retry`, `pm_park`, `pm_review` and your `pm_update`/`pm_update_many`/`pm_update_sprint` writes, and into every worker prompt: `pm_activity(run_id=<this run>)` is the report's record.

## Phase 1 — Pre-flight

1. Sprint: `--sprint <id>` → `pm_get_sprint(id)`; else `pm_list_sprints(status="active")`, unprojected (`brief=` drops the goal). None → stop (`/pm-plan`). Several → ask; `--auto` takes the latest.
2. `pm_status`, then `pm_audit`: ERROR-level findings **stop** the run, even under `--auto`. Keep its `digest: <16 hex>` as the **last audit digest** (step 21).
3. **Classify every in-progress claim from the data, never a guess.** `pm_board` and `pm_active` give `claimed_by_run`, `claim_age`, `stale: true` (`stale_claim_hours`, default 2; `pm_active(stale_after=<hours>)` overrides), `stale_tasks`. By `claimed_by_run`:
   - another `orch-` run, stale or silent since its claim (`pm_activity(item_id=<task-id>, event_type="update")`) → `pm_grab(<task-id>, run_id=<this run>)` + `pm_update(<task-id>, outcome="info", note="recovered from run <old-run-id>", run_id=<this run>)`; still emitting → live: list and skip under `--auto`.
   - a human, or any id without the `orch-` prefix — **never touch it**.
4. `git status --short` — keep the pre-existing modified list.
4b. `pm_context(max_doc_chars=2000, limit=5)` **once per run**; reused in every worker prompt.

## Phase 2 — Plan

5. `pm_get(story_id)` per sprint story, unprojected: the plan needs bodies and DoD. Capture `id`, `status`, `assignee`, `depends_on`, `points`, DoD.
6-10. Keep `{todo, in-progress, review, blocked}`, skip `done`, order by `depends_on`, flag out-of-sprint blockers, present it; `--dry-run` stops here, else confirm unless `--auto`.

## Phase 3 — Execution

11. `pm_accept` returned `next` → use it (already claimed), skip to 13; else refresh with `pm_board`.
12. Else the first plan entry that is `todo`, dependency-clear, unassigned, or step 3 recoverable: `pm_grab(<id>, run_id=<this run>)`. Never one left with someone else; none → exit.
13. `--max` exceeded → stop and report, releasing a pre-claimed unstarted task: `pm_release(<id>, note="<why>", run_id=<this run>)`.
14. Before **each** dispatch: `git status --short`, then `tar` the modified and untracked files, recording md5s.
15. `Agent`: `subagent_type: general-purpose`, `model:` the Phase 0 tier, foreground, no worktree; prompt below.

### Validation

16. **Status check**: `pm_get(task_id, fields="status,assignee")` — deliberate (trust-but-verify): `status` `in-progress`/`review`, `assignee` `claude`.
17. **Diff check**: `git status --short`, `git diff --stat` vs the step 14 snapshot, plus md5s of files it should not have touched. An empty diff fails unless the task is non-code; keep the file list.
18. **DoD check**: evidence per criterion, and run the tests it names **yourself**. Keep two more lists: test commands with pass/fail and a summary, DoD met and unmet.
19. **Verdict** — one verb each; **the note is ONE line, at most 200 characters**; lists go in `evidence` (`files`, `tests` with `command`/`passed`/`summary`, `dod_met`, `dod_unmet`), never the note (`note_long: true` = over-written).
    - **Accept**: `pm_accept(task_id, note="all DoD met; 47 pass", run_id=<this run>, evidence={"files": [...], "tests": [{"command": "pytest -q", "passed": true}], "dod_met": [...]})` → `done`, `story_closed` on the story's last task, `next` claimed, else `no_next_task`.
    - **Retry** (first failure): `pm_retry(task_id, note="<what was wrong>", evidence={"tests": [<failing>]})` → `todo`; dispatch **one** retry worker naming the failures.
    - **Park** (second failure or blocker): `pm_park(task_id, note="<why>", evidence={"tests": [<failing>], "dod_unmet": [...]})`; continue.
    - **Accept-as-review** (needs a human): `pm_review(task_id, note="<needs review>", evidence={"dod_met": [...], "dod_unmet": [...]})`.
20. Only `pm_accept` closes a task, never a worker.
21. **Health check** every 3 accepted tasks: `pm_audit(since=<last audit digest>)`: `unchanged: true` passes; else **stop** on new ERROR-level findings, or record its `digest:` as the new last audit digest.

## Phase 4 — Report

22. **From the log, not memory**: `pm_activity(run_id=<this run>, limit=100)`, paging `offset` while `has_more: true`: **Accepted** (`→ done`), **Retried** (`→ todo`, outcome `failed`), **Parked**/**accept-as-review** (`→ review`, `pm_run_log(<id>)` outcome `blocked`/`partial`), **Recovered claims** (`claimed_by_run` → `<this run>`), **Released** (outcome `info`), **Stories closed**, **Points moved** (`pm_get(<accepted ids>, fields="points")`), **Untouched**. Notes cross-check; if they disagree, **the log wins**.
23. `git diff --stat` vs the step 4 snapshot: code versus `.project/`.
24. All tasks `done` → `pm_update_sprint(sprint_id, status="completed", run_id=<this run>)`.

## Resume

`--resume` only. Mint a new id; never reuse the old. Read the dead run: `pm_activity(run_id=<old-run-id>, limit=100)`, paging `offset` while `has_more: true`. Adopt only tasks still `in-progress` and still `claimed_by_run: <old-run-id>`: `pm_grab(<task-id>, run_id=<this run>)` plus the lineage note `pm_update(<task-id>, outcome="info", note="recovered from run <old-run-id>", run_id=<this run>)`; leave the rest. Adopted tasks go out as **retries**, `<on resume: ...>` in the prompt. **Never adopt** a claim without the `orch-` prefix, or from a live run.

## Worker Prompt Template

```
You are executing a single ProjectMan task, already claimed for you;
pm_grab(<task-id>, run_id=<this run>) returns its context.

Task: <task-id> — <task-title>  Story: <story-id> — <story-title>
Run id: <this run>  Acceptance criteria: <criteria>  DoD: <dod items>
Project context: <architecture excerpt; widen: pm_context(max_doc_chars=2000)>
<on retry: "last attempt failed validation: <failures>; fix them">
<on resume: "run <old-run-id> died mid-task; validate the working tree first">

Run /pm-do with `<task-id>` — without --complete.

Rules:
- Never run git checkout, git restore, git stash, or git reset — earlier tasks' uncommitted work lives in the working tree. To undo a temporary edit, reverse it with the same edit tool.
- Never call pm_create_* or any Store write outside a tmp_path-isolated fixture.
- Edit tracked files directly with the Edit tool; do not stage code through scratchpad files.
- If you mutation-test source files they must end byte-identical — the orchestrator checks md5s.
- Tasks that touch git plumbing must never run the new command against the real repo.
- No git commit/push, pm_commit/pm_push.
- Do NOT mark the task done, run pm_done_next, or pass --complete — leave it
  in-progress; pm_accept records the verdict and closes task and story, and a
  worker-set done answers already_done. Raise blockers with pm_update(note=...).

Report back: files changed; test commands with pass/fail; DoD met and unmet.
```

## Stop Conditions

Stop when all sprint tasks are `done` or parked, `--max` is reached, nothing is ready, `pm_audit` finds a new ERROR-level finding mid-run (`unchanged: true` never is), or `--resume` named a live run. Run Phase 4 first, releasing any pre-claimed unstarted task: `pm_release(<id>, note="<why>", run_id=<this run>)`.

## What This Skill Does NOT Do

- **No parallel workers, worktrees, commits, pushes** — sequential, stage-only.
- **No scoping or planning** (→ `/pm-plan`), **no adopting a claim it does not own**, **no implementing** — always delegate.
