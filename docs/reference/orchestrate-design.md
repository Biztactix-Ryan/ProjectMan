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

## Isolation model

Four constraints hold the loop together, and each is a correctness requirement rather than
a preference. The first two were revised on 2026-09-09 by
[ADR-005](../../.project/DECISIONS.md), which replaced the original *stage-only* choice —
one shared checkout with neither branches nor worktree isolation — with a worktree and a
branch per task. That ADR is the record of the trade and its consequences; what follows is
the short form.

**One worker at a time, or two.** Parallel workers would need atomic task claiming
across processes. The store has compare-and-swap claiming (see the claim/release contract),
and ADR-005 removed the other half of the obstacle — two workers no longer edit one
unbranched checkout. What was left was ordering: a dependent task has to start from a run
branch that already carries its dependency's merge, so lanes were a design problem about the
merge point rather than a flag to flip. `US-PM-53` answered it, and the answer is the next
section: at most two lanes, one claim each, merged in acceptance order. One lane is still the
default.

**A worktree and a branch per task: commits, but no pushes.** Each dispatch runs in its own
git worktree on `orch/<run-id>/<task-id>`, cut from the run branch `orch/<run-id>`, which is
itself cut from `HEAD` at pre-flight. The worker commits its code there — code only, never
`.project` — and the orchestrator merges that branch onto the run branch when, and only
when, it accepts the task. Nothing is pushed and the store is never committed by a run: no
`git push`, no `pm_push`, no `pm_commit`. The run's product is a run branch the user reads
and merges. This is what keeps a bad run cheap: a rejected sprint is a branch the user
deletes, not a history to unwind and not a pushed remote to revert. It also makes two tasks'
edits physically separable — the branch diff *is* the boundary, where the shared-tree model
had a pre-task `git status --short` snapshot and an md5 list standing in for one. Isolation
does not relax the worker safety rules: inside a worktree as outside it, a worker never runs
`git checkout`, `restore`, `stash`, `reset` or `clean` — see *Known failure modes*. And
because `.project` is gitignored on the code branch, a fresh worktree simply does not have
it: every store read and write goes through the MCP tools against the primary checkout.
Cleanup is part of the model rather than housekeeping: once the final report has listed the
run's branches — merged, unmerged and abandoned — the run removes the worktree and branch of
every merged task, leaves a parked or review task's pair standing for whoever reads it, and
removes the run worktree last.

**Failures park, they do not halt.** A task failing validation twice is left in `review`
with a run-log record and the loop moves to the next ready task. A run that stops on the
first bad task converts one broken task into an idle sprint; a run that parks converts it
into one line of the final report. A parked task keeps its branch, unmerged, as the record
of the attempt for a human to read or salvage. Only systemic problems stop the loop — see
the skill's Stop Conditions.

**Every attempt is logged, structurally.** The verdict verbs append a run-log entry as part
of the same call that sets the status, and none of them can be called without a note, so a
verdict cannot land without a record. Evidence rides along as structured fields rather than
prose so it stays queryable: `pm_run_log(id, has_evidence=true)` returns only attempts that
proved something, and `pm_audit` raises `done-without-evidence` as a **warning** when a task
is done with nothing on its log. Failures stay visible to sessions that were not there.

## Lanes

`--lanes 2` lets the orchestrator keep two tasks in flight at once — lane A and lane B, one
claim each — so that it validates and merges the lane whose worker returned first while the
other worker is still running. The flag defaults to 1, and at 1 none of what follows applies.
Everything else is the same loop: the same pick, the same dispatch, the same verdict verbs,
and the same accept-then-merge ordering described under *Isolation model*.

**Lane compatibility is a store fact, not a judgment.** Two tasks may be in flight together
only when nothing in the store orders one against the other. Four rules, all of them read
rather than remembered (`lane_compatible` in `src/projectman/deps.py`, reached from the skill
as `pm_board(lane_compatible_with=<the task in flight>)`):

1. **Different stories.** Tasks of one story share a subject and usually a file set, and
   their intra-story order is exactly what the topological sort exists to preserve.
