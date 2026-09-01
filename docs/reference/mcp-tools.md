# MCP Tools Reference

`server.py` defines 54 tools; a default single-project install registers 41 of
them. Three families are gated behind `tools.changesets` /
`tools.maintenance` / `tools.web` in `.project/config.yaml` — off by default,
one line to turn on, nothing deleted:

- [Changeset](#changeset-tools) (5) — `tools.changesets`, which follows `hub` when unset
- [Break-glass](#break-glass-tools) (5) — `tools.maintenance`; every one reachable from the CLI
- [Web Dashboard](#web-dashboard-tools) (3) — `tools.web`

Gating the 13 removes **11,828 bytes (12.66%)** from every `tools/list` —
measured, not estimated: see
[telemetry/tool-list-size.md](../telemetry/tool-list-size.md) for the numbers,
the per-family breakdown and the command that reproduces them.

See [file-formats.md § tools](file-formats.md#tools--gated-tool-families).

## Break-glass tools

> **Off by default.** `pm_repair`, `pm_restore`, `pm_validate_branches`,
> `pm_fix_malformed` and `pm_push_all` are registered only when
> `.project/config.yaml` sets `tools.maintenance: true`. Otherwise they do
> not appear in `tools/list` and calling one returns `Unknown tool: <name>`
> with `is_error` set.
>
> These five are hidden for a different reason from the other two families.
> They are not unwanted — they are human recovery tools, and every one has a
> CLI equivalent that works whether or not the tool is registered:
> `projectman repair`, `projectman restore <filename>`,
> `projectman validate-branches`, `projectman fix-malformed <filename> --id
> ID --title T --type story|task`, and `projectman push-all [--dry-run]`.
> Each is documented in its own section below.

## Expected-negative responses

Some questions have a legitimate "no". A task that is not ready to grab, an
optional document that was never written, a commit with nothing to commit —
in each case the call did exactly what it was asked to do and the answer is
simply negative. These are **successful** responses: no `is_error`, and no
body beginning with `error:`. Genuine failures raise instead, so the two are
never confused (see `docs/reference/error-paths-inventory.md`).

All of them use one shape, so a caller branches on structure and never on
prose:

```yaml
outcome: expected_negative   # the discriminator — always this literal
status: not_ready            # machine-readable reason code, snake_case
message: task is not ready to grab   # human-readable; never parse it
blockers:                    # optional per-tool detail
  - no point estimate
  - already assigned to 'alice'
```

Branch on `status`. `outcome` lets a caller recognise an expected negative
even when it does not know the particular code.

| Tool | `status` | Meaning | Extra fields |
|---|---|---|---|
| `pm_grab` | `not_ready` | The task failed its readiness check and was not claimed | `blockers` |
| `pm_grab` | `already_claimed` | Another worker won the claim first — the task is untouched, take a different one | `holder`, `task_id` |
| `pm_release` | `not_holder` | A guarded release lost: `expected_assignee` is no longer the holder, so nothing was released | `holder`, `expected` |
| `pm_accept` | `already_done` | The task is already done — no second run-log entry, no second story close, no next grab | `task_id` |
| `pm_accept` / `pm_done_next` | `no_next_task` | The completion landed, but nothing ready follows it | `completed`, `next: null`, `next_info` |
| `pm_docs` | `not_created` | The requested document does not exist in this project | `doc`, `file` |
| `pm_commit` | `nothing_to_commit` | `.project/` is already clean — an idempotent no-op | — |

Related negatives that predate this shape use the same `status` key with the
same meaning: `pm_web_start` → `already_running`, `pm_web_stop` →
`not_running`, `pm_web_status` → `running: false`.

Note the boundary: `pm_docs("nonsense")` is *not* an expected negative.
Asking for an absent-but-valid document is a lookup over an optional set;
naming a document that does not exist at all is a bad argument, and stays an
error.

## Partial failure

The bulk write verbs — `pm_update_many` and `pm_archive_many` — touch many
items in one call, so "did it work" has more than two answers. Both obey one
contract, stated here once; their entries below link back to it, and their
docstrings say the same thing. `_bulk_result` in `src/projectman/server.py`
is the single code path that builds the shape, so the two cannot drift.

**Fail-soft per item.** A failing item is recorded and the sweep continues.
It never stops the items after it. A call over 50 items where 3 fail writes
the other 47 and reports all three failures.

**No rollback.** The items that landed stay landed. There is no transaction
and none is wanted: a caller told exactly which IDs changed can act, while a
caller handed a rollback has to guess what state it was left in.

**Call-level rejection is a different thing from item-level failure.** A
malformed *call* raises before the loop starts, so **nothing at all** is
written and `is_error` is set. Only a well-formed call reaches the per-item
stage, where a bad item is soft.

| | Rejected up front (nothing written, `is_error`) | Soft per item (`failed` entry) |
|---|---|---|
| `pm_update_many` | unknown key in an entry, entry with no `id`, `updates` not a list, no items at all, `ids` with no patch field, an entry with nothing to change, more than 250 items | unknown ID, an item whose own write is invalid (bad status value, `unassign` with an `assignee`, …) |
| `pm_archive_many` | no IDs, a **duplicate** ID, more than 250 items | unknown ID, an item whose archive fails |

The duplicate-ID rejection is `pm_archive_many`'s alone. Repeating an
idempotent patch is harmless; a list that archives the same item twice is not
the list its author thinks it is, and archiving is not something to guess
about.

**The result keys, and exactly when they are present.**

| Key | Type | Present |
|---|---|---|
| `updated` / `archived` | list of per-item objects | always (the written half) |
| `count` | int | always — `len` of that list |
| `failed` | list of `{id: str, error: str}`, **in input order** | only when ≥ 1 item failed |
| `failed_count` | int | only when ≥ 1 item failed |
| `succeeded` | list of str — the IDs that landed, **in input order** | only when ≥ 1 item failed |
| `partial` | `true` (never `false`) | only when ≥ 1 item failed |

A clean sweep carries none of the bottom four. Their **absence** is the
positive statement that every item landed, so branch on `"partial" in result`
rather than comparing `count` against the length of the list you sent.
`partial: true` also covers the all-failed sweep, which reports `count: 0`
with every ID in `failed`.

```yaml
archived:                    # 47 entries, the successes, in input order
  - {id: US-PRJ-1-1, status: done, archived: true}
  # ...
count: 47
failed:
  - {id: US-PRJ-1-9, error: 'Item not found: US-PRJ-1-9'}
  - {id: US-PRJ-1-30, error: 'Item not found: US-PRJ-1-30'}
  - {id: US-PRJ-1-88, error: 'Item not found: US-PRJ-1-88'}
failed_count: 3
succeeded: [US-PRJ-1-1, ...]   # the 47 IDs
partial: true
```

**A partial failure is not a failed call.** `is_error` is never set for one,
and the body never begins with `error:` — the same boundary the
[expected-negative responses](#expected-negative-responses) above draw. The
call did what it was asked to do; the outcome is reported per item.

**To retry**, re-issue the same call with `ids` set to the `failed` IDs only.
The successes are already durable, so re-sending them only repeats work — and
for `pm_archive_many` it would be a second archive of an already-archived
item.

## ID argument aliases

Every tool that acts on an item accepts **two spellings of its ID**: the
generic `id` and the typed one for what it acts on (`task_id`, `story_id`,
`epic_id`, `sprint_id`, `item_id`, `changeset_id`). The documented name below
is the canonical one; the marker `(alias: X)` on an ID argument means `X` is
accepted for it too. Either spelling alone is a complete call, both with the
same value is fine, and passing both with **different** values is an error —
there is no safe guess about which item you meant.

A typed name is only an alias when it names *the item the tool acts on*.
Where it names something else it is a real, separate argument and carries no
alias marker: `pm_update`'s and `pm_create_story`'s `epic_id` link a story to
an epic, and `story_id` on `pm_create_task`, `pm_create_tasks` and
`pm_fix_malformed` is the parent story.

## Query Tools

### pm_status(project?)
Get project status summary.
- **project** (optional): Project name for hub mode
- **Returns**: Epic/story/task counts, points, completion percentage, status breakdown

### pm_get(id, include_log?, fields?)
Get full details of one or more epics, stories, or tasks.
- **id**: One or more comma-separated IDs — epic (e.g. `EPIC-PRJ-1`), story (e.g. `US-PRJ-1`), or task (e.g. `US-PRJ-1-1,US-PRJ-1-2`) (alias: `task_id`). Prefer one multi-ID call over repeated single-ID calls.
- **include_log** (optional, default `false`): Include the 3 most recent run-log entries per item. Each entry carries `has_evidence` and, when true, a compact one-line `evidence_summary` (e.g. `"3 files, 1/1 tests passed, 2/2 DoD"`) — **never the evidence object itself**; `pm_get` is the high-frequency context call, and the full detail is one `pm_run_log` away.
- **fields** (optional): Comma-separated key names to return — everything else is omitted. `pm_get("US-PRJ-1-1", fields="status,assignee")` is the verification read after a worker reports done, and costs ~1.5% of the full item. Names are the item's own serialized keys (`status`, `assignee`, `points`, `title`, `story_id`, `depends_on`, `tags`, `body`, `acceptance_criteria`, `recent_run_log`, …), so each item type accepts its own; `id` is always returned so a multi-ID result stays addressable. Whitespace around names is stripped and duplicates are fine. An unknown name is a hard error listing the valid names for that item type — a typo must not silently return an empty projection that a verification read would read as a pass. `include_log=true` with a `fields` that does not name `recent_run_log` does not read the log at all. Omitting it (or passing an empty string) leaves the response byte-identical to before this parameter existed.
- **Returns**: Full frontmatter + body content. A single ID returns one object; multiple IDs return a list (missing IDs become `{id, error}` entries).

### pm_batch_get(type?, ids?, project?, brief?, fields?)
Get every item of a type (or a specific ID list) with full data in a single call.
- **type**: Item type to fetch: `"epics"`, `"stories"`, or `"tasks"`
- **ids** (optional): Comma-separated item IDs to fetch; takes precedence over `type`
- **project** (optional): Project name for hub mode
- **brief** (optional, default `false`): A fixed projection that drops the heavy free-text. Keeps whichever of `id`, `title`, `status`, `points`, `priority`, `story_id`, `epic_id`, `assignee`, `tags`, `depends_on` the item type has, and omits `body`, `acceptance_criteria` and any run log. `pm_batch_get(type="stories", brief=True)` is the scan-the-backlog call and costs a small fraction of the full listing — this is a list-*everything* tool, so full mode returns every body and every criterion in the project. Keys the type does not have are simply absent, never an error.
- **fields** (optional): Comma-separated key names to return, with exactly the semantics it has on `pm_get` — everything else is omitted, `id` is always kept, whitespace is stripped, and an unknown name is a hard error listing the valid names for that item type. Valid names are the item's own serialized keys, so a heterogeneous `ids` list must name keys every listed item has. **If both are given, `fields` wins** — explicit beats preset.
- **Returns**: Items with frontmatter and body content. Much faster than calling `pm_get` for each item individually. Omitting both `brief` and `fields` leaves the response byte-identical to before they existed. The `ids` path honours both the same way; a missing ID is still an `{id, error}` entry, but a bad field name fails the whole call rather than hiding in one entry.

### pm_docs(doc?, project?)
Read project documentation files.
- **doc** (optional): Specific doc to read — `project`, `infrastructure`, `security`, `vision`, `architecture`, `decisions`
- **project** (optional): Project name for hub mode
- **Returns**: Document content, or an expected negative `{outcome: expected_negative, status: not_created, message, doc, file}` when that document has not been created

### pm_active(project?, tag?, limit?, offset?, stale_after?)
List active/in-progress items, flagging stale claims.
- **tag** (optional): Filter items by tag
- **limit** (optional, default `20`): Max items per list
- **offset** (optional, default `0`): Starting index for pagination
- **stale_after** (optional): Hours a claim may sit before it is flagged. Omit to use the project's `stale_claim_hours` (default `2`).
- **Returns**: Active stories and in-progress tasks with totals and `has_more` pagination flag, plus [claim staleness](#claim-staleness) — `claim_age` / `claimed_by_run` / `stale: true` on each in-progress task, a `stale_tasks` id list and the `stale_after_hours` in force

### pm_search(query, project?, tag?)
Search by keyword or semantic similarity.
- **query**: Search string
- **tag** (optional): Filter results by tag
- **Returns**: Ranked results with scores

### pm_board(project?, assignee?, tag?, limit?, stale_after?)
Get the task board grouped by workflow state.
- **project** (optional): Project name for hub mode
- **assignee** (optional): Filter by assignee
- **tag** (optional): Filter tasks by tag
- **limit** (optional, default `10`): Max items per board group. Totals are always shown in the summary.
- **stale_after** (optional): Hours a claim may sit before it is flagged. Omit to use the project's `stale_claim_hours` (default `2`).
- **Returns**: Tasks grouped by `available`, `not_ready`, `in_progress`, `in_review`, `blocked` with readiness checks, suitability hints, and per-group totals. `in_progress` entries carry [claim staleness](#claim-staleness); `stale_tasks` (ids, untruncated by `limit`) and `stale_after_hours` sit beside `summary`, which keeps its five-group count shape.

### Claim staleness

`assignee` cannot answer "is anyone still working on this?" — every agent
claim is `claude`. `claimed_at` and `claimed_by_run` (see
[file-formats](file-formats.md#claim-ownership--claimed_at--claimed_by_run))
can, and `pm_active` / `pm_board` are where a caller reads them, because that
is where in-progress work is already being listed. No separate tool.

Per in-progress task, added **only when they say something**:

| Key | When present | Meaning |
|---|---|---|
| `claim_age` | `claimed_at` is known | Seconds since the claim was taken |
| `claimed_by_run` | the claim has a run id | Which run holds it |
| `stale` | and only when `true` | `claim_age` is past the threshold |

A task claimed before this metadata existed has neither `claim_age` nor
`stale`: unknown age is not old age. The threshold is `stale_claim_hours` in
`config.yaml` (default `2`), overridable per call with `stale_after`.

A stale claim is an abandoned one. Release it — `pm_release(id, note="stale
claim from a previous run")` — rather than waiting on it.

### pm_burndown(project?)
Get burndown data.
- **Returns**: Total, completed, remaining points with completion percentage

### pm_context(project?, limit?, max_doc_chars?)
Get combined hub and project context.
- **project** (optional): Project name for hub mode
- **limit** (optional, default `20`): Max epics/stories to include
- **max_doc_chars** (optional, default `4000`): Max characters per embedded doc (`0` = no limit); truncated docs point at `pm_docs` for the full text
- **Returns**: Hub vision/architecture + project docs + active epics/stories (with totals)

### pm_epic(id, project?, limit?, offset?)
Get epic details with story and task rollup.
- **id**: Epic ID (e.g. `EPIC-PRJ-1`) (alias: `epic_id`)
- **project** (optional): Project name for hub mode
- **limit** (optional, default `10`): Max stories to return per page
- **offset** (optional, default `0`): Starting index for story pagination
- **Returns**: Epic metadata, paginated linked stories/tasks, completion percentage (rollup always covers all stories), `has_more` and `next_offset` for pagination

## Write Tools

### pm_create_story(title, description, priority?, points?, epic_id?, acceptance_criteria?, tags?, project?)
Create a new user story.
- **epic_id** (optional): Link story to an epic
- **acceptance_criteria** (optional): List of acceptance criteria, one entry per criterion — e.g. `["Users can log in", "Error shown on invalid password"]`. Pass a JSON list, **not** a comma-joined string: criteria are natural language, so a comma inside one is punctuation and is never treated as a separator. A bare string is accepted and taken as exactly one criterion. Each criterion auto-generates a test task.
- **tags** (optional): Comma-separated tags
- **Returns**: Created story `id`/`title`/`status` plus any set fields, and `id`/`title` of auto-created test tasks

### pm_create_epic(title, description, priority?, target_date?, tags?, project?)
Create a new epic.
- **Returns**: Created epic metadata

### pm_create_task(story_id, title, description, points?, tags?, depends_on?, project?)
Create a task under a story.
- **tags** (optional): Comma-separated tags
- **depends_on** (optional): Comma-separated sibling task IDs
- **Returns**: Created task `id`/`title`/`story_id` plus any set fields

### pm_create_tasks(story_id, tasks, project?)
Create multiple tasks under a story in a single call.
- **story_id**: Parent story ID (e.g. `US-PRJ-1`)
- **tasks**: List of task objects, each with `title` (str), `description` (str), `points` (int, optional), `depends_on` (list[str], optional)
- **project** (optional): Project name for hub mode
- **Returns**: List of created task `id`/`title` (plus set fields), count, and total points

### pm_update(id, status?, points?, title?, assignee?, unassign?, clear?, epic_id?, body?, acceptance_criteria?, tags?, depends_on?, outcome?, note?, project?, run_id?, evidence?)
Update an epic, story, or task.
- **id**: Epic, story, or task ID (alias: `task_id`). `epic_id` is **not** an alias — it links a story to an epic.
- **assignee** (optional): Assignee name (tasks only). To remove one, pass `unassign=true` — never an empty assignee.
- **unassign** (optional, default `false`): Remove the assignee (tasks only). Changes nothing else — no status reset, no run-log entry; use `pm_release` for the whole hand-back. Passing `unassign=true` together with a non-empty `assignee` is an error.
- **clear** (optional): Comma-separated **field names** to reset to empty — e.g. `"depends_on"`, `"tags"`, `"depends_on,tags"`. Valid names and what they clear to: `assignee` → null (tasks), `depends_on` → `[]` (tasks, stories), `tags` → `[]` (epics, stories, tasks), `points` → null, `epic_id` → null (stories). Clearing an already-empty field succeeds — `clear` states a desired end state. An unknown name, a name that does not apply to this item type, or naming a field here *and* setting it in the same call is an error.
- **body** (optional): New markdown body/description content
- **acceptance_criteria** (optional): List of acceptance criteria, one entry per criterion (stories only) — e.g. `["Users can log in", "Error shown on invalid password"]`. Pass a JSON list, **not** a comma-joined string: criteria are natural language, so a comma inside one is punctuation and is never treated as a separator. A bare string is accepted and taken as exactly one criterion; an empty list clears the criteria. Editing criteria reconciles the auto-generated test tasks.
- **tags** (optional): Comma-separated tags
- **depends_on** (optional): Comma-separated sibling task IDs (tasks only)
- **outcome** (optional): Run-log outcome — `success`, `partial`, `blocked`, `failed`, or `info`. When provided, appends a run-log entry for tracking work attempts.
- **note** (optional): Run-log note describing what was accomplished or blocked. Notes longer than 4096 characters are truncated server-side with a visible `...[truncated N chars]` marker rather than rejected, so the status/outcome write always lands. Defaults outcome to `info` if outcome is omitted.
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- Passing `evidence` alone — with neither `outcome` nor `note` — still appends an entry (`outcome: info`, empty note).
- **run_id** (optional): Opaque id of the orchestrator run making this edit, stamped on the activity-log event so [`pm_activity(run_id=...)`](#pm_activityitem_id-event_type-from_date-to_date-actor-run_id-limit-offset-project) returns it beside that run's claims and verdicts. Never written to frontmatter, and never a claim — use `pm_grab` for that. Omit on ordinary edits: they belong to no run.
- Epic status values: `draft`, `active`, `done`, `archived`
- Story status values: `backlog`, `ready`, `active`, `done`, `archived`
- Task status values: `todo`, `in-progress`, `review`, `done`, `blocked`
- **Returns**: `id`, current `status`, and the fields changed by this call (plus `run_log: <outcome>` when a run-log entry was appended) — not the full object
- When — and only when — a supplied note had to be truncated, the response also carries `note_truncated: true`, `note_original_length`, `note_stored_length`, `note_dropped_chars` and `note_limit`, so a caller detects truncation without string-matching. Absence of the fields means the note was stored whole. Every note-writing tool (`pm_update`, `pm_release`, `pm_done_next`, `pm_accept`, `pm_retry`, `pm_park`, `pm_review`) reports it the same way.
- When — and only when — an `evidence` cap actually fired, the response also carries `evidence_clamped: true` and `evidence_dropped` (see [Structured evidence](#structured-evidence)).

### pm_update_many(ids?, updates?, status?, points?, title?, assignee?, unassign?, clear?, body?, tags?, depends_on?, outcome?, note?, run_id?, evidence?, project?)
Update many items in one call — the bulk form of `pm_update`, shaped like `pm_create_tasks`. Every field means exactly what it means on `pm_update`, and the same code performs each item's write, so nothing behaves differently for being in a batch.
- **ids** (optional): Comma-separated item IDs the uniform patch applies to (e.g. `"US-PRJ-1-1,US-PRJ-1-2"`). Epics, stories and tasks may be mixed. Passing `ids` with no patch field is an error.
- **updates** (optional): Per-item patches — a list of objects, each with `id` (alias: `task_id`) plus any of `status`, `points`, `title`, `assignee`, `unassign`, `clear`, `epic_id`, `body`, `acceptance_criteria`, `tags`, `depends_on`, `outcome`, `note`, `evidence`. An unknown key is an error naming the valid ones, raised **before** anything is written.
- Top-level patch fields given alongside `updates` are defaults each entry may override — e.g. `updates=[{"id": "a", "note": "..."}, ...], status="done", outcome="success"` is one status flip with per-item notes.
- Up to 250 items per call.
- **run_id** (optional): Stamped on every activity-log event this call emits, exactly as on `pm_update`. A property of the whole call, like `project` — not a per-item field inside `updates`.
- **Returns**: `updated:` — one entry per item written, each shaped like `pm_update`'s `updated` block and carrying that item's own extras (`note_truncated`, `test_tasks`, ...) — plus `count`.
- On partial failure the response also carries `failed:` (each with `id` and `error`), `failed_count`, `succeeded:` (the IDs that landed) and `partial: true`. A failing item never stops the ones after it and nothing already written is rolled back; a malformed *call* (unknown key, missing `id`, no items, nothing to change, over 250) is rejected up front, before any write. The full contract — key types, presence rules, why `is_error` stays unset, how to retry — is [Partial failure](#partial-failure) above, and it is identical for `pm_archive_many`.
- Prefer this over a run of single `pm_update` calls: a long tail of identical writes reads as runaway behaviour, while one declared call with an explicit ID list is one reviewable intent.

### pm_archive(id)
Archive an epic, story, or task.
- **id**: Epic, story, or task ID to archive (alias: `task_id`)
- Archiving more than one item? Use `pm_archive_many` — one declared call, not a run of these.

### pm_archive_many(ids, project?)
Archive many items in one call, from an explicit ID list — the bulk form of `pm_archive`, shaped like `pm_update_many`. The same code performs each item's write, so nothing behaves differently for being in a batch.
- **ids**: Comma-separated item IDs to archive (e.g. `"US-PRJ-1-1,US-PRJ-1-2"`). Epics, stories and tasks may be mixed.
- The list is the whole input — there is **no criteria or sweep form** and no default. This tool never decides for itself what to archive, so what it touches is exactly what the caller wrote down. An empty list is an error, never a no-op, and a duplicate ID is rejected before any write.
- Up to 250 items per call.
- **Returns**: `archived:` — one entry per item written, each with `id`, the `status` it ends up with and `archived: true` — plus `count`. A task keeps the status the work really reached (archiving sets an orthogonal flag); epics and stories move to `archived`.
- On partial failure the response also carries `failed:` (each with `id` and `error`), `failed_count`, `succeeded:` (the IDs that landed) and `partial: true` — the same keys `pm_update_many` uses. A failing item never stops the ones after it and the archives that landed are not rolled back; a malformed *call* (no IDs, a duplicate ID, more than 250 items) is rejected up front, before any write. The full contract — key types, presence rules, why `is_error` stays unset, how to retry — is [Partial failure](#partial-failure) above, and it is identical for `pm_update_many` apart from the duplicate-ID rejection, which is this verb's alone.
- Prefer this over a run of single `pm_archive` calls: a long tail of identical destructive writes reads as runaway behaviour and has been denied mid-sweep by permission tooling, while one declared call with an explicit ID list is one reviewable intent.

### pm_grab(task_id, assignee?, include_story?, run_id?, fields?)
Claim a task with readiness validation.
- **task_id**: Task ID to claim (e.g. `US-PRJ-1-1`) (alias: `id`)
- Sets assignee and status to `in-progress`
- Validates task readiness before claiming
- Claims by compare-and-swap on the on-disk assignee and status, under an exclusive lock on the task file — two concurrent workers cannot both win. The winner's response shape is unchanged; the loser gets `{outcome: expected_negative, status: already_claimed, message, holder, task_id}` and the task is left untouched. Re-claiming a task you already hold still succeeds.
- Loads task context for implementation
- **include_story** (optional, default `true`): Include the parent story body. Pass `false` when the story context is already known (e.g. grabbing a second task from the same story).
- **run_id** (optional): Opaque id of the run making the claim, written to the task as `claimed_by_run` and stamped on the activity-log event. Use a value stable across one orchestrator run and different across runs, so a restarted run can ask `pm_activity` what its predecessor claimed. Omit and the MCP server's own per-process id is used — every claim has an owner either way. A win also records `claimed_at`; re-claiming your own task under the **same** `run_id` leaves that timestamp alone, so a claim's age keeps running.
- **fields** (optional): Comma-separated key names to return. A name is either a key of the task (`status`, `assignee`, `points`, `title`, `story_id`, `depends_on`, …) or a whole top-level section (`body`, `story_context`, `sibling_tasks`, `sibling_tasks_total`, `sibling_tasks_done`, `dependency_status`, `warnings`, or `task` for the whole task). Named sections come back whole, unnamed ones are dropped, and the `task` dict is projected to the named task keys plus `id` — so `fields="status,assignee"` returns `grabbed: {task: {id, status, assignee}}` and nothing else, ~1.4% of the full payload. Projection is **output-only**: the claim (status write, assignee, index, event) is identical either way, and expected negatives (`already_claimed`, `not_ready`) are returned in full because their `holder` / `blockers` detail is the recovery path. Unknown names are a hard error listing the valid ones. Omit it for the full payload — the default is unchanged.
- **Returns**: Task details and context — task frontmatter + body, story context, unfinished sibling tasks (with `sibling_tasks_total` / `sibling_tasks_done` counts), dependency status, readiness warnings. Returns an expected negative `{outcome: expected_negative, status: not_ready, message, blockers}` when the readiness check fails (the task is left untouched).

### pm_release(task_id, status?, note?, outcome?, expected_assignee?, project?, run_id?)
Release a task — hand it back to the pool. The exact inverse of `pm_grab`, and the form to use whenever a task must stop being someone's: `pm_release("US-PRJ-1-1", note="worker stopped before finishing")`.
- **task_id**: Task ID to release (alias: `id`). Tasks only — a story or epic id is an error, since `assignee` is a task-only field.
- Clears the assignee **and the claim metadata** (`claimed_at`, `claimed_by_run`), sets the status, and appends a run-log entry — one call, no empty values anywhere. There is no `assignee` parameter: releasing is said by the verb.
- **run_id** (optional): Stamped on the activity-log event. Omit and the run recorded in the task's own `claimed_by_run` is used, so a release is attributed to the claim it ends.
- **status** (optional, default `todo`): Status to leave the task in
- **note** / **outcome** (optional): Run-log entry, appended only when one of them is given; `outcome` defaults to `info`
- **expected_assignee** (optional): Release only if this name still holds the task. Omit for an unguarded release. A mismatch is an expected negative (`status: not_holder`) and the task is left untouched.
- Releasing an already-unassigned task **succeeds**, with `from_assignee: null` — a cleanup loop never has to branch on it.
- **Returns**: `released:` with the full `task` and `from_assignee` (who held it before the call, or null), plus the `note_truncated` fields when the note had to be truncated (see `pm_update`)

### pm_done_next(task_id, outcome?, note?, assignee?, same_story_only?, run_id?, evidence?)
Complete a task and claim the next ready one in a single call — the loop primitive for working through tasks.
`pm_accept` is the same call with the verdict said by the verb. This spelling stays supported forever and is not deprecated.
- **task_id**: Task ID just finished (e.g. `US-PRJ-1-1`) (alias: `id`)
- Marks `task_id` done and **always** appends a run-log entry (`outcome` defaults to `success`). When no `note` is given (or a blank one is passed) a fixed placeholder — `completed via pm_done_next (no note given)` — is logged instead, so a completion is never silently unlogged; prefer `pm_accept`, which requires a real note.
- Closes the parent story automatically if this was its last open task (`story_closed` in the response)
- Grabs the next ready unassigned task — same-story siblings first (topological order), then other stories by priority. The story body is only included when the next task belongs to a different story.
- **same_story_only** (optional, default `false`): Stop instead of crossing to another story
- **run_id** (optional): Opaque id of this orchestrator run — recorded as `claimed_by_run` on the task claimed as `next`, and stamped on the activity-log events. Omit and the server's per-process id is used.
- The completed task keeps its `assignee` but has `claimed_at` / `claimed_by_run` cleared: the claim is over, and only a claim in force can go stale.
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- **Returns**: `completed` summary, optional `story_closed`, and `next` (a full grab payload). When nothing is ready the response is an expected negative — `{outcome: expected_negative, status: no_next_task, message, completed, next: null, next_info}` — the task was still completed; only the second half of the question has no answer. The `note_truncated` fields (see `pm_update`) are present on both shapes when the note had to be truncated.

### The verdict verbs — pm_accept / pm_retry / pm_park / pm_review

The four terminal moves an orchestrator can make on a finished attempt, one
verb each. **`status` and `outcome` are not parameters**: there is no way to
call `pm_park` and get `success`, nor to reach `done` without `success`. The
`note` is **required** on all four and must be non-blank — it is the whole
mechanism behind "a completion cannot land without a run-log entry", since a
fixed outcome plus a required note makes the entry structurally unavoidable.
An omitted note is rejected by the schema before anything is written; a blank
one is an error for the same reason. See
`docs/reference/verdict-verbs-contract.md`.

| Verb | Verdict | status | outcome | assignee | claim metadata |
|---|---|---|---|---|---|
| `pm_accept` | Accept | `done` | `success` | **kept** (a done task records who did it) | cleared |
| `pm_retry` | Retry | `todo` | `failed` | cleared | cleared |
| `pm_park` | Park | `review` | `blocked` | cleared | cleared |
| `pm_review` | Accept-as-review | `review` | `partial` | cleared | cleared |

All four clear `claimed_at` / `claimed_by_run`: the claim is no longer in
force, and left behind it would age every finished task into a phantom stale
claim. Their activity-log events are attributed to the run named in the task's
own `claimed_by_run`, so none of the three releasing verbs needs a `run_id`
parameter.

`pm_retry`, `pm_park` and `pm_review` accept **any** starting status,
including `done` — the common case is precisely a worker that self-reported
done and failed validation. Only `pm_accept` guards. All four are tasks-only:
a story or epic id is an error, not an expected negative.

`pm_update(id, status=...)` keeps working exactly as before, including
`status="done"` with no outcome or note. It is the generic escape hatch; the
verdict verbs are purely additive.

All four also take the optional `evidence` object — see
[Structured evidence](#structured-evidence). In practice `pm_accept` and
`pm_review` are where evidence exists, and `pm_retry`/`pm_park` carry the
failing `tests` entries that justify the verdict.

### pm_accept(task_id, note, next_task?, same_story_only?, assignee?, project?, run_id?, evidence?)
Accept a task's work — mark it done, log why, and claim the next one. The
same call as `pm_done_next` with the verdict said by the verb, so it is the
form to use in an orchestrator loop: `pm_accept("US-PRJ-1-1", note="all DoD items met; 47 tests pass")`.
- **task_id**: Task ID being accepted (alias: `id`). Tasks only.
- **note** (**required**): Run-log note saying what was delivered. Blank is an error; over 4096 characters is truncated server-side, never rejected.
- Always writes `status: done` + `outcome: success` + the note, so a run-log entry is unavoidable. The assignee is **kept**; `claimed_at` / `claimed_by_run` are cleared.
- **run_id** (optional): Opaque id of this orchestrator run — recorded as `claimed_by_run` on the task claimed as `next`, and stamped on the activity-log events.
- Closes the parent story automatically if this was its last open task (`story_closed` in the response)
- **next_task** (optional, default `true`): Also claim the next ready task. With `false` the `next` key is absent entirely.
- **same_story_only** (optional, default `true`): Only take a next task from the same story
- **assignee** (optional, default `claude`): Who claims the next task
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- Accepting an already-done task is an expected negative (`status: already_done`) — nothing is written twice.
- **Returns**: `completed` (with `id`, `status`, `run_log`), optional `story_closed`, and `next` (a full grab payload). When nothing is ready to follow, an expected negative `{outcome: expected_negative, status: no_next_task, message, completed, next: null, next_info}` — the completion still landed. Plus the `note_truncated` fields (see `pm_update`) when the note had to be truncated.

### pm_retry(task_id, note, project?, evidence?)
Retry a task — the attempt failed, hand it back to the pool for another go.
- **task_id**: Task ID to retry (alias: `id`). Tasks only.
- **note** (**required**): Run-log note saying what failed, so the next worker inherits the reason
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- Always writes `status: todo` + `outcome: failed`, and clears the assignee
- **Returns**: `retried:` with the full `task`, `from_status` and `from_assignee`, plus the `note_truncated` fields (see `pm_update`) when the note had to be truncated

### pm_park(task_id, note, project?, evidence?)
Park a task — it is blocked on something a human has to resolve.
- **task_id**: Task ID to park (alias: `id`). Tasks only.
- **note** (**required**): Run-log note saying what it is blocked on — the whole handover to whoever unblocks it
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- Always writes `status: review` + `outcome: blocked`, and clears the assignee so it does not sit stale
- **Returns**: `parked:` with the full `task`, `from_status` and `from_assignee`, plus the `note_truncated` fields (see `pm_update`) when the note had to be truncated

### pm_review(task_id, note, project?, evidence?)
Send a task to review — the work partly landed and a human should look. The
middle answer between `pm_accept` and `pm_retry`.
- **task_id**: Task ID to send to review (alias: `id`). Tasks only.
- **note** (**required**): Run-log note saying what landed and what did not
- **evidence** (optional): Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (`{command, passed, summary?}` objects), `dod_met` and `dod_unmet`. **Lists go here, never in the note**; the note stays a one-line human summary. See [Structured evidence](#structured-evidence) below.
- Always writes `status: review` + `outcome: partial`, and clears the assignee. `partial` is the outcome the vocabulary keeps losing — ~90% of run-log entries say `success` — and this verb is how it gets said.
- **Returns**: `reviewed:` with the full `task`, `from_status` and `from_assignee`, plus the `note_truncated` fields (see `pm_update`) when the note had to be truncated

### pm_update_doc(doc, content, project?)
Update a project documentation file.
- **doc**: Document name — `project`, `infrastructure`, `security`, `vision`, `architecture`, `decisions`
- **content**: New document content
- **project** (optional): Project name for hub mode

## Sprint Tools

### pm_create_sprint(name, goal?, start_date?, end_date?, planned_stories?, project?)
Create a sprint with a name, goal, dates, and planned stories.
- **name**: Sprint name (e.g. `Sprint 1 — Auth & Onboarding`)
- **goal** (optional): Sprint goal summary
- **start_date** / **end_date** (optional): Dates in `YYYY-MM-DD` format
- **planned_stories** (optional): Comma-separated story IDs (e.g. `US-PRJ-1,US-PRJ-2`)
- **Returns**: Created sprint metadata, plus `dependency_warnings` if any planned story has unmet dependencies external to the sprint

### pm_get_sprint(sprint_id, project?)
View sprint details with live progress per story.
- **sprint_id**: Sprint ID (e.g. `SPRINT-PRJ-1`) (alias: `id`)
- **Returns**: Sprint metadata plus per-story rollup (task counts, points completed vs. remaining)

### pm_list_sprints(status?, project?, brief?, fields?)
List sprints, optionally filtered by status.
- **status** (optional): Filter by `planning`, `active`, `completed`, or `cancelled`
- **brief** (optional, default `false`): A fixed projection that drops the free-text. Keeps `id`, `name`, `status`, `start_date`, `end_date`, `planned_points`, `completed_points` and `planned_stories`, and omits `goal` — which on a long history is most of the payload by weight. `pm_list_sprints(status="completed", brief=True)` is the scan-the-history call.
- **fields** (optional): Comma-separated key names to return, with the same semantics as on `pm_get` — everything else is omitted, `id` is always kept, and an unknown name is a hard error listing the valid sprint keys. **If both are given, `fields` wins** — explicit beats preset.
- **Returns**: `sprints` (with name, status, goal, and dates) and `count`. `count` is present in every mode, and omitting both `brief` and `fields` leaves the response byte-identical to before they existed.

### pm_update_sprint(sprint_id, name?, status?, goal?, start_date?, end_date?, planned_stories?, run_id?, project?)
Update sprint fields (status, stories, dates, etc.).
- **sprint_id**: Sprint ID (alias: `id`)
- **status** (optional): New status — `planning`, `active`, `completed`, or `cancelled`
- **planned_stories** (optional): Comma-separated story IDs (replaces the planned set)
- **run_id** (optional): Opaque id of the orchestrator run closing (or otherwise editing) the sprint, stamped on the activity-log event so the close appears in `pm_activity(run_id=...)` beside that run's claims and verdicts. Not a sprint field.
- **Returns**: Updated sprint metadata, plus `dependency_warnings` if newly planned stories have unmet dependencies

## Intelligence Tools

### pm_estimate(id)
Get estimation context with calibration guidelines.
- **id**: Story or task ID to estimate (alias: `task_id`)

### pm_scope(id)
Get scoping context for story decomposition.
- **id**: Story ID to scope into tasks (alias: `story_id`)

### pm_auto_scope(mode?, project?, limit?, offset?)
Discover what needs scoping — returns codebase signals or undecomposed stories.
- **mode** (optional): `"full"` for codebase scan (new projects) or `"incremental"` for scoping existing stories. Auto-detected if omitted.
- **project** (optional): Project name for hub mode
- **limit** (optional, default `5`): Max stories per batch in incremental mode
- **offset** (optional, default `0`): Starting index for pagination in incremental mode
- **Returns**: Full scan returns documentation, build files, source tree, and creation guidance. Incremental returns a paginated batch of undecomposed story IDs/titles with `has_more` and `next_offset` for pagination.

### pm_audit(include_info?, project?, since?)
Run project audit for drift detection. Performs 18 checks covering stories, tasks, epics, documentation, hub docs, assignments, dependencies, malformed files, and completion evidence.
- Findings include `done-without-evidence` (warning): one aggregate finding listing every non-archived `done` task whose run log carries no entry with structured `evidence`. A done task with no run log at all qualifies; an `evidence` object with all lists empty does not (presence, never truthiness). It is a warning, not an error, so it never halts an orchestrator run — every task completed before evidence shipped trips it. Use `pm_run_log(id, has_evidence=false)` to see the evidence-less entries for one item.
- **include_info** (optional, default `false`): Include info-level findings in the response. By default only errors and warnings are returned, with omitted info findings summarized as a count. The full report is always written to `DRIFT.md`.
- Every report starts with a `digest: <16 hex chars>` line, immediately after the `# Project Audit Report` title and before the `**Errors:** …` counts. It is a fixed-width fingerprint of everything the audit reads — item files, `config.yaml`, project and hub docs, `malformed/`, `logs/*.jsonl`, sprints, indexes — hashed by content, so two calls with no writes between them return the same digest and any change to audit inputs returns a different one. The same digest appears in the default response, the `include_info` response, and `DRIFT.md`. Audit output and caches (`DRIFT.md` itself, `embeddings.db`) are excluded, so an audit never invalidates its own answer. Keep the digest between polls to tell an unchanged project from a changed one without diffing reports.
- **since** (optional): A digest from a previous `pm_audit` call. If it matches the current digest, the tool answers in under 100 bytes — `digest: <hex>`, `unchanged: true`, and `errors: N | warnings: M` from the last report — without running a single check and without rewriting `DRIFT.md`. If it differs, is absent, is stale, or is malformed, the full audit runs exactly as it otherwise would; an unusable `since` is never an error.
- **Why `since` does not weaken the health check**: the digest is a content hash of everything the audit reads, so any state change that could produce a new finding necessarily changes the digest. A matching digest therefore means byte-identical inputs, which means identical findings — a new ERROR-level finding cannot hide behind a short-circuit. The hash is deliberately over-sensitive: an unrelated write costs one extra full report, whereas under-sensitivity would hide a real finding. Orchestrators should keep polling on their normal cadence and simply pass the last digest as `since`.

### pm_reindex(project?)
Rebuild project index and embeddings.

### pm_repair()
> Break-glass — off the tool list unless `tools.maintenance: true`. CLI: `projectman repair`.

Scan the hub for unregistered projects, initialize missing PM data directories (`.project/projects/{name}/`), rebuild all indexes and embeddings, and regenerate dashboards. Hub mode only. Writes a `REPAIR.md` report.

## Web Dashboard Tools

> **Off by default.** These three tools are registered only when
> `.project/config.yaml` sets `tools.web: true`. Otherwise they do not appear
> in `tools/list` and calling one returns `Unknown tool: <name>` with
> `is_error` set. See [file-formats.md § tools](file-formats.md#tools--gated-tool-families).
> The dashboard itself is unaffected — `projectman web` still starts it from
> the CLI.

### pm_web_start(host?, port?)
Start the ProjectMan web dashboard as a background server.
- **host** (optional, default `127.0.0.1`): Host/IP to bind to. Use `0.0.0.0` to listen on all interfaces.
- **port** (optional, default `8000`): Port to listen on. If the port is in use, the tool returns an error with a suggestion to try the next port.
- **Returns**: `{status, url, pid}` on success, or `{status: "error", error, suggestion}` if the port is taken
- **Requires**: `web` extra (`pip install projectman[web]`)

### pm_web_stop()
Stop the running ProjectMan web server.
- **Returns**: `{status: "stopped", pid}` or `{status: "not_running"}`

### pm_web_status()
Check if the web server is running.
- **Returns**: `{running, url, pid, host, port}` if running, or `{running: false}` if not

## Malformed File Tools

### pm_malformed(project?)
Get the next malformed file from quarantine.
- **Returns**: File content and metadata for the next malformed file, one at a time

### pm_fix_malformed(filename, id, title, item_type, body?, status?, priority?, points?, story_id?, project?)
> Break-glass — off the tool list unless `tools.maintenance: true`. CLI:
> `projectman fix-malformed <filename> --id ID --title T --type story|task
> [--body B] [--status S] [--priority P] [--points N] [--story-id SID] [--project NAME]`.

Fix a malformed file by providing corrected metadata.
- **filename**: Name of the malformed file
- **id**: Corrected ID
- **title**: Corrected title
- **item_type**: `story` or `task`
- **body** (optional): Corrected body content
- **status** (optional): Corrected status
- **priority** (optional): Corrected priority (stories only)
- **points** (optional): Corrected points
- **story_id** (optional): Parent story ID (tasks only)
- **Returns**: Fixed file metadata

### pm_restore(filename, project?)
> Break-glass — off the tool list unless `tools.maintenance: true`. CLI:
> `projectman restore <filename> [--project NAME]`.

Restore a malformed file back to its original location without fixes.
- **filename**: Name of the malformed file
- **Returns**: Restored file path

## Git & Push Tools

### pm_git_status(project?)
Get git status of all hub submodules.
- **project** (optional): Project name for hub mode
- **Returns**: Per-project branch, dirty state, ahead/behind counts, and open PRs

### pm_commit(scope?, message?)
Commit `.project/` changes.
- **scope** (optional, default `"all"`): `"hub"`, `"project:<name>"`, or `"all"`
- **message** (optional): Commit message (auto-generated if omitted)
- **Returns**: Commit hash and committed-file count (the message is echoed only when auto-generated), or an expected negative `{outcome: expected_negative, status: nothing_to_commit, message}` when there is nothing to commit

### pm_push(scope?)
Push committed changes to remote.
- **scope** (optional, default `"hub"`): `"hub"`, `"project:<name>"`, or `"all"`
- **Returns**: Push result

### pm_push_all(dry_run?, projects?)
> Break-glass — off the tool list unless `tools.maintenance: true`. CLI:
> `projectman push-all [--dry-run] [--projects a,b]`.

Coordinated push: preflight checks, push subprojects, then push hub.
- **dry_run** (optional, default `false`): Preview what would be pushed without pushing
- **projects** (optional): Comma-separated project names (auto-discovers dirty projects if omitted)
- **Returns**: Per-project push results with preflight status

### pm_validate_branches()
> Break-glass — off the tool list unless `tools.maintenance: true`. CLI: `projectman validate-branches`.

Validate that hub submodule branches match their configured tracking branches.
- **Returns**: Per-project branch validation results

## Changeset Tools

> **Off by default outside hub mode.** These five tools are registered when
> `.project/config.yaml` sets `tools.changesets: true`, and — because a
> changeset spans several projects — automatically in hub mode unless
> `tools.changesets: false` says otherwise. When hidden they do not appear in
> `tools/list` and calling one returns `Unknown tool: <name>` with `is_error`
> set. See [file-formats.md § tools](file-formats.md#tools--gated-tool-families).
> The CLI is unaffected either way — `projectman changeset create/add-project/status`
> works whether or not the tools are registered.

### pm_changeset_create(title, projects, description?, project?)
Create a changeset to coordinate multi-project changes.
- **title**: Changeset title
- **projects**: Comma-separated project names
- **description** (optional): Changeset description
- **Returns**: Created changeset metadata

### pm_changeset_status(changeset_id?, project?)
Get changeset details or list all changesets.
- **changeset_id** (optional): Specific changeset ID. Omit to list all. (alias: `id`)
- **Returns**: Changeset metadata and entry statuses

### pm_changeset_add_project(name, changeset_id, ref?, project?)
Add a project entry to an existing changeset.
- **name**: Project name to add
- **changeset_id**: Changeset ID (e.g. `CS-PRJ-1`) (alias: `id`)
- **ref** (optional): Git branch/ref for this project's changes
- **Returns**: Updated changeset metadata

### pm_changeset_create_prs(changeset_id, project?)
Generate `gh` CLI commands for creating cross-referenced PRs.
- **changeset_id**: Changeset ID (alias: `id`)
- **Returns**: `changeset`, `title`, and `pr_commands` — one entry per project. An entry with a ref carries `project`, `ref`, `argv` and `command`; an entry without a ref carries `project` and `status` ("skipped — no ref/branch set") only.
- **argv**: the `gh pr create` invocation as a list of arguments (`["gh", "pr", "create", "--title", …, "--body", …, "--head", ref]`). Execute this form directly — `subprocess.run(argv, cwd=project)` — never a shell string.
- **command**: the same invocation rendered for a human to read/paste, built with `shlex.quote`/`shlex.join`: `cd <project> && gh pr create …`. Titles, bodies and refs containing `"`, `'`, backticks, `$(…)`, `;`, `&&`, `|` or newlines are quoted, so `shlex.split(command)` always round-trips to `["cd", project, "&&", *argv]`.
- The PR body uses real newlines, so the cross-reference list renders as separate lines on GitHub.
- **NUL bytes are rejected, not rendered.** If the changeset id, title, description, a project name or a ref contains a NUL byte (`0x00`), the call raises `ValueError: changeset <id> <field> contains a NUL byte (0x00), which cannot be carried in a command argument; remove it from the changeset before generating PR commands`. No argv element can carry a NUL — `execve` arguments are NUL-terminated, `subprocess.run` raises `embedded null byte`, and a shell truncates the argument there — so a rendered `command` would differ from what actually executes. The error names the offending field rather than handing back an unrunnable command.

The commands are **not** executed — review them, then run them yourself.

### pm_changeset_push(changeset_id, project?)
Check PR merge status and update changeset status.
- **changeset_id**: Changeset ID (alias: `id`)
- **Returns**: Per-entry merge status, overall changeset status, `needs_review` flag

## Run Log

### pm_run_log(id, limit?, offset?, project?, has_evidence?)
Read the run log for an epic, story, or task — shows previous work attempts, outcomes, and notes.
- **id**: Epic, story, or task ID (alias: `task_id`)
- **limit** (optional, default `20`): Max entries to return (most recent first)
- **offset** (optional, default `0`): Starting index for pagination
- **has_evidence** (optional): Filter by structured evidence — `true` returns only entries carrying an `evidence` object, `false` only those without, omitted returns everything. This makes "did this completion prove anything" a one-call question. The filter is applied **before** `limit`/`offset`.
- **Returns**: JSON array of log entries, each with `timestamp`, `outcome`, `status`, `note`, `actor`, and `evidence` **verbatim** when the entry has one. The `evidence` key is omitted entirely when absent, so an entry without evidence is byte-for-byte the response it always was.

Run-log entries are created by passing `outcome`, `note` and/or `evidence` to `pm_update` or to any of the verdict verbs. Stored as JSONL in `.project/logs/{item_id}.jsonl`.

### Structured evidence

`docs/reference/evidence-contract.md` is the binding design. The rule:
**the note says what happened; the evidence says what proves it — prose is
never the container for a list.**

`evidence` is an optional trailing object parameter on the six tools that can
append a run-log entry: `pm_accept`, `pm_review`, `pm_retry`, `pm_park`,
`pm_update` and `pm_done_next`.

```json
{"files": ["src/projectman/store.py", "tests/test_store.py"],
 "tests": [{"command": "uv run pytest tests/test_store.py",
            "passed": true, "summary": "47 passed"}],
 "dod_met": ["evidence stored on entry", "old lines still parse"],
 "dod_unmet": []}
```

| Field | Shape | Cap |
|---|---|---|
| `files` | list of paths changed | ≤ 40 items, each ≤ 160 chars |
| `tests` | list of `{command, passed, summary?}` | ≤ 10 items, strings ≤ 160 chars |
| `dod_met` | list of criteria evidenced | ≤ 20 items, each ≤ 160 chars |
| `dod_unmet` | list of criteria still outstanding | ≤ 20 items, each ≤ 160 chars |

- **Caps clamp, never reject.** An over-long list keeps its **first** N
  entries and an over-long string is cut to 160 characters; the status/outcome
  write always lands. When a clamp fires the response carries
  `evidence_clamped: true` and `evidence_dropped` — items dropped per list,
  plus `chars` for characters cut from over-long strings. Absence of both
  fields means the evidence was stored whole.
- **`note` is unchanged** — still required on the four verdict verbs, still
  capped at 4096 characters. Its *recommended* length is now one line, ≤ 200
  characters: when evidence is present and the note exceeds that, the response
  carries `note_long: true`, `note_length` and `note_recommended`. Advisory
  only — never an error, never extra truncation.
- **Present-but-empty is evidence.** `{}` — four empty lists — explicitly says
  "nothing to show", which is the genuinely non-code task. *Absent* evidence
  is the gap, so `has_evidence` tests presence, never truthiness.
- **Backwards compatible.** Every pre-existing `.jsonl` line parses to
  `evidence: null` with no migration and no version marker, and an entry
  written without evidence has no `evidence` key on disk at all.

## Activity Log

### pm_activity(item_id?, event_type?, from_date?, to_date?, actor?, run_id?, limit?, offset?, project?)
Query the activity log with filtering and pagination.
- **item_id** (optional): Filter by item ID (alias: `id`)
- **event_type** (optional): Filter by event type (`create`, `update`, `delete`, `archive`)
- **from_date** (optional): Start date filter (ISO format)
- **to_date** (optional): End date filter (ISO format)
- **actor** (optional): Filter by actor name
- **run_id** (optional): Filter to the events **one orchestrator run** produced. `actor` is the same string for every run of every agent on a machine, so it is this — and only this — that answers "what did *this* run do". Everything a run needs for its final report is in the filtered slice: the claims it took (`pm_grab`), the claims it took *back* (`claimed_by_run: <old> → <this run>`), its releases, its verdicts (`pm_accept` / `pm_retry` / `pm_park` / `pm_review`), the **story closures those verdicts triggered** — `pm_accept` stamps the close with the run that caused it — and any `pm_update`, `pm_update_many` or `pm_update_sprint` the caller tagged with the same `run_id`. Ordinary untagged edits carry no run id and never match. This is how `/pm-orchestrate` Phase 4 rebuilds its report from the log instead of from memory, and how a restarted run reconstructs its predecessor's.
- **limit** (optional, default `20`): Max entries to return
- **offset** (optional, default `0`): Starting index for pagination
- **Returns**: `total`, `showing`, `has_more` and `entries` — formatted log entries, most recent first. Claim, release and verdict events additionally render `run <run_id>` after the actor, and carry the `claimed_at` / `claimed_by_run` before/after pair in their changes — `actor` alone cannot separate one orchestrator run from the next, so that is what a run reads to find the claims it left behind.
- **`has_more`** is `true` when entries remain past this page. Page with `offset` until it is `false`: a report rebuilt from a silently truncated first page is a wrong report, which is precisely the failure the `run_id` filter exists to prevent.
