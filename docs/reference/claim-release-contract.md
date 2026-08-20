# The Claim / Release Contract

**Task:** US-PM-7-6 · **Story:** US-PM-7 — Atomic task claim and release primitive
**Date:** 2026-07-30 · **Version:** v0.8.9 (this checkout)
**Status:** DECIDED — three decisions below are binding on `US-PM-7-7`, `US-PM-7-8`
and `US-PM-9`.

This document is a contract, not an implementation. No store or server behaviour is
changed by this task. `US-PM-7-7` implements §2 (compare-and-swap claiming),
`US-PM-7-8` implements §1 and §3 (release and the field-clear affordances), and
`US-PM-7-9` applies §4 to `pm-orchestrate/SKILL.md`.

---

## Verdict in one line

Release gets **both** a dedicated `pm_release` verb *and* an `unassign: bool` on
`pm_update`; claiming gets a **compare-and-swap on the on-disk `assignee`, taken under
an exclusive file lock**, whose loser is an *expected negative* and never an error; and
`depends_on` / `tags` get a **`clear="<field names>"` parameter whose value is the name
of the field to clear**. The single rule generating all three: *no operation may require
the caller to spell emptiness.*

---

## 0. The governing principle

Every measured failure in this class has the same shape. The model must express
"nothing" in a value position, discovers `null` already means *leave unchanged*, and
emits a bare key:

```json
{"id": "US-HP-82-11", "status": "todo", "assignee": , "outcome": "info", "note": "Released by orchestrator..."}
```

So the design rule is not "document the sentinel better". It is:

> **Nothing-valued intents must be expressed by a present, non-empty token.**
> A verb name, a boolean, or a field name — never an absence.

And its corollary, which is what makes this a schema fix rather than a documentation
fix:

> **Every plausible spelling of the intent must land somewhere valid.**
> Removing a capability from where the model reaches does not stop the reach; it
> converts a malformed call into a dead end. So `pm_release(...)`,
> `pm_update(unassign=true)`, `pm_update(clear="assignee")` and the legacy
> `pm_update(assignee="")` all succeed. Only one of them is *documented*.

### The evidence

| Machine | Malformed `pm_update` calls | Share of that machine's total errors |
|---|---:|---|
| Study D | 48 | 48 of 49 |
| Study A | 62 | — |
| Study C | 31 (`assignee`) + 17 (`depends_on`) + 6 (`note`) = 44 of 45 payloads | 44 of 55 total |
| Study B | 27 | — |

Sources: `an internal usage study` §1, `an internal usage study` §5 and
"Recommendations" §3, `an internal usage study`, `an internal usage study`.

Two facts from that data shape the design and are easy to miss:

1. **`depends_on` is the second-biggest case (17) and has no sentinel at all** — not
   even an undocumented one. Whatever is decided for `assignee` must generalise, or
   this recurs field by field.
2. **The dominant payload is not "unassign", it is "release"** — a *compound*
   operation. Study C's malformed payloads carry `status: "todo"` **and** an `outcome` /
   `note` reading `"Released by orchestrator..."`. The model was hand-assembling a
   three-field transaction out of a generic setter. That is an argument for a verb, not
   just a flag.

### Why the previous fix did not take, precisely

Commit `2261a0d` (2026-07-04, v0.8.14) added `pm_update(assignee="")` → clears, plus
one docstring line. Study D's failures run 2026-07-24 → 2026-07-28, three weeks later. The
docstring line sits at argument 5 of 14 and loses to the `null` prior. Nothing about
that is fixable with more prose.

**Port-forward hazard — resolved by the 0.8.15 rebase.** The analysis below was written
when this tree was v0.8.9 and `2261a0d` was **not** an ancestor of HEAD. It is now: the
tree is v0.8.15 and `store.py:1936` carries the `unassign = kwargs.get("assignee") == ""`
normalisation, so only the `origin/main` column below still describes this checkout. The
two baselines *as they stood then* differed:

