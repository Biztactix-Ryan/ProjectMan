# MCP Tools Reference

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
| `pm_docs` | `not_created` | The requested document does not exist in this project | `doc`, `file` |
| `pm_commit` | `nothing_to_commit` | `.project/` is already clean — an idempotent no-op | — |

Related negatives that predate this shape use the same `status` key with the
same meaning: `pm_web_start` → `already_running`, `pm_web_stop` →
`not_running`, `pm_web_status` → `running: false`.

Note the boundary: `pm_docs("nonsense")` is *not* an expected negative.
Asking for an absent-but-valid document is a lookup over an optional set;
naming a document that does not exist at all is a bad argument, and stays an
error.

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

### pm_get(id, include_log?)
Get full details of one or more epics, stories, or tasks.
- **id**: One or more comma-separated IDs — epic (e.g. `EPIC-PRJ-1`), story (e.g. `US-PRJ-1`), or task (e.g. `US-PRJ-1-1,US-PRJ-1-2`) (alias: `task_id`). Prefer one multi-ID call over repeated single-ID calls.
- **include_log** (optional, default `false`): Include the 3 most recent run-log entries per item
- **Returns**: Full frontmatter + body content. A single ID returns one object; multiple IDs return a list (missing IDs become `{id, error}` entries).

### pm_batch_get(type?, ids?, project?)
Get every item of a type (or a specific ID list) with full data in a single call.
- **type**: Item type to fetch: `"epics"`, `"stories"`, or `"tasks"`
- **ids** (optional): Comma-separated item IDs to fetch; takes precedence over `type`
- **project** (optional): Project name for hub mode
- **Returns**: Items with frontmatter and body content. Much faster than calling `pm_get` for each item individually.

### pm_docs(doc?, project?)
Read project documentation files.
- **doc** (optional): Specific doc to read — `project`, `infrastructure`, `security`, `vision`, `architecture`, `decisions`
- **project** (optional): Project name for hub mode
- **Returns**: Document content, or an expected negative `{outcome: expected_negative, status: not_created, message, doc, file}` when that document has not been created

### pm_active(project?, tag?, limit?, offset?)
List active/in-progress items.
- **tag** (optional): Filter items by tag
- **limit** (optional, default `20`): Max items per list
- **offset** (optional, default `0`): Starting index for pagination
- **Returns**: Active stories and in-progress tasks with totals and `has_more` pagination flag

### pm_search(query, project?, tag?)
Search by keyword or semantic similarity.
- **query**: Search string
- **tag** (optional): Filter results by tag
- **Returns**: Ranked results with scores

### pm_board(project?, assignee?, tag?, limit?)
Get the task board grouped by workflow state.
- **project** (optional): Project name for hub mode
- **assignee** (optional): Filter by assignee
- **tag** (optional): Filter tasks by tag
- **limit** (optional, default `10`): Max items per board group. Totals are always shown in the summary.
- **Returns**: Tasks grouped by `available`, `not_ready`, `in_progress`, `in_review`, `blocked` with readiness checks, suitability hints, and per-group totals

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

### pm_update(id, status?, points?, title?, assignee?, unassign?, clear?, epic_id?, body?, acceptance_criteria?, tags?, depends_on?, outcome?, note?, project?)
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
- Epic status values: `draft`, `active`, `done`, `archived`
- Story status values: `backlog`, `ready`, `active`, `done`, `archived`
- Task status values: `todo`, `in-progress`, `review`, `done`, `blocked`
- **Returns**: `id`, current `status`, and the fields changed by this call (plus `run_log: <outcome>` when a run-log entry was appended) — not the full object
- When — and only when — a supplied note had to be truncated, the response also carries `note_truncated: true`, `note_original_length`, `note_stored_length`, `note_dropped_chars` and `note_limit`, so a caller detects truncation without string-matching. Absence of the fields means the note was stored whole. Every note-writing tool (`pm_update`, `pm_release`, `pm_done_next`) reports it the same way.

### pm_archive(id)
Archive an epic, story, or task.
- **id**: Epic, story, or task ID to archive (alias: `task_id`)

### pm_grab(task_id, assignee?, include_story?)
Claim a task with readiness validation.
- **task_id**: Task ID to claim (e.g. `US-PRJ-1-1`) (alias: `id`)
- Sets assignee and status to `in-progress`
- Validates task readiness before claiming
- Claims by compare-and-swap on the on-disk assignee and status, under an exclusive lock on the task file — two concurrent workers cannot both win. The winner's response shape is unchanged; the loser gets `{outcome: expected_negative, status: already_claimed, message, holder, task_id}` and the task is left untouched. Re-claiming a task you already hold still succeeds.
- Loads task context for implementation
- **include_story** (optional, default `true`): Include the parent story body. Pass `false` when the story context is already known (e.g. grabbing a second task from the same story).
- **Returns**: Task details and context — task frontmatter + body, story context, unfinished sibling tasks (with `sibling_tasks_total` / `sibling_tasks_done` counts), dependency status, readiness warnings. Returns an expected negative `{outcome: expected_negative, status: not_ready, message, blockers}` when the readiness check fails (the task is left untouched).