2. **Neither task depends on the other**, in either direction.
3. **Neither task depends on the other's story.** A task's `depends_on` may name a story, and
   depending on the whole story includes the task in flight.
4. **The two stories are not connected by `depends_on`** — any path, either direction,
   transitively.

Anything else is compatible. The rules are structural rather than temporal: whether the
dependency is already `done` is irrelevant here, because what must not overlap is the two
lanes' *edit sets*, and a task written against another story's work is as entangled with it
after that work lands as before. The orchestrator never settles this from its memory of what
two tasks touch — that is precisely the heuristic ADR-005 took out of the isolation model,
and re-deriving it in the scheduler would reinstate it one layer up. A board narrowed by the
filter reports `lane_excluded: <n>`, so a short list of candidates is never misread as an
empty backlog.

**Why two lanes, and not three.** The orchestrator is a single context, and validation is the
part of the loop that runs *in* it: step 17's validator is dispatched in the foreground, so
exactly one validation happens at a time however many workers are out. A third lane therefore
buys no extra validation throughput. What it does buy is a third branch cut from the run
branch before the first merge — conflicts grow with the number of concurrent branches, not
with the number of lanes — and a third set of in-flight bookkeeping, which claim, which
branch, which worker has returned, held in the context that projections and the validator
subagent exist to protect. The wait it would be spending that on is already covered: measured
worker waits are p50 8-11 minutes on this project and p50 21-36 minutes on a larger one (the
run-metrics table in [`cli.md`](cli.md)), and one overlapping lane covers a wait of that size,
because a lane's validation and merge fit comfortably inside the other lane's dispatch. Two
is the number at which the orchestrator stops idling; three is the number at which it starts
merging.

**Merge order is acceptance order, never dispatch order.** A branch reaches the run branch
when `pm_accept` takes its task and at no other time (*Isolation model*), and with two lanes
those two orders come apart: lane B's branch was cut from the run branch before lane A's merge
landed on it, so B's merge can conflict with work B never saw. That is expected rather than
exceptional, and it needs no new failure path — it is routed through the one already written
for a conflicting merge: abort the merge, `pm_retry` with the conflicting paths in
`evidence.files` and a note to rebase onto the run branch, then park on a second conflict. A
conflict retry keeps its lane and its task branch and is not a fresh dispatch, so it cannot
silently spend `--max`: that budget bounds how much *new* work a run starts, and a rebase of
work already done is not new work.

**The dependency barrier.** The second lane never dispatches a task whose dependency is still
in flight. Compatibility rules 2 to 4 bar it before the pick is made, which is the earliest
point at which it can be barred: a dependent task dispatched beside its dependency would start
from a run branch that does not yet carry the dependency's merge — the consequence ADR-005
records — and would then either re-implement it or collide with it. When the filter leaves
nothing available, that is an answer rather than an error: lane B idles until lane A is
accepted, and the final report says which lane idled.

**The validator is told which files are not its business.** Two lanes are two worktrees, so
the diffs never mix; but the forbidden-file check is a judgment about *scope*, and the other
lane's task is legitimately editing files this task must not. So the validator prompt names
the other in-flight task, whose files are out of scope for this verdict, and a diff that
reaches into them is a retry, not a park — the worker overstepped its task, it did not damage
another one. Nothing else about the validator changes; see *The validator subagent* for what
it is handed and why its report is bounded and JSON-shaped.

**One lane is the default, and it is the old loop exactly.** `--lanes 1` claims one task,
dispatches it, validates it, merges it, and picks the next — no second claim, no compatibility
filter, and no other-lane line in the validator prompt. Lanes are opt-in because the second
lane is paid for in the orchestrator's context and in merge conflicts, and a sprint short
enough not to notice the waits should not pay it.

## Heartbeat

The orchestrator spends most of a run waiting: a worker is dispatched in the background, the
turn ends, and nothing is sent to the API until the task notification lands. Prompt caching
makes that wait free only while the cache entry lives. Claude Code gives the main
conversation a one-hour entry on a subscription within plan, and the first call after a
longer gap re-sends the whole prompt as a cache *write* at twice the input price. Measured on
2026-09-17 across the three largest runs on a larger project (Claude Fable 5.1, 535-603k
peak context, every write a one-hour entry): one to three full misses per run, each after a
worker wait of 60-112 minutes, each re-writing 194-469k tokens — $6 to $16 a run at API rates,
19-45% of its input spend. Every miss sat right after a wait; none had another cause.

