# The pm-orchestrate Design Rationale

**Task:** US-PM-25-5 · **Story:** US-PM-25 — pm-orchestrate skill is under 9KB of instruction
with its rationale in a reference doc
**Date:** 2026-09-05 · **Version:** v0.8.9 (this checkout)
**Status:** REFERENCE — the companion to `src/projectman/templates/skill_pm_orchestrate.md.j2`.

This document is the *why*. The skill template is the *what*: an orchestrating agent reads
the skill to know what to do, and reads this only when it wants to know what a rule is
protecting or what happens if it is dropped. Nothing here is an instruction; nothing in the
skill needs to repeat an argument made here.

Where a rule is already fixed by a contract document, this file links rather than restates:

- [`claim-release-contract.md`](claim-release-contract.md) — claiming as compare-and-swap,
  expected negatives, and why nothing-valued intents get a verb rather than an absence.
- [`verdict-verbs-contract.md`](verdict-verbs-contract.md) — the four verdict verbs, what
  each fixes (status, outcome, assignee), and why `note` is required on all four.
- [`evidence-contract.md`](evidence-contract.md) — the `evidence` object, its caps, and the
  rule that the note says what happened while the evidence says what proves it.
- [`skills.md#pm-orchestrate`](skills.md#pm-orchestrate) — the user-facing summary of the
  same machine.
- [`file-formats.md#claim-ownership--claimed_at--claimed_by_run`](file-formats.md#claim-ownership--claimed_at--claimed_by_run)
  — where `claimed_at` and `claimed_by_run` live on disk.

---

## Stage-only model

Three constraints hold the loop together, and each is a correctness requirement rather than
a preference.

**Sequential, one worker at a time.** Parallel workers would need atomic task claiming
across processes. The store has compare-and-swap claiming (see the claim/release contract),
but the orchestrator's loop also mutates the working tree, and two workers editing one
unbranched checkout cannot be separated afterwards. Until worker isolation exists, adding
concurrency trades a whole class of recoverable failures for an unrecoverable one.

**Stage-only: no commits, no pushes, no branches, no worktrees.** Neither the orchestrator
nor a worker runs `git commit`, `git push`, `pm_commit`, or `pm_push`. The run's product is
a working tree the user reads and commits. This is what makes a bad run cheap: a rejected
sprint is a `git diff` the user declines, not a history to unwind. It is also why workers
must never run `git checkout`, `restore`, `stash`, `reset` or `clean` — see *Known failure
modes*. No worktree isolation follows from the same choice: sequential plus stage-only
means there is exactly one tree, and the pre-task `git status --short` snapshot is what
separates this worker's edits from the ones already there.

**Failures park, they do not halt.** A task failing validation twice is left in `review`
with a run-log record and the loop moves to the next ready task. A run that stops on the
first bad task converts one broken task into an idle sprint; a run that parks converts it
into one line of the final report. Only systemic problems stop the loop — see the skill's
Stop Conditions.

**Every attempt is logged, structurally.** The verdict verbs append a run-log entry as part
of the same call that sets the status, and none of them can be called without a note, so a
verdict cannot land without a record. Evidence rides along as structured fields rather than
prose so it stays queryable: `pm_run_log(id, has_evidence=true)` returns only attempts that
proved something, and `pm_audit` raises `done-without-evidence` as a **warning** when a task
is done with nothing on its log. Failures stay visible to sessions that were not there.

## Run identity

One opaque id per run, `orch-<YYYY-MM-DD>-<4 random hex>`, minted before pre-flight and
spent on every call that takes or clears a claim.

**The `orch-` prefix is load-bearing.** Pre-flight's claim classification reads it to tell
an orchestrator's claim from a human's, and no other signal in the store distinguishes them.
A run id without the prefix is, by definition, not the orchestrator's to touch.

**The random tail must differ run to run**, so a restart never collides with the run it is
recovering from. Two runs sharing an id merge into one `pm_activity(run_id=)` slice, and the
final report then cannot say which process did what.

**Why every call carries it.** The store records the id on the task as `claimed_by_run` and
stamps it on the activity-log event. Those two facts together are what make a crashed run's
claims recoverable *from the data* instead of by argument. A claim with no run id has an
owner (the server's own per-process id fills in) but no lineage.

**Why the report is built from it.** `pm_activity(run_id=<this run>)` returns everything the
run produced — claims, releases, verdicts, the story closures `pm_accept` triggered, and any
hand-tagged `pm_update` / `pm_update_many` / `pm_update_sprint`. That is why writes which
are not claims (the pre-flight recovery note, the sprint close) must be tagged with the same
`run_id=`: an untagged write is invisible to the query the report is made of.

**Why a resuming run still mints a fresh id.** Reuse would merge the dead run's slice with
the live one. The link is kept as *lineage* — a `recovered from run <old-id>` note on each
adopted claim — which preserves both slices and still connects them.

## Pre-flight and claim classification

**The sprint read is deliberately unprojected.** `pm_list_sprints(status="active")` returns
one or two sprints, and `brief=True` would drop the goal the pre-flight summary wants. This
is the one read where projection saves nothing worth having.

**Classify claims from the data, never from a guess.** Every in-progress task carries
`claimed_by_run`, `claim_age`, and `stale: true` once the age passes `stale_claim_hours`
(default 2, overridable per call). Those three fields decide every case that an earlier
version of the skill referred to a human, which is why the current step has no warning and
no confirmation prompt. The one question still worth asking is a genuinely ambiguous *human*
claim — an unattributable non-`orch-` id on a task the plan needs — and even that is skipped
under `--auto`.

The branches and their reasons:

- **A stale or dead `orch-` run** — reclaim. A cross-run re-claim under the same `claude`
  assignee is allowed by the claim contract and resets `claimed_at`. "Dead" is not a guess
  either: no activity entry carries that run id after its last claim on the task.
- **A live `orch-` run** — leave it. Taking a claim from a process still emitting events
  races it, and the loser of that race is a half-finished working tree.
- **A human, or any non-`orch-` id** — never touch it, however old. Age is evidence about
  processes, not about people.

**Why the recovery is written down.** `pm_update(..., outcome="info", note="recovered from
run <old>")` exists so the next reader sees the takeover, and so the final report finds it
in this run's own slice rather than having to remember it.

**Why the tree is snapshotted before anything runs.** `git status --short` at pre-flight is
the baseline that lets the final report separate orchestrator-caused changes from the local
edits that were already there. Without it, a dirty starting tree is indistinguishable from
worker output. Sprint 7 extended this to a `tar` + md5 snapshot before *each* dispatch — see
*Known failure modes*.

**Why project context is fetched once, bounded.** `pm_context(max_doc_chars=2000, limit=5)`
is called once per run and the same excerpt is pasted into every worker prompt, retries
included. The bounds are the whole point: five docs at 2,000 chars each holds the return
near 10k. An unbounded `pm_context` returned **48,588 characters** in one study — a cost
that would otherwise be paid once per worker, per retry, for context each worker mostly does
not read. The active epic and story lists are dropped because `pm_grab` already hands each
worker its own story context.

## Dispatch and the worker prompt

**Why the plan read is unprojected.** The plan is built out of task bodies and their DoD
checklists, so this is one of the few calls that genuinely needs the full item.

**Why a worker prompt is self-contained.** A worker has no prior context and no memory of
the run. Every fact it needs — task, story, acceptance criteria, DoD, the bounded project
context excerpt, the run id — is inlined, because a worker that has to rediscover its
context spends its budget on discovery and produces less implementation.

**Why the run id is pasted into the prompt.** The worker's own `pm_grab` then claims under
the same run id rather than an anonymous per-process id, so the claim is attributable and
recoverable if the run dies mid-task.

**Why the worker reports three lists, not prose.** The orchestrator transcribes them
straight into structured `evidence` (files, tests, DoD met/unmet). Prose has to be re-parsed
and loses exactly the structure the evidence contract asks for.

**Why the worker is told its report will be independently verified.** A worker's self-report
is a claim, not a result. The stated verification is what makes "I ran the tests" cheaper to
prove than to assert.

**Why the orchestrator never implements, even a trivial task.** Its context is the
validation instrument. An orchestrator that has written the code cannot review it with fresh
eyes, and the context it spends implementing is context it no longer has for the sprint.

## Validation and verdicts

The governing rule: *the orchestrator's own judgment, never the worker's word.*

**The status read is deliberate and must never be removed.** `pm_get(task_id,
fields="status,assignee")` is trust-but-verify, and projection makes it nearly free — tens
of characters rather than thousands — so there is no efficiency argument for dropping it.
`assignee` is read alongside `status` because an unexpected assignee means something else
touched the task while the worker ran.

**Why the diff is read, not counted.** A `done` task with an empty diff is a failure unless
the task is genuinely non-code. File counts do not answer "do the changed files plausibly
match the task scope?" — only reading them does.

**Why tests are run by the orchestrator.** "Tests pass" from the party being validated is
the claim under test. Re-running is the only check that does not depend on the worker's
honesty or its definition of passing.

**Why the three lists are collected while validating.** Files changed, test commands with
results, and DoD criteria met versus unmet are gathered during steps 17–18 so the verdict is
a transcription rather than a recollection. Recollection is where evidence quietly stops
matching what happened.

**Why a verb per verdict.** Status and outcome are fixed by the verb itself, so there is no
way to record a park with a success outcome or reach `done` without `success`; the required
note means a terminal move cannot land silently. The full argument, including the measured
failure it replaced, is in [`verdict-verbs-contract.md`](verdict-verbs-contract.md).

**Why the note is one line and the lists go in `evidence`.** Prose is not the container for
a list — the argument, the caps, and the clamping behaviour are in
[`evidence-contract.md`](evidence-contract.md). A response carrying `note_long: true` is the
signal that detail was written into the wrong field.

**Why `pm_accept` returns `next`, and why `same_story_only` defaults true.** Complete-plus-
next is the orchestrator's actual unit of work; splitting it re-creates the grab-then-update
pair the usage data showed losing. Keeping the next pick inside the same story keeps it
inside the sprint — there is no sprint filter, but sibling tasks are always in-sprint. An
exhausted story returns the expected negative `no_next_task` with `next: null`; the
completion still landed, and the loop falls back to the plan.

**Why retry carries the failing test entries forward.** The next attempt inherits the exact
commands that failed, so a retry worker starts from evidence instead of from a summary.

**Why a park continues the loop.** See *Stage-only model*: parking is what keeps one bad
task from costing the sprint.

## Health checks

Re-running `pm_audit` every 3 accepted tasks is a poll, and the poll is the point: it is
what catches drift introduced mid-run, when the sprint state is changing fastest.

The usage studies flagged those repeated `pm_audit` calls as waste because they were
byte-identical repeats within a session. They are not waste — they are this check working as
designed, and caching `pm_audit` per session would disable it silently. `since=<last audit
digest>` is the correct fix: it keeps the poll and removes the cost. An `unchanged: true`
answer means nothing the audit reads has changed, so the findings are necessarily the ones
already cleared — the check passes without a report being generated at all. A stale or
unknown `since` is never an error; it simply misses and returns the full audit.

ERROR-level findings stop the run even under `--auto` because dependency cycles and
done-stories-with-incomplete-tasks are states no worker can be dispatched out of.

## Resume protocol

A run that dies mid-loop leaves claims behind with no record of intent. `--resume
<old-run-id>` is how the next run picks them up as **one deliberate decision over one run's
whole record**, instead of leaving per-claim classification to infer them a task at a time.
Without the flag none of this applies: classification runs as written and a stale `orch-`
claim is recovered case by case. The building blocks are the same either way — the minted
run id, `claimed_by_run` / `claim_age` / `stale`, and the activity log.

**R1 — new id, old id as lineage.** Covered under *Run identity*: reuse would merge two
processes into one activity slice and leave the report unable to attribute anything. The
lineage note keeps the slices per-process and still links them.

**R2 — read the dead run's record before touching anything.** `pm_activity(run_id=<old>)`,
paged on `has_more`, is everything that run did. Each task it names is then sorted by its
*current* state, and each branch has a reason:

- **Still in-progress under the old id** → adopt. The claim is orphaned; nobody else is
  coming for it.
- **Already done** → leave it. The verdict landed. It belongs to the dead run's record, not
  to this run's accepted list.
- **Released, parked, or back in todo** → leave it and report it. Each of those was a
  decision the dead run made on purpose. A parked task is waiting on a human and a released
  one is back in the pool where the ordinary pick will find it; adopting either overrules a
  decision that was already taken.
- **Claimed under a different id** → another run already recovered it. Two recoveries of one
  claim is the race the whole scheme exists to prevent.

**R3 — an adopted task is dispatched as a retry, never as fresh work.** Its worker may have
died with half-written files in the tree, and the store records nothing about how far it
got. So the tree is snapshotted first, and the prompt carries the `<on resume: ...>` line
telling the worker to validate the working-tree state before editing. A failure on an
adopted task is a *first* failure — retry once, then park — because the dead run's attempt
was never validated and so was never a failure on the record.

**R4 — `--resume` narrows nothing.** Claims belonging to other runs remain ordinary
classification's business. The flag buys certainty about *one* run's claims; it does not
suppress the rest.

**R5 — the report says what was adopted and from whom.** No extra bookkeeping is needed: the
adopted claims are exactly the `claimed_by_run: <old> → <this run>` entries in this run's own
slice, each carrying its lineage note.

**When not to resume.** `--resume` is an instruction to adopt claims, so it is wrong
whenever the claim is not the orchestrator's to take:

- **A human holds it** — never adopted, flag or no flag. If that is the only claim the old
  run left, there is nothing to resume.
- **The old run's last event is a verdict on a task now done** — the run finished before it
  died; the "claim" would be a completed one.
- **The old run is still emitting events** — it is slow, not dead, and adopting races a live
  process. Under `--auto` this is a skip rather than a stop, because racing is the harm and
  stopping is not the only way to avoid it.
- **The id matched no events** — a typo or another project's id. Falling back to ordinary
  classification is better than guessing which claims were meant.

## Final report from the activity log

**The log is the record; the orchestrator's memory is only the cross-check.** A loop that
ran for hours produces a report from `pm_activity(run_id=<this run>)`, paged on `has_more`,
because one filtered query holds every claim, release, verdict, story closure and tagged
edit the run produced. Deriving the report from memory instead reproduces whatever the
orchestrator believes happened, including verdicts it believes it passed and did not.

**Where the two disagree, the log wins — and the disagreement is named outright.** A
mismatch is evidence of a write that never landed. Silently preferring either side hides
exactly the failure the report exists to surface.

**Why some sections need a second read.** Park and accept-as-review both land on `status: …
→ review`, so the activity entry alone cannot separate them; the run-log outcome does
(`blocked` is parked, `partial` is accept-as-review). Likewise `pm_retry` and `pm_release`
write an identical `→ todo` entry, and only the newest run-log outcome (`failed` versus
`info`, or no entry at all) tells them apart.

**Why points are re-read rather than summed from memory.** One projected `pm_get` over the
accepted ids is cheap and correct; a remembered total is neither.

**Why `git diff --stat` stays in the report.** The activity log records what changed in the
project store and never what changed in the repository. The log answers "which tasks moved";
the diff answers "which files moved". A report with only one of those is half a report.

## Known failure modes

Each rule in the worker prompt was bought with an incident. They are recorded here so the
rule is not read as ceremony.

**2026-08-21 (Sprint 5, US-PM-12-2) — `git checkout` erased three tasks' work.** A worker
ran `git checkout src/projectman/server.py` to undo a mutation it had made for a test. The
file also held three earlier tasks' uncommitted implementation, which the checkout discarded.
Recovery meant replaying the edits out of session transcripts.
→ **Rule: a worker never runs `git checkout`, `git restore`, `git stash`, `git reset`, or
`git clean`.** Undo a temporary edit with the same edit tool that made it. The stage-only
model means the working tree is the only copy of every earlier task's work.

**2026-08-22 (Sprint 6) — a throwaway diagnostic wrote to the real store.** A worker's
scratch script called `pm_create_story` outside a `tmp_path` fixture and left a stray story
in the repository's real `.project/`.
→ **Rule: never call `pm_create_*`, or any Store write, outside a `tmp_path`-isolated
fixture.** The repository under test is also the repository being managed; a test that is
not isolated is a production write.

**2026-08-22 (Sprint 6) — scratchpad staging pulled in a stale copy.** A worker wrote test
code into a scratchpad file and copied it into `tests/test_server.py`, and a later copy of
the same scratchpad overwrote newer content.
→ **Rule: edit tracked files directly with the Edit tool.** Do not stage code through
scratchpad files; a second source of truth for a tracked file is a stale copy waiting to
happen.

**2026-09-01 (Sprint 7) — the md5 check that caught nothing.** Mutation-testing workers were
told the source files they mutate must end byte-identical, and the orchestrator verified
md5s after each dispatch. It caught nothing, because every worker complied. The check was
still not the safeguard: a `tar` + md5 snapshot taken *before* each dispatch was, because it
turns recovery from a transcript replay into a `tar x`.
→ **Rules: a task that mutation-tests source files must leave them byte-identical, the
orchestrator verifies md5s, and it snapshots the tree before each dispatch.** Verification
tells you something broke; the snapshot is what fixes it. A related rule from the same
sprint: a task touching git plumbing must not run the new command against the real repo.

**2026-09-05 — a worker's self-set `done` swallowed the evidence.** When a worker sets its
own task to `done`, the orchestrator's `pm_accept` short-circuits on the expected negative
`already_done` and **writes nothing** — no run-log entry, no evidence, no story close, no
`next`. The completion looks fine and the record is empty, which is exactly the state
`pm_audit`'s `done-without-evidence` warning is meant to catch after the fact.
→ **Rule: a worker leaves its task `in-progress` and lets `pm_accept` close it.** A worker
that cannot finish sets `review` with a note; `done` is the orchestrator's word, not the
worker's. (Note that the current worker prompt still instructs the worker to set `done`
itself — reconciling that is `US-PM-25-7`.)

## Sizes and numbers

The figures the skill's instructions depend on, with their sources.

| Number | What it is | Why it is that number |
|---|---|---|
| **48,588 chars** | An unbounded `pm_context` return, measured in one study | The reason project context is fetched once per run at `max_doc_chars=2000, limit=5`, which holds the return near 10k |
| **2,000 / 5** | `max_doc_chars` / `limit` for the pre-flight `pm_context` | Five docs × 2,000 chars ≈ 10k, small enough to paste into every worker prompt |
| **200 chars** | The skill's note-length guidance for a verdict | A human one-line summary; the lists belong in `evidence`. Distinct from the store's hard cap |
| **4,096 chars** | `store.RUN_LOG_NOTE_LIMIT` | The server-side truncation point — notes are clamped, never rejected, so a verdict never fails on note length |
| **16 hex** | The `digest:` line in an audit report | The token passed back as `pm_audit(since=…)`; a match short-circuits to `unchanged: true` and no checks run |
| **every 3 accepted tasks** | Health-check cadence | Frequent enough to catch mid-run drift, cheap because `since=` makes an unchanged answer a few bytes |
| **2 hours** | `stale_claim_hours` default (`pm_active(stale_after=…)` overrides per call) | The point past which an `orch-` claim is treated as recoverable rather than live |
| **limit=100 + `has_more`** | Activity-log paging in resume and the final report | The report must hold *every* event in the run's slice; a single unpaged page is a silently truncated report |
| **40 / 10 / 20 / 160** | `evidence` caps: files, tests, dod items, chars per string | Set and justified in [`evidence-contract.md`](evidence-contract.md); clamped rather than rejected |
| **512 vs 387** | grab-then-update pairs versus `pm_done_next` calls in the usage data | The measurement behind `pm_accept` absorbing complete-plus-next; see [`verdict-verbs-contract.md`](verdict-verbs-contract.md) |
| **31,731 → under 9,000 bytes** | The skill template before and after `US-PM-25` | Roughly 14k of the original is the rationale this document now holds; the rest is tightening |

Numbers that appear in more than one place must agree across the skill templates and the
code — task point range, the audit check count, the skill count, and which call closes a
story. Reconciling the ones that currently disagree is `US-PM-25-8`; this table is not the
arbiter of those four.

## Template sections absorbed

The map from `src/projectman/templates/skill_pm_orchestrate.md.j2` (31,731 bytes, 225 lines,
as of this task) to the sections above. Line ranges are of the template *before* `US-PM-25-6`
rewrites it. "Rationale bytes" is the share of the section that is explanation rather than
instruction, measured by classifying each paragraph.

| Template section | Lines | Bytes | Rationale bytes (approx) | Absorbed by |
|---|---|---|---|---|
| Title + preamble | 8–11 | 326 | ~0 | — (instruction; stays) |
| `## Flags` | 12–21 | 1,053 | ~230 | *Run identity* (advisory-model note, lineage note on `--resume`) |
| `## Operating Model` | 22–28 | 1,215 | ~900 | *Stage-only model* (all four bullets' reasoning, incl. the run-log/evidence paragraph) |
| `## Phase 0 — Model Selection and Run Identity` | 29–47 | 1,841 | ~500 | *Run identity* (big-model/cheap-model split, coarse-tier mapping, advisory-orchestrator argument) |
| `### Run id — mint it here, spend it everywhere` | 48–57 | 1,645 | ~950 | *Run identity* (prefix is load-bearing, random tail, why every call carries it, why the report is built from it, fresh id on resume) |
| `## Phase 1 — Pre-flight` | 58–71 | 4,020 | ~1,620 | *Pre-flight and claim classification* (unprojected sprint read, the three claim branches and their reasons, the no-prompt argument, the tree snapshot, the 48,588-char `pm_context` study) |
| `## Phase 2 — Build the Execution Plan` | 72–80 | 785 | ~210 | *Dispatch and the worker prompt* (why the plan read is unprojected; out-of-sprint blockers) |
| `## Phase 3 — Execution Loop` | 81–90 | 1,471 | ~380 | *Dispatch and the worker prompt* (pre-claimed `next`, idempotent re-claim, foreground + no-worktree reasoning) |
| `### Validation — your own judgment, not the worker's word` | 91–119 | 5,702 | ~2,100 | *Validation and verdicts* + *Health checks*; verb semantics link to `verdict-verbs-contract.md`, evidence shape to `evidence-contract.md` |
| `## Phase 4 — Final Report` | 120–137 | 3,812 | ~1,400 | *Final report from the activity log* (log-over-memory, why park/review and retry/release need a second read, why points are re-read, why the diff stays) |
| `## Resume — Picking Up an Interrupted Run` | 138–161 | 5,337 | ~4,300 | *Resume protocol* (R1–R5 in full, plus "when not to resume") |
| `## Worker Prompt Template` | 162–206 | 2,233 | ~350 | *Dispatch and the worker prompt* (self-containment, pasted run id, three-lists-not-prose, independent verification) |
| `## Stop Conditions` | 207–216 | 847 | ~190 | *Health checks* (why `unchanged: true` is never a stop) and *Resume protocol* (live-run race) |
| `## What This Skill Does NOT Do` | 217–224 | 714 | ~250 | *Stage-only model* (sequential, no commits) and *Validation and verdicts* (never implement) |
| **Total** | 8–225 | **31,731** | **~13,400** | |

Rationale with no home in the template — the Sprint 5/6/7 and 2026-09-05 incidents that
produced the worker safety rules — is recorded here under *Known failure modes*; the rules
themselves belong in the worker prompt (`US-PM-25-7`).
