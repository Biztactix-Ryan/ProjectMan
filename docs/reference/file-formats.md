# File Formats Reference

## .project/ Directory Structure

```
.project/
├── config.yaml          # Project configuration
├── PROJECT.md           # Architecture and design decisions
├── INFRASTRUCTURE.md    # Current infrastructure reality
├── SECURITY.md          # Security posture and review notes
├── DRIFT.md             # Auto-generated drift report
├── .gitignore           # Excludes the five derived index files below
├── index.yaml           # Compact project dashboard — derived, not tracked
├── INDEX.md             # Human-readable board — derived, not tracked
├── INDEX-EPICS.md       # Derived, not tracked
├── INDEX-STORIES.md     # Derived, not tracked
├── INDEX-TASKS.md       # Derived, not tracked
├── activity.jsonl       # Append-only activity log
├── epics/
│   └── EPIC-PRJ-1.md   # Epic files
├── stories/
│   └── US-PRJ-1.md     # User story files
├── tasks/
│   └── US-PRJ-1-1.md   # Task files
├── sprints/
│   └── SPRINT-PRJ-1.md # Sprint files
└── logs/
    └── US-PRJ-1-1.jsonl # Per-item run logs
```

## config.yaml

Project configuration. Created by `projectman init`.

```yaml
name: my-project
prefix: PRJ              # Uppercase letters, used for epic/story/task IDs
description: ""
auto_commit: false       # Auto-commit .project/ changes after writes
deploy_branch: null      # Default branch for push operations
next_story_id: 1         # Auto-incremented
next_epic_id: 1          # Auto-incremented
next_sprint_id: 1        # Auto-incremented
stale_claim_hours: 2.0   # Age at which an in-progress claim is flagged stale
activity_log_max_bytes:  # Optional — rotate activity.jsonl past this many bytes
activity_log_max_days:   # Optional — rotate activity.jsonl past this many days
tools:                   # Optional — which gated tool families agents see
  maintenance: false     # Break-glass repair/restore tools, off by default
  web: false             # Web dashboard tools, off by default
orchestrate:             # Optional — knobs for orchestrated runs
  max_task_minutes: 60   # Ceiling on a single task's expected runtime
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Project name |
| `prefix` | string | Uppercase letters, used as ID prefix for epics, stories, and tasks (e.g. `PRJ` → `EPIC-PRJ-1`, `US-PRJ-1`, `US-PRJ-1-1`) |
| `description` | string | Project description |
| `auto_commit` | bool | Whether to auto-commit `.project/` changes after write operations |
| `deploy_branch` | string\|null | Default branch for push operations |
| `next_story_id` | int | Next story number to assign (auto-incremented) |
| `next_epic_id` | int | Next epic number to assign (auto-incremented) |
| `next_sprint_id` | int | Next sprint number to assign (auto-incremented) |
| `stale_claim_hours` | float | How long an in-progress claim may sit before `pm_active` / `pm_board` flag it `stale: true` — a claim must *pass* this age, so exactly at the threshold is not yet stale. Default `2.0`. A task with no `claimed_at` is never stale regardless. Turn it *up* rather than to `0` to disable — `0` flags every live claim. A value that is not a non-negative finite number falls back to `2.0` rather than failing the config load |
| `activity_log_max_bytes` | int\|null | Rotate `activity.jsonl` once it reaches this many bytes. Default `null` — no size bound, the log grows forever. See [Activity Log Rotation](#activity-log-rotation) |
| `activity_log_max_days` | float\|null | Rotate `activity.jsonl` once its **oldest entry** is this many days old. Default `null` — no age bound. See [Activity Log Rotation](#activity-log-rotation) |
| `tools.maintenance` | bool | Register the two break-glass tools (`pm_restore`, `pm_fix_malformed`). Default `false` |
| `tools.web` | bool | Register the three `pm_web_*` tools. Default `false` |
| `orchestrate.max_task_minutes` | float | Longest a single task should be expected to run, in minutes. Planning tools flag a points band whose measured p90 duration sits above this as `long_task_risk`, because a worker that overruns the one-hour prompt-cache window costs the next dispatch a full prefix rewrite. Default `60`. Turn it *up* rather than to `0` to disable — `0` flags every band. A value that is not a non-negative finite number falls back to `60` rather than failing the config load |

### tools — gated tool families

Two tool families are registered with the MCP server only when this project
asks for them. Across ~14,200 recorded tool calls on four machines none of
their members was ever called, so by default their schemas were paid for in
every request and never used. Hiding them costs nothing that was in use and
takes **eight** tools off `tools/list` — 50 registered, 42 visible with a
default config.

Nothing is deleted: the code is untouched, and turning a family back on is
one line.

```yaml
tools:
  web: true              # pm_web_start / pm_web_stop / pm_web_status