**The fix is a cached read before the entry expires.** A read refreshes the entry's timer on
either TTL, and a read of the whole prefix costs about 1/40th of re-writing it. The prior art
is [cachebeat](https://github.com/ARahim3/cachebeat), a Claude Code skill that polls the
session transcript for idle time and echoes a line that wakes the model into a few-word reply.
The orchestrator does not need the polling: it knows exactly when it goes idle, so Phase 0
arms one session-only cron job (`CronCreate`, every 30 minutes) whose prompt says to answer in
a few words with no tools while a worker is out. Cron prompts fire only while the REPL is
idle, never mid-turn, which is precisely the worker-wait window, and the job dies with the
session. The same prompt tells the orchestrator to `CronDelete` the job when no run is in
flight, so a run that dies before Phase 4 still stops beating; Phase 4 deletes it on the
normal path.

**Why 30 minutes, and why the one-hour cache.** The alternative is the five-minute cache — its
writes cost 1.25x rather than 2x — bridged by a ping every four minutes. Replaying the real call
timelines of those runs under one ideal cache model (read what the previous call had, write
the increment, re-write everything after a gap longer than the TTL; the model reproduces the
observed spend within 5%):

| Regime | Per run (three Kura sessions) |
|---|---|
| One-hour cache as run today | $45-56 |
| One-hour cache, heartbeat every 30 minutes | $32-39 |
| Five-minute cache, ping every 4 minutes | $49-59 (175-200 pings) |
| Five-minute cache, no pings | $180-240 (36-47 misses) |

The runs are bursty — 30-40 gaps of 5-30 minutes and 8-14 idle hours each — so the one-hour
entry covers the short gaps for a write premium of about $10 a run, while bridging them on the
five-minute cache costs 15 pings an hour, $12-24 a run. Ping-pong only wins under roughly four
idle hours per run. Thirty minutes is the shortest cron cadence that stays well inside the
hour with the scheduler's jitter; cron cannot express "every 50", and hourly plus jitter would
land past the TTL. Two beats an idle hour at 600k context is about $0.30. A beat is also not
free in context: its reply is appended to the prefix every future call re-reads, which is why
the prompt demands a few words and no tools.

**The five-minute cache is the real risk, not the alternative.** Claude Code drops the main
conversation to the five-minute TTL once a subscription draws on usage credits, and an API key
gets it always. On that cache every worker wait over five minutes is a full miss — the bottom
row of the table, four times the cost of the same run. The user-level setting
`promptCacheTtl: "1h"` pins the one-hour cache through overage; subagents stay on five
minutes, since a worker runs tools continuously and only pays the cheaper write. Because the
drop is silent, `projectman orch-cost` reports the TTL mix of a run — calls that wrote
`ephemeral_5m` versus `ephemeral_1h` entries, straight from `usage.cache_creation` — and the
number of heartbeat firings, so a run that ran cold shows up in its metrics rather than on the
bill. See *Sizes and numbers* for the cadence, and [`cli.md`](cli.md) for the report.

## Run identity

One opaque id per run, `orch-<YYYY-MM-DD>-<4 random hex>`, minted before pre-flight and
spent on every call that takes or clears a claim.

**Where the model flags sit.** The skill's `## Flags` section explains only `--resume`;
`--orchestrator-model` and `--executor-model` survive in the front-matter `args` line alone.
`--executor-model` is the one that acts — it names the model each worker and validator is
dispatched with — while `--orchestrator-model` is advisory: the model driving the loop is
whichever session invoked the skill, so the flag records an intent the skill itself cannot
enforce.

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

**Every pre-flight read is projected.** `pm_list_sprints(status="active", brief=True)` and
`pm_board(brief=True)` return identity, state and the three fields step 3 classifies from —
`claimed_by_run`, `claim_age`, `stale` — while dropping the sprint goal, the story labels,
the readiness blockers and the hints, none of which the loop acts on. Unprojected, that pair
measured 6.6 KB and 13 KB on the Kura runs, charged at pre-flight to the one context that has
to survive the whole sprint. Projection is what stops the run's fixed overhead scaling with
the size of the board.

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

**Why pre-flight looks at the working tree at all.** Under ADR-005 the run branch is cut
from `HEAD`, so `git status --short` at pre-flight is a *gate*: anything dirty outside
`.project/` stops the run and is reported as a list, because a branch cut from a dirty
`HEAD` bakes edits nobody attributed to a task into every task branch beneath it. What the
final report needs afterwards is not a snapshot but a diff — `git diff --stat HEAD...<run
branch>` — and what separates one task's work from another's is that task's own branch. The
`tar` + md5 snapshot Sprint 7 took before *each* dispatch is history; see *Known failure
modes*.

**Why a very dirty tree is still warned about.** Past the Phase 0 gate the modified list is
`.project/` churn, which every dispatch adds to and step 23 walks in the report. On the Kura
runs a 1,050-entry tree made that walk 55 KB — paid for a condition one commit would have
cleared. Past **200** entries Phase 1 therefore says so and names the fix, commit or clean
first, instead of paying it silently. It is a warning and not a stop because store churn is
legitimate and the run may still be the right thing to do; `--auto` continues, and the
condition is carried into the Phase 4 report so the next run's operator sees it.

**Why memory files and transcripts are never read during a run.** The orchestrator reads
store tools and the files a verdict genuinely needs, and nothing else — no memory file under
`~/.claude`, no session transcript. Such files are read whole, because they have no
projection to ask for (15 KB and 7 KB in one measured run), and what they hold is a previous
session's recollection: unversioned, unattributable, and superseded by the store, which is
where this run's facts already live. Anything in them that matters has to be re-verified
against `pm_activity` anyway, so the read buys a page of context and no additional
certainty.

**Why the per-run project context fetch was dropped.** Until `US-PM-49` the pre-flight
called `pm_context(max_doc_chars=2000, limit=5)` once per run and pasted the same excerpt
into every worker prompt, retries included. The bounds were the whole point: five docs at
2,000 chars each holds the return near 10k, where an unbounded `pm_context` returned
**48,588 characters** in one study. What the measurement missed is that the excerpt was
context each worker mostly did not read: on the Kura runs it was most of a 6.2 KB prompt,
re-sent per dispatch, while `pm_grab` already hands each worker its own task and story
context. So the paste went first, and with nothing left to amortise the fetch went with it —
the orchestrator makes no `pm_context` call at all now, and a worker that does need the
project docs is routed to them by `/pm-do`, where the bound is still stated.

## Dispatch and the worker prompt

**Why the plan read is one projected batch.** The plan is built out of story bodies,
acceptance criteria and the dependency and point wiring, so step 5 asks for exactly those
and nothing else: a single `pm_batch_get(ids=<sprint story ids>, fields="title,status,points,depends_on,acceptance_criteria,body")`
in place of an unprojected `pm_get` per story. Batching turns one round trip per story into
one for the sprint, and the field list leaves behind the run logs and history a full item
carries and the plan never opens — 16 KB of it on the Kura runs.

**Why a worker prompt is self-contained.** A worker has no prior context and no memory of
the run. Every fact it needs and nothing more — task, story, acceptance criteria,
DoD, the run id and the safety rules — is inlined, because a worker that has to rediscover
its context spends its budget on discovery and produces less implementation. Project docs
are not among those facts: they are the same bytes every dispatch, and `pm_grab` plus
`/pm-do` already route a worker that needs them.

**Why the run id is pasted into the prompt.** The worker's own `pm_grab` then claims under
the same run id rather than an anonymous per-process id, so the claim is attributable and
recoverable if the run dies mid-task.

**Why the worker's report has a fixed shape and a cap.** It is five ordered parts — files
changed as paths only, tests as `command -> pass|fail (n passed)`, DoD met, DoD unmet,
blockers — in at most about **1,500 characters**, with no code and no log output. The shape
is the reason: the first four parts transcribe straight into structured `evidence` (files,
tests, DoD met/unmet), where prose has to be re-parsed and loses exactly the structure the
evidence contract asks for. The cap is the other half of it. Worker reports averaged 5.6 KB
on the Kura runs, mostly pasted diffs and test output that the validator re-derives from the
tree anyway; unbounded, each dispatch leaves a page of duplicated evidence resident in the
one context that has to last the sprint.

**Why the worker is told its report will be independently verified.** A worker's self-report
is a claim, not a result. The stated verification is what makes "I ran the tests" cheaper to
prove than to assert.

**Why the orchestrator never implements, even a trivial task.** Its context is the
validation instrument. An orchestrator that has written the code cannot review it with fresh
eyes, and the context it spends implementing is context it no longer has for the sprint.

## Validation and verdicts

The governing rule: *the orchestrator's own judgment, never the worker's word.* The
judgment is the orchestrator's; since `US-PM-48` the *checking* that feeds it is delegated
to a validator subagent — see *The validator subagent* for why that is not a weakening of
the rule.

**The status read is deliberate and must never be removed.** `pm_get(task_id,
fields="status,assignee")` is trust-but-verify, and projection makes it nearly free — tens
of characters rather than thousands — so there is no efficiency argument for dropping it.
`assignee` is read alongside `status` because an unexpected assignee means something else
touched the task while the worker ran.

**Why the diff is read, not counted.** A `done` task with an empty diff is a failure unless
the task is genuinely non-code. File counts do not answer "do the changed files plausibly
match the task scope?" — only reading them does. The validator does the reading and reports
what it found; a file count would have been cheap to pass back and would have proved
nothing.

**Why tests are re-run rather than believed.** "Tests pass" from the party being validated is
the claim under test. Re-running is the only check that does not depend on the worker's
honesty or its definition of passing. The re-run happens inside the validator subagent, which
changes where the output lands, not whether the claim is checked.

**Why the three lists are collected while validating.** Files changed, test commands with
results, and DoD criteria met versus unmet are gathered by the validator as it checks, and
come back in its report, so the verdict is a transcription rather than a recollection.
Recollection is where evidence quietly stops matching what happened.

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

**Why a park continues the loop.** See *Isolation model*: parking is what keeps one bad
task from costing the sprint.

## The validator subagent

Steps 16–19 of the skill split validation in two. The orchestrator still owns the verdict —
it reads the task's status itself and it alone calls the verb — but the checks that produce
that verdict run inside a subagent whose context is discarded the moment it answers.

**Independence is unchanged: the validator is not the worker.** Trust-but-verify is a rule
about *who* checks, and it is untouched. The agent that wrote the code is still never the
agent whose word is taken for it. The validator is spawned fresh, with no memory of the
implementation and no stake in it, and is handed the task id, the run id, the DoD list, the
run and task branch names, and the worktree path and commit sha the worker reported — facts
about the *task*, not the worker's account of what it did. The worker's report goes along as a claim to be tested, in
exactly the role it had before. What `US-PM-48` moved is where the checking happens, not
whose assertion is under test.

**Why it now runs in a discarded context.** Measured 2026-09-09, per-task orchestrator
context growth ran 7–9k tokens in this project and 16–28k in a larger one, and the largest
visible bucket was validation itself: full test-runner output and the `git diff --stat` and
`git diff --name-only` listings of the task's branch.
Every byte of it is read once, to settle one question, and is never consulted again — but in
a single-context loop it stays resident for the rest of the sprint, competing with the plan,
the run's own record and the final report the orchestrator still has to write. A subagent's
window is thrown away when it returns, so that bucket is paid once and freed, and what
survives into the orchestrator is the conclusion rather than the working. This is why the
skill says the orchestrator must **never** run the tests or the branch diff itself: a
step 17 that "just checks quickly" reinstates the entire cost the split removed, and does it
invisibly, because the loop still looks correct.

**Why the report is bounded and JSON-shaped.** The validator answers with one JSON object of
about 1,500 characters at most — `verdict`, `files`, `tests`, `dod_met`, `dod_unmet`, `note`.
*Bounded*, because an unbounded report re-imports the very output that was moved out; a
validator free to paste its evidence back would undo the saving it exists to make, and the
cap is what makes the subagent's cost predictable per task rather than proportional to how
noisy the test suite is. *JSON-shaped*, because the object **is** the verdict call: `verdict`
picks the verb, `note` becomes the note, and the remaining fields map straight onto the
`evidence` argument of `pm_accept` / `pm_retry` / `pm_park` / `pm_review`. That keeps step 19
a transcription with no parsing step — the same property *Validation and verdicts* asks of
the three lists — and it keeps the caps in [`evidence-contract.md`](evidence-contract.md)
enforced by the store rather than by whichever agent remembered them. Prose would have to be
re-read and re-shaped by the one context the split was protecting.

**What a malformed verdict does.** A validator that returns nothing, returns prose, or
returns JSON with no usable `verdict` has said nothing about the task. Reading that as an
accept trusts an agent that did not answer; reading it as a task failure blames the worker
for the validator's silence. So it is neither: a missing or malformed verdict counts as **one
validation failure**. The validator is re-run once, and if the second attempt also comes back
without a verdict the task is parked with the fixed note `validator returned no verdict`.
Parking names the true state — the task is unjudged, not failed — and it keeps the loop
moving, per *Isolation model*. The note is fixed wording on purpose: a validator that is
systematically malforming its answers then shows up in the run log as one greppable pattern
instead of a scatter of unrelated parks.

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
died with half-written files in its worktree, and the store records nothing about how far
it got. So the adopted task's branch and worktree are read first — its last commit on
`orch/<run-id>/<task-id>` and the status of the checkout that branch was left in — and the
prompt carries the `<on resume: ...>` line telling the worker to validate that state before
editing. A failure on an
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
`git clean`.** Undo a temporary edit with the same edit tool that made it. The rule did not
relax when tasks moved into their own worktrees under ADR-005: until the worker commits its
branch, its worktree is still the only copy of that task's work.

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
still not the safeguard: the `tar` + md5 snapshot taken *before* each dispatch — the
`snap.sh` habit — was, because it turned recovery from a transcript replay into a `tar x`.
→ **Rule, as ADR-005 revised it: a task that mutation-tests source files must still leave
them byte-identical, but the snapshot and the md5 list are gone.** Each task edits its own
worktree on its own branch, so `git diff --stat <run branch>...<task branch>` is what it
changed and `git diff --name-only` is the list the forbidden-file check is judged from — a
boundary rather than a heuristic, checked before the branch is merged rather than after the
damage. Recovery is the unmerged branch, not a tarball, so `snap.sh` has no job left. A
related rule from the same sprint: a task touching git plumbing must not run the new command
against the real repo.

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
| **48,588 chars** | An unbounded `pm_context` return, measured in one study | Why every documented `pm_context` call is bounded at `max_doc_chars=2000, limit=5`, which holds the return near 10k |
| **2,000 / 5** | `max_doc_chars` / `limit` on the `pm_context` calls that remain | Five docs × 2,000 chars ≈ 10k. `US-PM-49` removed the orchestrator's own call; the bound is pinned where the pointers live — `/pm`, the pm agent and `/pm-do` |
| **200 entries** | The `git status --short` size past which Phase 1 warns | Steps 14 and 23 re-walk that list every dispatch (55 KB per dispatch on a 1,050-entry tree), so beyond it the fix — commit or clean — is worth naming |
| **200 chars** | The skill's note-length guidance for a verdict | A human one-line summary; the lists belong in `evidence`. Distinct from the store's hard cap |
| **4,096 chars** | `store.RUN_LOG_NOTE_LIMIT` | The server-side truncation point — notes are clamped, never rejected, so a verdict never fails on note length |
| **16 hex** | The `digest:` line in an audit report | The token passed back as `pm_audit(since=…)`; a match short-circuits to `unchanged: true` and no checks run |
| **every 3 accepted tasks** | Health-check cadence | Frequent enough to catch mid-run drift, cheap because `since=` makes an unchanged answer a few bytes |
| **2 lanes** | The most `--lanes` offers; the default is 1 | One validation runs at a time whatever the lane count, so a third lane adds concurrent branches to merge and in-flight bookkeeping without adding throughput; the waits it would cover — p50 8-11 min here, p50 21-36 min on a larger project — are already covered by one overlap. See *Lanes* |
| **7–9k / 16–28k tokens** | Per-task orchestrator context growth, measured 2026-09-09 in this project and in a larger one | The measurement behind *The validator subagent*: validation output was the largest visible bucket, so it was moved into a context that is discarded |
| **~1,500 chars** | The cap on the worker's report back to the orchestrator | Reports averaged 5.6 KB unbounded, mostly output the validator re-derives from the tree; the fixed five-part shape transcribes into `evidence` |
| **~1,500 chars** | The cap on the validator's JSON report | Bounded so the report cannot re-import the output the split removed; the object doubles as the `evidence` argument |
| **every 30 minutes** | Heartbeat cadence (`CronCreate`, session-only) | The shortest cron cadence that stays well inside the one-hour cache TTL with scheduler jitter; each beat is a cached read at about 1/40th of the re-write a miss costs. See *Heartbeat* |
| **2 hours** | `stale_claim_hours` default (`pm_active(stale_after=…)` overrides per call) | The point past which an `orch-` claim is treated as recoverable rather than live |
| **`offset` + `has_more`** | Activity-log paging in resume and the final report | The report must hold *every* event in the run's slice; a single unpaged page is a silently truncated report |
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
| `## Operating Model` | 22–28 | 1,215 | ~900 | *Isolation model* (all four bullets' reasoning, incl. the run-log/evidence paragraph) |
| `## Phase 0 — Model Selection and Run Identity` | 29–47 | 1,841 | ~500 | *Run identity* (big-model/cheap-model split, coarse-tier mapping, advisory-orchestrator argument) |
| `### Run id — mint it here, spend it everywhere` | 48–57 | 1,645 | ~950 | *Run identity* (prefix is load-bearing, random tail, why every call carries it, why the report is built from it, fresh id on resume) |
| `## Phase 1 — Pre-flight` | 58–71 | 4,020 | ~1,620 | *Pre-flight and claim classification* (the projected sprint and board reads, the three claim branches and their reasons, the no-prompt argument, the tree snapshot and its dirty-tree warning, the no-memory-reads rule, the 48,588-char `pm_context` study) |
| `## Phase 2 — Build the Execution Plan` | 72–80 | 785 | ~210 | *Dispatch and the worker prompt* (why the plan read is one projected batch; out-of-sprint blockers) |
| `## Phase 3 — Execution Loop` | 81–90 | 1,471 | ~380 | *Dispatch and the worker prompt* (pre-claimed `next`, idempotent re-claim, foreground + no-worktree reasoning) |
| `### Validation — your own judgment, not the worker's word` | 91–119 | 5,702 | ~2,100 | *Validation and verdicts* + *The validator subagent* + *Health checks*; verb semantics link to `verdict-verbs-contract.md`, evidence shape to `evidence-contract.md` |
| `## Phase 4 — Final Report` | 120–137 | 3,812 | ~1,400 | *Final report from the activity log* (log-over-memory, why park/review and retry/release need a second read, why points are re-read, why the diff stays) |
| `## Resume — Picking Up an Interrupted Run` | 138–161 | 5,337 | ~4,300 | *Resume protocol* (R1–R5 in full, plus "when not to resume") |
| `## Worker Prompt Template` | 162–206 | 2,233 | ~350 | *Dispatch and the worker prompt* (self-containment, pasted run id, the capped fixed-shape report, independent verification) |
| `## Stop Conditions` | 207–216 | 847 | ~190 | *Health checks* (why `unchanged: true` is never a stop) and *Resume protocol* (live-run race) |
| `## What This Skill Does NOT Do` | 217–224 | 714 | ~250 | *Isolation model* (sequential, no push) and *Validation and verdicts* (never implement) |
| **Total** | 8–225 | **31,731** | **~13,400** | |

Rationale with no home in the template — the Sprint 5/6/7 and 2026-09-05 incidents that
produced the worker safety rules — is recorded here under *Known failure modes*; the rules
themselves belong in the worker prompt (`US-PM-25-7`).
