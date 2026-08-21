# The Verdict Verbs Contract

**Task:** US-PM-8-6 · **Story:** US-PM-8 — Verdict verbs for the orchestrator state machine
**Date:** 2026-08-21 · **Version:** v0.8.9 (this checkout)
**Status:** DECIDED — binding on `US-PM-8-7` (implement), `US-PM-8-8` (compat),
`US-PM-8-9` (rewrite `pm-orchestrate`), and the tests `US-PM-8-1/-2/-4`.

This document is a contract, not an implementation. No behaviour changes with this task.

---

## Verdict in one line

Each of `pm-orchestrate` SKILL.md step 19's four verdicts gets a verb that **fixes status
and outcome in the tool itself**, so neither can be omitted or mismatched; **`note` is
required on all four**, so a terminal move cannot land without a run-log entry; and
**`pm_accept` absorbs `pm_done_next`** — complete-plus-next is the orchestrator's actual
unit of work, and splitting it re-creates the grab-then-update pair the data shows losing
(512 pairs vs 387 `pm_done_next` calls).

The governing rule, the sibling of the one in `claim-release-contract.md`:

> **A verdict is said by the verb, never by a values triple the caller must remember.**

---

## 1. The four verbs

| Verb | Verdict (step 19) | status | outcome | assignee | note |
|---|---|---|---|---|---|
| `pm_accept` | Accept | `done` | `success` | **kept** (attribution) | required |
| `pm_retry` | Retry | `todo` | `failed` | cleared | required |
| `pm_park` | Park | `review` | `blocked` | cleared | required |
| `pm_review` | Accept-as-review | `review` | `partial` | cleared | required |

`status` and `outcome` are **not parameters**: there is no way to call `pm_park` and get
`success`, nor to reach `done` without `success`. `pm_accept` keeps the assignee because a done task records who did it; the other three
clear it because the task is going back to the pool (`retry`) or waiting on a human
(`park`, `review`), and a stale holder blocks the next `pm_grab`. `pm_retry` / `pm_park` /
`pm_review` accept **any** starting status including `done` — the common case is precisely
a worker that self-reported `done` and failed validation. Only `pm_accept` guards (§2).

### Signatures

Style matches `pm_release` / `pm_done_next` in `src/projectman/server.py`: `task_id` with
an `id` alias resolved by `_resolve_id`, `project` last, `@mcp.tool(...)` with
`ToolAnnotations(readOnlyHint=False, destructiveHint=False)`.

```python
def pm_accept(task_id=None, note=..., next_task=True, same_story_only=True,
              assignee="claude", project=None, id=None) -> str
def pm_retry (task_id=None, note=..., project=None, id=None) -> str
def pm_park  (task_id=None, note=..., project=None, id=None) -> str
def pm_review(task_id=None, note=..., project=None, id=None) -> str
```

`note: str` has **no default** — FastMCP rejects the call before any write, so an omitted
note never leaves half a verdict on disk; a blank note raises `ToolError` for the same
reason. Oversized notes are truncated at `store.RUN_LOG_NOTE_LIMIT` (4096) exactly as
`pm_update` does — never rejected — and the response then carries `note_truncated`,
`note_original_length`, `note_stored_length`, `note_dropped_chars`, `note_limit`.

`pm_accept` only: `next_task=False` completes without claiming anything; `same_story_only`
defaults **true** (step 19 already requires it — `pm_done_next` has no sprint filter and
siblings are always in-sprint); `assignee` is who claims the next task.

### Responses

- `pm_retry` / `pm_park` / `pm_review`: `{"<verb>ed": {"task": <meta>, "from_status": ...,
  "from_assignee": ...}}` plus truncation fields — the `pm_release` shape.
- `pm_accept`: `completed: {id, status: done, run_log: success}`, `story_closed: <id>` when
  this closed the parent story, and `next: {...}` — byte-compatible with `pm_done_next`
  today. With `next_task=False` the `next` key is absent entirely.

### Validation / error cases

| Case | Result |
|---|---|
| id is a story or epic | `ToolError` — "applies to tasks only" (mirrors `pm_release`) |
| unknown id | `ToolError` from `store.get_task` via `_failed` |
| `note` missing / blank | `ToolError`, nothing written |
| `pm_accept` on an already-`done` task | expected negative `already_done` — no second run-log entry, no second story close, no next grab |
| `pm_accept` finds no next task | expected negative `no_next_task` (§3) — the completion still landed |
| next task lost the claim race | that candidate is skipped; the loop continues (`_do_grab` already returns `already_claimed`) |