```

```yaml
tools:
  maintenance: true      # pm_restore / pm_fix_malformed
```

Neither flag takes any inference from anything else: both are a plain
`false` until someone writes `true`.

`tools.maintenance` is the odd one out in *why* it is hidden. The web family
is hidden because nobody calls it; these two are hidden because they are
aimed at the wrong audience. Un-quarantining a malformed file is human
recovery work, and both have a CLI equivalent, so hiding them from the
agent's tool list takes away no reach:

| Tool | CLI command |
|------|-------------|
| `pm_restore` | `projectman restore <filename> [--project NAME]` |
| `pm_fix_malformed` | `projectman fix-malformed <filename> --id ID --title T --type story\|task` |

A hidden tool is hidden from `tools/list` **and** from `tools/call`: calling
one gets the same `Unknown tool: <name>` any misspelled name gets, with
`is_error` set. The flags are read when the server starts, so a change takes
effect on the next server restart.

## Derived index files — generated, not tracked

Five files in every store are derived: `index.yaml`, `INDEX.md`,
`INDEX-EPICS.md`, `INDEX-STORIES.md` and `INDEX-TASKS.md`. Every byte of
them is recomputed from the epic, story and task files beside them, so
nothing is lost by deleting them. They are rebuilt by `pm_reindex`, by
`pm_commit` just before staging, by `projectman reindex`, and on demand by
any reader that finds `index.yaml` older than the newest file under
`epics/`, `stories/` or `tasks/` (`indexer.ensure_fresh`).

**Decision (US-PM-29-6, 2026-09-06): generated.** A store scaffolded by
`projectman init` writes a `.project/.gitignore` naming those five files, so
git never carries them.

### The churn numbers

Measured on this repository's own store (84 commits, 12 of them touching
`.project/`) after the per-write rebuilds were removed (US-PM-29-4/5):

| Historical churn (`git log --numstat` over `.project/`) | |
| --- | --- |
| Commits touching at least one index file | 9 of 84 (11%); 9 of the 12 `.project/` commits (75%) |
| Commits touching all five | 6 |
| Commits changing item files *without* touching an index | 1 |
| Index lines as a share of all changed lines | 17,351 of 184,937 (9%) |
| Commits where the index diff outweighed the rest of the diff | 1 of 9 |
| Item files carried alongside an index change | median 63, range 17–448 |

That history is human batch commits — dozens of items at a time — so it
understates what per-write `pm_commit` will do. The forward-looking number
is what one rebuild changes, measured on a copy of the same store:

| Change made | Index files changed | Index lines ± | Item lines ± |
| --- | --- | --- | --- |
| Nothing (rebuild on an unchanged store) | 0 of 5 | 0 | 0 |
| One task status flip | 2 of 5 | 6 | 2 (+1 activity line) |
| One story retitled | 2 of 5 | 4 | 2 |
| One task created | 4 of 5 | 18 | ~12 |
| Ten task status flips at once | 2 of 5 | 42 | 20 |

### Why generated

The rebuild is now idempotent — an unchanged store rebuilds to zero diff,
which was the whole point of US-PM-29-4 — but an index change still rides
along with *every* commit that carries an item change, because the indexes
summarise every item. For the common case, one task edit, that means four
changed files instead of two and roughly twice as many changed lines in the
echo as in the change itself. Three costs decided it:

1. **The same change lands in the commit twice**, once as the item file and
   once as its rendering, so a reviewer reads a diff that is mostly restated.
2. **`index.yaml` is a guaranteed conflict.** It is ~7,000 lines listing every
   item, so any two branches — or two parallel agents — that touched
   *different* tasks conflict in it. Item files never conflict with each other.
3. **A read can dirty the tree.** `ensure_fresh` repairs a lagging index on the
   read path, so opening the dashboard after a write modifies tracked files.
   No amount of care at commit time fixes that while the files are tracked.

Against that, tracking them buys a browsable board on the git remote — not
enough to pay for the three costs above. A fresh clone needs no migration step
either: a missing `index.yaml` counts as stale, so the first read regenerates
all five.

Commit messages ignore the five files, in old stores and new ones alike
(`Store._generate_commit_message`):
one task edit reads `pm: update 1 task`, never `pm: update 1 task, config, 4 files`.

### Migrating an existing store

Stores created before this change still track the five files. To convert one
(run from the store's git root — for a worktree-mounted store, that is
`.project/` itself):

```bash
projectman reindex                      # make sure the files on disk are current
cat >> .project/.gitignore <<'EOF'
INDEX.md
INDEX-EPICS.md
INDEX-STORIES.md
INDEX-TASKS.md
index.yaml
EOF
git rm --cached -- .project/INDEX.md .project/INDEX-EPICS.md \
    .project/INDEX-STORIES.md .project/INDEX-TASKS.md .project/index.yaml