- **`origin/main`** normalises correctly — `store.py:969` `unassign = kwargs.get("assignee") == ""` → writes `None`.
- **This tree at v0.8.9** had no such normalisation. `Store.update` applied
  `if value is not None: post.metadata[key] = value` (`store.py:1763-1765`), so `""` is
  written **literally**. Measured on a scratch store in that tree:

  ```
  s.update(tid, assignee="", status="todo")
  → returned assignee   : ''
  → re-read from disk   : ''
  → frontmatter line    : assignee: ''
  → check_readiness     : ready=False, blockers=["already assigned to ''"]
  ```

  `readiness.py:23` tests `task_meta.assignee is not None`, and `''` is not `None`. So
  on that baseline the documented release sentinel did not merely fail to be spellable —
  **when it was spelled correctly it bricked the task permanently.**

`US-PM-7-8` must therefore land the `"" → None` normalisation *as well as* the new
surface, and must not assume the upstream half is present. Whichever baseline the work
lands on, the normalisation is required and must survive the merge.

---

## 1. Decision 1 — the release surface

> **Decision: both.** A dedicated `pm_release` verb is the primary and the only form
> documented in skills; `unassign: bool = False` on `pm_update` is the secondary
> landing spot; `clear="assignee"` (§3) is an accepted third spelling; the legacy
> `assignee=""` keeps working, undocumented.

### 1.1 `pm_release` — the primary

```python
@mcp.tool(
    title="Release Task",
    annotations=ToolAnnotations(
        title="Release Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_release(
    task_id: Optional[str] = None,
    status: str = "todo",
    note: Optional[str] = None,
    outcome: Optional[str] = None,
    expected_assignee: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
```

**Why it has no malformed form.** The failure is a *value* the model cannot spell.
`pm_release(task_id="US-PM-7-6")` has exactly one required argument and it is a
content-bearing string the model already holds. There is no `assignee` parameter, so
`{"assignee": }` is not merely discouraged — it is unreachable. Emptiness is expressed
by the *verb name*, which is a token, not an absence.

**Why a verb and not only a flag.** Release is compound: clear assignee, reset status,
append a run-log entry. Study C's payloads prove the model was already assembling all
three. One verb collapses a three-parameter transaction into a one-parameter call, and
is the exact inverse of `pm_grab`, which already exists as a dedicated verb for the
claim half. `grab` / `release` is a symmetry a model can predict; `grab` /
`update(status=..., assignee=...)` is not.

**Semantics.**

| Aspect | Contract |
|---|---|
| Effect | `assignee → None`; `status → status` (default `todo`); `updated` bumped |
| Run log | Appended iff `note` or `outcome` given; `outcome` defaults to `info`, matching `pm_update` |
| Idempotence | Releasing an already-unassigned task **succeeds** with `from_assignee: null`. It is not an expected negative — the orchestrator's cleanup loop must not have to branch on a condition it does not care about |
| Guard | `expected_assignee` is optional. Omitted → unguarded release (the orchestrator case, which is the measured hot path). Supplied and mismatched → expected negative, task untouched |
| Scope | Tasks only. A story or epic id is a **genuine failure** (`ToolError`), because `assignee` is a task-only field (`models.py:140`) |
| Not found | `FileNotFoundError` → `raise _failed(e) from e`, per `server.py:154` |
| Side effects | Same as `pm_update`: activity-log `update` event with an `assignee` before/after diff, `_auto_commit`, `write_index(store)` |

**Success response** — follows the `updated:` / `grabbed:` house shape:

```yaml
released:
  task: {...}            # full TaskFrontmatter model_dump(mode="json")
  from_assignee: claude  # or null when it was already unassigned
```

`from_assignee` is the one field added beyond the task itself. It is the caller's only
way to learn whether the release actually took something, and it is what makes the
unguarded default safe to reason about. Response bytes are a tracked cost
(`docs/telemetry/baseline-pre-fix.md`) — nothing else is added.

**Guarded-release negative** (`expected_assignee` mismatch), using the
`_expected_negative` helper at `server.py:111`:

```yaml
outcome: expected_negative
status: not_holder
message: task is held by another assignee
holder: worker-2
expected: worker-1
```

### 1.2 `unassign: bool = False` on `pm_update` — the secondary

**Why keep it at all.** `pm_update` is 36.8% of all ProjectMan calls
(`an internal usage study` §2). A model with `pm_update` already in context will
reach for it. Per the corollary in §0, that reach needs a landing spot.