Expected negatives use `_expected_negative` / `_expected_negative_payload`: `outcome:
expected_negative` + machine-readable `status`. They are successes, never `is_error`.

---

## 2. `pm_accept` absorbs `pm_done_next`

**Decision.** One internal `_do_accept(store, task_id, note, next_task, same_story_only,
assignee)` holds the logic. `pm_accept` is its verdict-shaped front door; `pm_done_next`
becomes a thin wrapper over the same function and **stays forever** — it is not
deprecated-then-removed, and its signature (`outcome="success"`, `note` optional,
`same_story_only=False`) is unchanged.

Rationale: the two calls are one decision — "accepted" and "give me the next one" are the
same beat of the orchestrator loop, and the measured failure is callers splitting them
(`pm_grab` + `pm_update(done)`). A `pm_accept` that did not return `next` would leave
`pm_done_next` as the fast path and the new verb as the slow one — the opposite of the
intent. `next_task=False` covers the non-orchestrator caller.

**Exhaustion.** `next: null` in 22% of calls is the normal case, not an edge, and its shape
is unchanged from today's `pm_done_next`: the payload leads with
`_expected_negative_payload("no_next_task", ...)`, then `completed`, then `next: None` and
the `next_info` hint (which already distinguishes "in this story" from "in this project" by
`same_story_only`). Step 19's "when `next` is `null`, fall back to the plan via step 11"
therefore survives the rewrite verbatim; a `same_story_only=True` exhaustion is the
expected end of a story and usually arrives with `story_closed` alongside it.

**Store calls.** `Store.get_task`, `Store.update(task_id, status=..., outcome=...,
note=..., clear=["assignee"])`, `Store.list_tasks(story_id=...)` + `Store.get_story` for
the auto-close, and the server helpers `_do_grab`, `write_index`, `_emit_status_change`,
`_note_truncation_fields` (read it immediately after the verdict write — the story close
and the next grab both reset `store.last_note_truncation`).

---

## 3. Run-log entries

`Store.update` appends a run-log entry when `outcome is not None or note is not None`
(`store.py`, `_append_run_log`). Every verdict verb passes a fixed non-null `outcome` and a
required non-empty `note`, so **an entry is structurally unavoidable** — that is the
mechanism behind the story's "share of completions lacking a run-log entry drops to zero".
Entries record the post-update status: a `pm_park` entry reads `status: review, outcome:
blocked`.

`pm_done_next`'s hole is closed inside the wrapper: it currently forwards `outcome` *only
when a note was given*, which is the 13% of `done` writes with no run log. It will now
always forward the outcome, substituting the fixed note
`"completed via pm_done_next (no note given)"` when the caller omits one (or passes a
blank one) — no signature
change, no rejected call, and the omission stays visible in the data rather than vanishing.

---

## 4. Backwards compatibility

`pm_update(id, status=...)` keeps working **exactly** as today, including `status="done"`
with no `outcome`/`note` and therefore no run-log entry. It is the generic escape hatch and
the compat surface (US-PM-8-8); nothing about it is deprecated, warned on, or made
stricter, and the verdict verbs are purely additive. Traffic moves off `pm_update` because
US-PM-8-9 rewrites the skill, not because the old path was taken away.

---

## 5. Tests the sibling tasks should cover

**US-PM-8-1 — structural status and outcome.** Per verb: one call leaves the documented
status on disk and the documented outcome in `Store.get_run_log`; `status`/`outcome` are
absent from every verb's parameter schema; `pm_retry`/`pm_park`/`pm_review` clear the
assignee, `pm_accept` preserves it; `pm_retry` on a `done` task reopens it to `todo`.

**US-PM-8-2 — outcome cannot be omitted.** Every verb call appends exactly one run-log
entry with a non-null outcome; omitting `note`, or passing a blank one, is a pre-write
error leaving status and run log untouched; a >4096-char note is truncated rather than
rejected and the status write still lands, with the truncation fields present.

**US-PM-8-4 — backwards compatibility.** `pm_update(status="done")` with no outcome/note
still succeeds and still writes no run-log entry; `pm_done_next` keeps its signature and
its `next`/`no_next_task` shape; `pm_done_next` with no note now appends one entry carrying
the sentinel note; `pm_accept` and `pm_done_next` on equivalent inputs leave the same
on-disk state.

**Also worth covering** (§1–§2): `pm_accept` on an already-done task returns `already_done`
and does not double-log; `pm_accept` with `same_story_only=True` on the last open task
returns `story_closed` plus `no_next_task` with `next: null`; a story or epic id on any
verb is a `ToolError`, not a negative.