git add .project/.gitignore
git commit -m "pm: stop tracking the derived index files"
```

`git rm --cached` leaves the working copies in place; only the tracking
stops. Nothing else needs changing — the rebuild points and the read-path
repair already keep the files current.

## index.yaml

Compact project dashboard, and one of the five derived files above — see
[Derived index files](#derived-index-files--generated-not-tracked) for why it
is not tracked and when it is rebuilt.

```yaml
entries:
  - id: EPIC-PRJ-1
    title: Authentication system
    type: epic
    status: active
    points: 8
  - id: US-PRJ-1
    title: User authentication
    type: story
    status: active
    points: 5
    epic_id: EPIC-PRJ-1
  - id: US-PRJ-1-1
    title: JWT middleware
    type: task
    status: in-progress
    points: 2
    story_id: US-PRJ-1
    tags: [backend]
total_points: 5
completed_points: 0
epic_count: 1
story_count: 1
task_count: 1
```

## Story Format (stories/US-PRJ-1.md)

Stories use YAML frontmatter followed by a markdown body.

```markdown
---
id: US-PRJ-1
title: User authentication
status: backlog
priority: should
points: 5
epic_id: EPIC-PRJ-1
tags: [auth, security]
created: '2026-02-15'
updated: '2026-02-15'
---

## As a user, I want to log in securely

So that my account is protected.

## Acceptance Criteria

- [ ] Login with email/password
- [ ] Password validation rules enforced
- [ ] Session management with timeout
```

### Story Frontmatter Fields

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `id` | string | yes | Pattern: `US-PREFIX-N` (e.g. `US-PRJ-1`) |
| `title` | string | yes | Short descriptive title |
| `status` | enum | yes | `backlog`, `ready`, `active`, `done`, `archived` |
| `priority` | enum | yes | `must`, `should`, `could`, `wont` |
| `points` | int\|null | no | Fibonacci: 1, 2, 3, 5, 8, 13 |
| `epic_id` | string\|null | no | Parent epic ID |
| `tags` | list[str] | no | Free-form tags |
| `created` | date | yes | ISO date |
| `updated` | date | yes | ISO date |

### Story Status Lifecycle

```
backlog → ready → active → done → archived
```

## Task Format (tasks/US-PRJ-1-1.md)

Tasks use YAML frontmatter and serve as work orders for developers or Claude.

```markdown
---
id: US-PRJ-1-1
story_id: US-PRJ-1
title: Implement JWT middleware
status: todo
points: 2
assignee: null
claimed_at: null         # Set when claimed, cleared on release/done
claimed_by_run: null     # Which run holds the claim
tags: [backend]
depends_on: []
created: '2026-02-15'
updated: '2026-02-15'
---

## Implementation