### pm_release(task_id, status?, note?, outcome?, expected_assignee?, project?)
Release a task — hand it back to the pool. The exact inverse of `pm_grab`, and the form to use whenever a task must stop being someone's: `pm_release("US-PRJ-1-1", note="worker stopped before finishing")`.
- **task_id**: Task ID to release (alias: `id`). Tasks only — a story or epic id is an error, since `assignee` is a task-only field.
- Clears the assignee, sets the status, and appends a run-log entry — one call, no empty values anywhere. There is no `assignee` parameter: releasing is said by the verb.
- **status** (optional, default `todo`): Status to leave the task in
- **note** / **outcome** (optional): Run-log entry, appended only when one of them is given; `outcome` defaults to `info`
- **expected_assignee** (optional): Release only if this name still holds the task. Omit for an unguarded release. A mismatch is an expected negative (`status: not_holder`) and the task is left untouched.
- Releasing an already-unassigned task **succeeds**, with `from_assignee: null` — a cleanup loop never has to branch on it.
- **Returns**: `released:` with the full `task` and `from_assignee` (who held it before the call, or null), plus the `note_truncated` fields when the note had to be truncated (see `pm_update`)

### pm_done_next(task_id, outcome?, note?, assignee?, same_story_only?)
Complete a task and claim the next ready one in a single call — the loop primitive for working through tasks.
- **task_id**: Task ID just finished (e.g. `US-PRJ-1-1`) (alias: `id`)
- Marks `task_id` done; appends a run-log entry when `note` is given (`outcome` defaults to `success`)
- Closes the parent story automatically if this was its last open task (`story_closed` in the response)
- Grabs the next ready unassigned task — same-story siblings first (topological order), then other stories by priority. The story body is only included when the next task belongs to a different story.
- **same_story_only** (optional, default `false`): Stop instead of crossing to another story
- **Returns**: `completed` summary, optional `story_closed`, and `next` (a full grab payload). When nothing is ready the response is an expected negative — `{outcome: expected_negative, status: no_next_task, message, completed, next: null, next_info}` — the task was still completed; only the second half of the question has no answer. The `note_truncated` fields (see `pm_update`) are present on both shapes when the note had to be truncated.

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

### pm_list_sprints(status?, project?)
List sprints, optionally filtered by status.
- **status** (optional): Filter by `planning`, `active`, `completed`, or `cancelled`
- **Returns**: Sprints with name, status, goal, and dates

### pm_update_sprint(sprint_id, name?, status?, goal?, start_date?, end_date?, planned_stories?, project?)
Update sprint fields (status, stories, dates, etc.).
- **sprint_id**: Sprint ID (alias: `id`)
- **status** (optional): New status — `planning`, `active`, `completed`, or `cancelled`
- **planned_stories** (optional): Comma-separated story IDs (replaces the planned set)
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

### pm_audit(include_info?, project?)
Run project audit for drift detection. Performs 17 checks covering stories, tasks, epics, documentation, hub docs, assignments, dependencies, and malformed files.
- **include_info** (optional, default `false`): Include info-level findings in the response. By default only errors and warnings are returned, with omitted info findings summarized as a count. The full report is always written to `DRIFT.md`.

### pm_reindex(project?)
Rebuild project index and embeddings.

### pm_repair()
Scan the hub for unregistered projects, initialize missing PM data directories (`.project/projects/{name}/`), rebuild all indexes and embeddings, and regenerate dashboards. Hub mode only. Writes a `REPAIR.md` report.

## Web Dashboard Tools

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
Coordinated push: preflight checks, push subprojects, then push hub.
- **dry_run** (optional, default `false`): Preview what would be pushed without pushing
- **projects** (optional): Comma-separated project names (auto-discovers dirty projects if omitted)
- **Returns**: Per-project push results with preflight status

### pm_validate_branches()
Validate that hub submodule branches match their configured tracking branches.
- **Returns**: Per-project branch validation results

## Changeset Tools

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
- **Returns**: List of `gh pr create` commands with cross-references

### pm_changeset_push(changeset_id, project?)
Check PR merge status and update changeset status.
- **changeset_id**: Changeset ID (alias: `id`)
- **Returns**: Per-entry merge status, overall changeset status, `needs_review` flag

## Run Log

### pm_run_log(id, limit?, offset?, project?)
Read the run log for an epic, story, or task — shows previous work attempts, outcomes, and notes.
- **id**: Epic, story, or task ID (alias: `task_id`)
- **limit** (optional, default `20`): Max entries to return (most recent first)
- **offset** (optional, default `0`): Starting index for pagination
- **Returns**: JSON array of log entries, each with `timestamp`, `outcome`, `status`, `note`, `actor`

Run-log entries are created by passing `outcome` and/or `note` to `pm_update`. Stored as JSONL in `.project/logs/{item_id}.jsonl`.

## Activity Log

### pm_activity(item_id?, event_type?, from_date?, to_date?, actor?, limit?, offset?, project?)
Query the activity log with filtering and pagination.
- **item_id** (optional): Filter by item ID (alias: `id`)
- **event_type** (optional): Filter by event type (`create`, `update`, `delete`, `archive`)
- **from_date** (optional): Start date filter (ISO format)
- **to_date** (optional): End date filter (ISO format)
- **actor** (optional): Filter by actor name
- **limit** (optional, default `20`): Max entries to return
- **offset** (optional, default `0`): Starting index for pagination
- **Returns**: Formatted log entries, most recent first