**Why a boolean has no malformed form.** JSON has exactly two boolean literals, `true`
and `false`; both are non-empty tokens. There is no "empty boolean" to emit. Critically,
the default is `False`, **not `None`** — so unlike every other parameter on this tool,
`null` is not this parameter's "leave unchanged" value. The prior that defeated the
`""` sentinel has nowhere to land.

**Semantics.** `unassign=True` sets `assignee → None`, identically to `pm_release`, but
touches *nothing else* — no status reset, no run-log entry. It is the field-level
primitive; `pm_release` is the transaction.

**Conflict rule.** `unassign=True` together with a non-empty `assignee="name"` is
contradictory. It is a **genuine failure** (`ToolError`), not a precedence rule. A
silent winner would let a release silently become an assignment.

### 1.3 What is *not* done

- **`assignee=""` is not removed.** It keeps clearing the assignment forever
  (back-compat, and cheap). It is deleted from the `pm_update` docstring and from
  `docs/reference/mcp-tools.md` — a *documented* sentinel is precisely what trained the
  malformed prior. Undocumented-but-accepted is the right end state.
- **`pm_grab` is not renamed.** It is 342 measured calls with an established payload.
  `pm_release` is named to pair with it, not to replace it.
- **No new tool beyond `pm_release`.** `US-PM-9` tracks trimming 16 zero-call tools;
  one new tool with a measured 100+ failure hot path is comfortably net-positive
  against that budget.

---

## 2. Decision 2 — compare-and-swap claim semantics

> **Decision:** the compare is on the **on-disk** `assignee` *and* `status`, re-read
> inside an exclusive `fcntl.flock` critical section on the task file and bypassing the
> process cache. The loser is an **expected negative** (`status: already_claimed`) and
> the task is left untouched. The winner's return shape is **unchanged**.

### 2.1 Why there is a race today

`pm_grab` (`server.py:1500-1535`) does:

```
store.get_task(task_id)        # read  — may be served from the module-level cache
check_readiness(...)           # test  — assignee is None?
store.update(task_id, ...)     # write — unconditional
```

Read, test, write, with no lock and no re-verify. Two workers can both pass
`check_readiness` and both write; the second silently wins and the first believes it
holds the task. There is **no locking or atomic write anywhere in the codebase** —
verified: `grep -rn "fcntl\|flock\|os.replace\|O_EXCL" src/` returns nothing, and
`Store` writes with a bare `path.write_text(frontmatter.dumps(post))`
(`store.py:1775`). This is why the story can cite SKILL.md's own admission: *"No
parallel workers — sequential until the store supports atomic claiming."*

### 2.2 What is compared

A new store primitive, not a flag on `update`:

```python
def claim_task(
    self, task_id: str, assignee: str, expected_assignee: str | None = None
) -> tuple[bool, TaskFrontmatter]:
    """Atomically claim a task.  Returns (won, current_meta)."""
```

Inside an exclusive lock on the task's own file, re-read **from disk** (never from
`_cache`; `get_task` will serve a cached copy, `store.py:1568-1572`) and evaluate:

```
won  ⟺  (disk.assignee is None and disk.status == todo)
      or (disk.assignee == assignee and disk.status in {todo, in-progress})
```

Three things are compared, in this order:

1. **`assignee`** — the swap variable. This is the CAS proper.
2. **`status`** — a task that reached `review` or `done` between the readiness check
   and the lock must not be claimable even though its assignee may be `None`.
3. **`expected_assignee`**, when supplied — narrows the predicate to
   `disk.assignee == expected_assignee`, for a caller performing an explicit
   hand-off rather than taking from the pool.

The second clause is the **idempotent re-claim** from `2261a0d` / `readiness.py`'s
`reclaim_for`, preserved verbatim. It is load-bearing: `pm_done_next` pre-claims a task
for a worker that then calls `pm_grab` itself. A CAS that rejected the holder's own
re-claim would break the entire orchestrator hand-off. **`US-PM-7-7` must not drop
this.**

### 2.3 Locking and durability