Add JWT validation middleware to the Express app.

### Files to modify
- `src/middleware/auth.ts`
- `src/config/jwt.ts`

## Testing

- Unit test JWT validation with valid/invalid/expired tokens
- Integration test protected endpoints

## Definition of Done

- [ ] Middleware validates JWT on protected routes
- [ ] Invalid tokens return 401
- [ ] Tests passing
```

### Task Frontmatter Fields

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `id` | string | yes | Pattern: `US-PREFIX-N-N` (e.g. `US-PRJ-1-1`) |
| `story_id` | string | yes | Parent story ID |
| `title` | string | yes | Short descriptive title |
| `status` | enum | yes | `todo`, `in-progress`, `review`, `done`, `blocked` |
| `points` | int\|null | no | Fibonacci: 1, 2, 3, 5, 8, 13 |
| `assignee` | string\|null | no | Who is working on this |
| `claimed_at` | datetime\|null | no | UTC ISO-8601 timestamp of the claim in force. Written by `pm_grab` / the next-claim in `pm_done_next`; cleared on release and on done |
| `claimed_by_run` | string\|null | no | Opaque id of the run holding the claim. Cleared with `claimed_at` |
| `tags` | list[str] | no | Free-form tags |
| `depends_on` | list[str] | no | Task IDs this task depends on (must be siblings under the same story) |
| `created` | date | yes | ISO date |
| `updated` | date | yes | ISO date |

### Task Status Lifecycle

```
todo → in-progress → review → done
              ↓
           blocked
```

### Claim ownership — `claimed_at` / `claimed_by_run`

`assignee` says *who* holds a task. It is not enough to recover from a crash:
every agent claim is `claude`, so an orchestrator restarting after a dead run
cannot tell a task being worked right now from one abandoned forty minutes ago.
These two fields answer that without asking a human.

- `claimed_by_run` — an opaque run id. Callers pass `run_id` to `pm_grab`,
  `pm_release`, `pm_accept` or `pm_done_next`; when they do not, the MCP
  server's own per-process id is used, so **every claim has an owner**.
- `claimed_at` — UTC ISO-8601, the moment the claim was taken.

Rules the store enforces:

| Event | `assignee` | `claimed_at` / `claimed_by_run` |
|-------|-----------|----------------------------------|
| `pm_grab` / next-claim wins | set | set |
| re-claim by the **same** run | unchanged | **unchanged** — the claim did not change hands, so its age keeps running |
| re-claim by a **different** run | set | reset — a restarted run retaking `claude`'s work is a new claim |
| `pm_release`, `pm_retry`, `pm_park`, `pm_review` | cleared | cleared |
| `pm_accept` / `pm_done_next` (done) | **kept** — a done task records who did it | cleared — the claim is no longer in force |

Both fields are optional and default to `null`, so a task file written before
they existed loads unchanged. Such a task has an **unknown** claim age and is
never reported stale: treating a missing timestamp as "old" would have a
recovery loop take live work away from an older writer.

Staleness is not stored — it is computed on read from `claimed_at` against
`stale_claim_hours` (below) and surfaced by `pm_active` and `pm_board`.

## Epic Format (epics/EPIC-PRJ-1.md)

Epics use YAML frontmatter followed by a markdown body.

```markdown
---
id: EPIC-PRJ-1
title: Authentication system
status: active
priority: must
points: 8
target_date: '2026-03-15'
tags: [auth, security]
created: '2026-02-15'
updated: '2026-02-15'
---

## Overview

Build a complete authentication system supporting email/password login,
session management, and role-based access control.

## Goals