- **`fcntl.flock(LOCK_EX)` on the task file**, held across read-verify-write. Chosen
  over an `O_CREAT|O_EXCL` lockfile because it is released automatically when the
  process dies — a crashed worker leaves no stale lock to reap, and there is no
  lock-expiry policy to get wrong. ProjectMan's `.project/` is a directory in a local
  git repo; single-host POSIX locking is sufficient and no distributed case exists.
- **Write via temp file + `os.replace`**, so a concurrent reader never observes a
  half-written frontmatter block. `os.replace` is atomic within a filesystem.
- **Cache invalidation inside the lock.** The winner calls `_invalidate_cache("tasks")`
  (or `_cache_update_entry`) before releasing, so no reader can observe the pre-claim
  value after the claim is durable.
- **Lock scope is one task file.** No global lock — two workers claiming *different*
  tasks must not contend.

`check_readiness` stays where it is, outside the lock: it is the expensive part
(`list_tasks`, `list_stories`, story lookup) and it is advisory. The lock covers only
the cheap re-verify plus the write. A task that passes readiness and then loses the CAS
gets `already_claimed`, which is the correct and honest answer.

### 2.4 What happens to the loser

> The loser gets an **expected negative**. It is never an `is_error`, and the task is
> left byte-for-byte untouched.

```yaml
outcome: expected_negative
status: already_claimed
message: task is already claimed
holder: worker-2
task_id: US-PM-7-6
```

**Why not an error.** Two workers racing for one task is the *normal* operation of a
parallel pool, not a fault. `server.py:111-151` is explicit: an expected negative is
"a valid negative answer, not a failure" — the caller asked whether it could take this
task and got an informative no. Classifying it as `is_error` would make routine
contention indistinguishable from real breakage in every transport-level metric, which
is the entire subject of `US-PM-2`. `already_claimed` joins `not_ready`, `not_created`
and `nothing_to_commit` as a documented `status` code.

**Why a new code rather than reusing `not_ready`.** The recovery differs, and `status`
is the field callers branch on. `not_ready` means *this task needs fixing* (estimate it,
unblock its dependencies). `already_claimed` means *this task is fine, take a different
one*. `holder` is the detail field, exactly as `blockers` is `not_ready`'s.

### 2.5 The winner's return shape

**Unchanged.** `pm_grab` returns the same `grabbed:` mapping it returns today
(`server.py:1608-1622`) — `task`, `body`, `story_context`, `sibling_tasks`,
`sibling_tasks_total`, `dependency_status`, and `warnings` only when non-empty. No
success-path field is added: `pm_grab` is already 34% of all ProjectMan bytes
(`an internal usage study` §2), and a caller that got `grabbed:` has, by
construction, won. Winning needs no announcement.

The CAS is therefore invisible to every currently-correct caller. The only new
observable is the `already_claimed` negative, which today's callers cannot receive
because today's `pm_grab` cannot detect the condition.

---

## 3. Decision 3 — the clear affordance for `depends_on` and `tags`

> **Decision:** one parameter, `clear: Optional[str]`, on `pm_update` — a
> comma-separated list of **field names** to clear. `clear="depends_on"`,
> `clear="tags"`, `clear="depends_on,tags"`.

### 3.1 Why this shape

**It has no malformed form because the value is content, not emptiness.** The model
types the *name of the field it wants cleared* — a token it already holds, in the same
vocabulary as the parameter names it is looking at. Contrast `depends_on=""`, which
requires spelling emptiness and produced 17 malformed payloads with no sentinel
documented at any point.

**Why one parameter rather than per-field booleans.** `clear_depends_on`, `clear_tags`,
`clear_points`… adds one parameter per clearable field to a tool that already has 14 —
and the story itself identifies "argument 5 of 14" as part of why the last fix lost.
`clear` is a single parameter that covers every clearable field, including ones added
later, and it appears once in the docstring rather than N times.

**Why `unassign` is a boolean while these are not.** This is a frequency decision, not
an inconsistency. Assignee-clearing is the measured hot path (31 + 48 + 27 + 62
occurrences); the highest-frequency operation earns the shortest spelling and a
top-of-docstring position. `depends_on` and `tags` clearing is comparatively rare (17
and 0 measured) and does not warrant its own parameter each. Per §0's corollary,
**`clear="assignee"` must also be accepted** so a model that generalises from the
`depends_on` pattern lands somewhere valid instead of malformed.

### 3.2 Contract

| Field name | Cleared to | Applies to |
|---|---|---|
| `assignee` | `None` | tasks |
| `depends_on` | `[]` | tasks, stories |
| `tags` | `[]` | epics, stories, tasks |
| `points` | `None` | epics, stories, tasks |
| `epic_id` | `None` | stories |

- **Unknown field name** → **genuine failure** (`ToolError`) whose message lists the
  valid names. This is a caller bug, and the error text is the recovery path.
- **Field not valid for this item type** (e.g. `clear="assignee"` on a story) →
  `ToolError`, same reasoning.
- **`clear="tags"` together with `tags="a,b"`** → `ToolError`. Contradictory
  instruction; loud and deterministic beats a silent precedence rule.
- **Clearing an already-empty field** is a **success**, not a negative. `clear` is
  declarative — it states the field's desired end state, and the state is already
  correct. Only `updated` changes.
- **Whitespace is tolerated**: `clear="depends_on, tags"` splits and strips, matching
  the existing CSV handling at `server.py:1388-1394`.

### 3.3 Store-level shape

`Store.update` cannot express clearing today: `if value is not None:`
(`store.py:1763-1765`) drops exactly the value that means "clear". Add an explicit
parameter rather than a magic sentinel object:

```python
def update(self, item_id: str, *, clear: Iterable[str] = (), **kwargs): ...
```

An explicit `clear` set is preferred over a module-level `CLEAR` singleton because the
downstream code that must also see it is ordinary iteration, not a value check —
specifically:

- the **activity-log diff** (`store.py:1826-1836`) must record cleared fields as
  `{"before": [...], "after": []}`; it currently loops `if value is not None` and would
  silently omit them;
- the **auto-commit message** (`store.py:1717-1720`) should render `clear=depends_on`;
- **`_validate_task_depends_on`** must be skipped for a cleared `depends_on` (an empty
  list is trivially valid), and the **cycle check** at `store.py:1813` need not run.

---

## 4. What `pm-orchestrate/SKILL.md` must say (input to US-PM-7-9)

`pm-orchestrate` is not vendored in this repo — it is referenced by `.project` tasks and
by a comment at `audit.py:336`. `US-PM-7-9` edits it wherever it is installed. Both
sites (step 13 and the stop-conditions block) currently instruct:

```
pm_update(<id>, status="todo", assignee="")      ← DELETE
```

Replacement:

```
pm_release(<id>, note="<why it was released>")
```

Constraints on that rewrite, so the fix is not undone by prose:

1. **`assignee=""` must not appear anywhere in the skill.** It remains accepted by the
   server (§1.3) but documenting it is what trained the failure.
2. **No status parameter in the documented form.** `todo` is the default; naming it
   invites the model back into multi-parameter assembly.
3. **The stop-conditions block and step 13 must use identical text**, so the model sees
   one form, not two.

---

## 5. Summary of what each downstream task owes

| Task | Owes |
|---|---|
| `US-PM-7-7` | `Store.claim_task` with `flock` + on-disk re-verify + `os.replace` (§2.2, §2.3); `pm_grab` returns `already_claimed` on loss (§2.4); idempotent re-claim preserved (§2.2); success shape unchanged (§2.5) |
| `US-PM-7-8` | `pm_release` (§1.1); `unassign: bool` (§1.2); `clear: str` on `pm_update` and `Store.update` (§3); the `"" → None` normalisation and its port-forward note (§0) |
| `US-PM-7-9` | The SKILL.md rewrite (§4) |
| `US-PM-7-1` | Release is expressible with no empty-string or null sentinel (§1) |
| `US-PM-7-2`, `US-PM-7-5` | Concurrent claim: exactly one winner, loser gets `already_claimed` and the task is untouched (§2) |
| `US-PM-7-3` | `clear` covers `depends_on` and `tags`; conflict and unknown-name cases raise (§3) |
| `US-PM-7-4` | SKILL.md contains no `assignee=""` (§4) |
| Docs | `docs/reference/mcp-tools.md` gains `pm_release`, `unassign`, `clear`, and the `already_claimed` / `not_holder` codes in its expected-negative section; the `assignee=""` mention is removed |