- Secure user login and registration
- Session handling with configurable timeout
- Role-based authorization
```

### Epic Frontmatter Fields

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `id` | string | yes | Pattern: `EPIC-PREFIX-N` (e.g. `EPIC-PRJ-1`) |
| `title` | string | yes | Short descriptive title |
| `status` | enum | yes | `draft`, `active`, `done`, `archived` |
| `priority` | enum | yes | `must`, `should`, `could`, `wont` |
| `points` | int\|null | no | Fibonacci: 1, 2, 3, 5, 8, 13 |
| `target_date` | date\|null | no | Target completion date |
| `tags` | list[str] | no | Free-form tags |
| `created` | date | yes | ISO date |
| `updated` | date | yes | ISO date |

### Epic Status Lifecycle

```
draft → active → done → archived
```

## Sprint Format (sprints/SPRINT-PRJ-1.md)

Sprints are time-boxed planning containers that reference a set of stories. They use YAML frontmatter; the body is free-form notes.

```markdown
---
id: SPRINT-PRJ-1
name: Sprint 1 — Auth & Onboarding
status: active
start_date: '2026-03-01'
end_date: '2026-03-14'
planned_stories:
  - US-PRJ-1
  - US-PRJ-2
planned_points: 13
completed_points: 5
goal: Ship end-to-end login and account creation
created: '2026-03-01'
updated: '2026-03-05'
---

Sprint notes and retrospective go here.
```

### Sprint Frontmatter Fields

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `id` | string | yes | Pattern: `SPRINT-PREFIX-N` (e.g. `SPRINT-PRJ-1`) |
| `name` | string | yes | Sprint name |
| `status` | enum | yes | `planning`, `active`, `completed`, `cancelled` |
| `start_date` | date | no | ISO date |
| `end_date` | date | no | ISO date |
| `planned_stories` | list | no | Story IDs planned for the sprint |
| `planned_points` | int | no | Total points of planned stories |
| `completed_points` | int | no | Points completed so far |
| `goal` | string | no | Sprint goal summary |
| `created` | date | yes | ISO date |
| `updated` | date | yes | ISO date |

### Sprint Status Lifecycle

```
planning → active → completed
                 ↘ cancelled
```

## Activity Log Format (activity.jsonl)

The activity log is an append-only JSONL file at `.project/activity.jsonl`. Each line is a JSON object recording a single event.

```json
{"event_type": "create", "item_id": "US-PRJ-1", "item_type": "story", "changes": {"title": "User authentication", "status": "backlog"}, "timestamp": "2026-03-01T14:30:45.123456", "actor": "claude", "source": "mcp"}
{"event_type": "update", "item_id": "US-PRJ-1", "item_type": "story", "changes": {"status": ["backlog", "active"]}, "timestamp": "2026-03-01T15:00:00.000000", "actor": "claude", "source": "mcp"}
```

### Activity Log Entry Fields

| Field | Type | Values |
|-------|------|--------|
| `event_type` | enum | `create`, `update`, `delete`, `archive` |
| `item_id` | string | ID of the affected item |
| `item_type` | enum | `story`, `task`, `epic` |
| `changes` | dict | Field changes (for updates, values are `[old, new]` pairs) |
| `timestamp` | datetime | ISO 8601 with microseconds |
| `actor` | string | Who performed the action (e.g. `claude`, a human name) |
| `source` | enum | `mcp`, `web`, `cli` |
| `run_id` | string\|null | Which orchestrator run owned this mutation. Set on claim, release and verdict events; `null` on ordinary edits and on every line written before the field existed |

`run_id` exists because `actor` is too coarse for recovery: every run of every
agent on a machine shares one actor, so "what did *my* previous run claim?"
cannot be answered from it. A claim event also carries `claimed_at` and
`claimed_by_run` in its `changes` diff.

The log is never overwritten — new entries are always appended. Query it with `pm_activity`.

### Activity Log Rotation

By default `activity.jsonl` grows forever, which is fine for most projects and
not for a long-lived one — this repo's log passed 300 KB in six weeks. Two
optional `config.yaml` keys bound it:

```yaml
activity_log_max_bytes: 1048576   # rotate once the live file reaches 1 MB
activity_log_max_days: 90         # rotate once its oldest entry is 90 days old
```

Set either, both, or neither. **Neither is the default**, and with neither set
nothing rotates — an existing project behaves exactly as it did before the keys
existed. A value that is not a positive finite number (a typo, `0`, a negative)
is read as "no bound" rather than failing the config load.

The bounds are checked on append, against the file already on disk:

1. If the live `activity.jsonl` is at or past a bound, it is **renamed** to a
   dated sibling `activity-YYYYMMDD-HHMMSS.jsonl` (UTC, the moment of rotation).
   A rename, not a copy — atomic on one filesystem, so there is no instant at
   which an entry lives in neither file.
2. The entry being appended is then written to a fresh `activity.jsonl`.

Because the check happens *before* the write, rotation can never drop the entry
that triggered it. If the rename fails for any reason the entry is still
appended to the live file: an oversized log is a smaller problem than a lost
event. An empty log is never rotated.

The **size** bound is the live file's bytes on disk. The **age** bound is
measured from the log's *oldest entry's* `timestamp`, not the file's mtime —
mtime is the last append, by which a busy log would look permanently young. If
no entry in the file's first 100 lines carries a parseable timestamp, the file's
mtime stands in.

Readers see across rotations. `pm_activity`, the web dashboard's `/api/activity`
and the migration commands all read the rotated siblings in name order (which is
chronological, the timestamp being fixed-width) and then the live file, so
`total` counts the whole history and paging back reaches events written before
the last rotation. `pm_activity` reports `No activity log found` only when there
is neither a live file nor a rotated sibling.

Rotated siblings are ordinary files in `.project/`; nothing deletes them, so
pruning old ones is a human decision. Only names matching the exact
`activity-YYYYMMDD-HHMMSS.jsonl` pattern are treated as rotation output — an
`activity-old.jsonl` you drop in yourself is ignored, by the reader and by
`pm_reindex` alike (the indexers only scan `stories/`, `tasks/`, `epics/` and
`sprints/`).

## Run Log Format (logs/{item_id}.jsonl)

Each epic, story, or task can have a per-item run log — an append-only JSONL file at `.project/logs/{item_id}.jsonl` that records work attempts and their outcomes. Entries are created by passing `outcome` and/or `note` to `pm_update`.

```json
{"timestamp": "2026-03-01T15:00:00.000000+00:00", "outcome": "success", "status": "done", "note": "Implemented login endpoint and tests", "actor": "claude"}
{"timestamp": "2026-03-01T16:30:00.000000+00:00", "outcome": "blocked", "status": "blocked", "note": "Waiting on auth service credentials", "actor": "claude"}
```

### Run Log Entry Fields

| Field | Type | Values |
|-------|------|--------|
| `timestamp` | datetime | ISO 8601 (UTC) |
| `outcome` | enum | `success`, `partial`, `blocked`, `failed`, `info` |
| `status` | string | Item status at the time of the entry (may be null) |
| `note` | string | What was accomplished or blocked (max 1024 chars) |
| `actor` | string | Who performed the work (e.g. `claude`, a human name) |

Read the history with `pm_run_log`, or fetch the most recent entries inline via `pm_get(id, include_log=true)`.

## DRIFT.md

Auto-generated by `pm_audit`. Lists inconsistencies found in the project.

```markdown
# Project Audit Report

digest: 4f1c8a9b2d7e0356

**Errors:** 1 | **Warnings:** 0 | **Info:** 1

- [ERROR] Story US-PRJ-1 is done but has 1 incomplete task(s)
- [INFO] Story US-PRJ-3 has a thin description (12 chars)
```

The `digest:` line is a fixed-width (16 hex character) fingerprint of everything
the audit reads, hashed by content: item files, `config.yaml`, project
docs, `malformed/`, `logs/*.jsonl`, sprints and indexes. It is stable across
calls with no writes in between and changes whenever any audit input changes,
so a poller can tell an unchanged project from a changed one without diffing
reports. `DRIFT.md` itself and derived caches such as `embeddings.db` are
excluded from the hash. The same digest appears in every `pm_audit` response.

Severity levels:
- **ERROR** — critical inconsistencies (done stories with incomplete tasks, done epics with open stories, missing documentation)
- **WARNING** — likely needs action (undecomposed stories, stale items, orphaned references, malformed files)
- **INFO** — suggestions (thin descriptions, point mismatches, stale drafts, stale documentation)

The audit covers stories, tasks, epics, documentation, assignments, dependencies, malformed files, and completion evidence. The full check list with severities is in [cli.md](cli.md#projectman-audit).
