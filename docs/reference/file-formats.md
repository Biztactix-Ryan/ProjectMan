# File Formats Reference

## .project/ Directory Structure

```
.project/
├── config.yaml          # Project configuration
├── PROJECT.md           # Architecture and design decisions
├── INFRASTRUCTURE.md    # Current infrastructure reality
├── SECURITY.md          # Security posture and review notes
├── DRIFT.md             # Auto-generated drift report
├── index.yaml           # Compact project dashboard
├── activity.jsonl       # Append-only activity log
├── epics/
│   └── EPIC-PRJ-1.md   # Epic files
├── stories/
│   └── US-PRJ-1.md     # User story files
├── tasks/
│   └── US-PRJ-1-1.md   # Task files
├── sprints/
│   └── SPRINT-PRJ-1.md # Sprint files
├── logs/
│   └── US-PRJ-1-1.jsonl # Per-item run logs
└── changesets/
    └── CS-PRJ-1.md      # Changeset files
```

With `--hub`, also creates:
```
.project/
├── VISION.md            # Hub vision and mission
├── ARCHITECTURE.md      # System-wide architecture
├── DECISIONS.md         # Cross-project decision log
├── projects/            # Per-project PM data (stories, tasks, epics, config)
│   └── {name}/          # e.g. .project/projects/my-api/
│       ├── config.yaml
│       ├── stories/
│       ├── tasks/
│       └── epics/
├── roadmap/
└── dashboards/
```

In hub mode, per-project PM data lives in `.project/projects/{name}/` inside the hub repo. Git submodules under `projects/` remain source-code-only.

## config.yaml

Project configuration. Created by `projectman init`.

```yaml
name: my-project
prefix: PRJ              # Uppercase letters, used for epic/story/task IDs
description: ""
hub: false               # true for hub mode
auto_commit: false       # Auto-commit .project/ changes after writes
deploy_branch: null      # Default branch for push operations
next_story_id: 1         # Auto-incremented
next_epic_id: 1          # Auto-incremented
next_changeset_id: 1     # Auto-incremented
projects: []             # Hub mode: list of registered project names
stale_claim_hours: 2.0   # Age at which an in-progress claim is flagged stale
tools:                   # Optional — which gated tool families agents see
  changesets: null       # null = follow `hub`; true/false to force
  maintenance: false     # Break-glass repair/restore tools, off by default
  web: false             # Web dashboard tools, off by default
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Project name |
| `prefix` | string | Uppercase letters, used as ID prefix for epics, stories, and tasks (e.g. `PRJ` → `EPIC-PRJ-1`, `US-PRJ-1`, `US-PRJ-1-1`) |
| `description` | string | Project description |
| `hub` | bool | Whether this is a hub (multi-repo) project |
| `auto_commit` | bool | Whether to auto-commit `.project/` changes after write operations |
| `deploy_branch` | string\|null | Default branch for push operations |
| `next_story_id` | int | Next story number to assign (auto-incremented) |
| `next_epic_id` | int | Next epic number to assign (auto-incremented) |
| `next_changeset_id` | int | Next changeset number to assign (auto-incremented) |
| `projects` | list[str] | Hub mode: names of registered subprojects |
| `stale_claim_hours` | float | How long an in-progress claim may sit before `pm_active` / `pm_board` flag it `stale: true` — a claim must *pass* this age, so exactly at the threshold is not yet stale. Default `2.0`. A task with no `claimed_at` is never stale regardless. Turn it *up* rather than to `0` to disable — `0` flags every live claim. A value that is not a non-negative finite number falls back to `2.0` rather than failing the config load |
| `tools.changesets` | bool\|null | Register the five `pm_changeset_*` tools. `null` (default) follows `hub` |
| `tools.maintenance` | bool | Register the five break-glass tools (`pm_repair`, `pm_restore`, `pm_validate_branches`, `pm_fix_malformed`, `pm_push_all`). Default `false` |
| `tools.web` | bool | Register the three `pm_web_*` tools. Default `false` |

### tools — gated tool families

Three tool families are registered with the MCP server only when this project
asks for them. Across ~14,200 recorded tool calls on four machines none of
their members was ever called, so by default their schemas were paid for in
every request and never used. Hiding them costs nothing that was in use and
takes **thirteen** tools off `tools/list` — 54 registered, 41 visible with a
default config.

Nothing is deleted: the code is untouched, and turning a family back on is
one line.

```yaml
tools:
  web: true              # pm_web_start / pm_web_stop / pm_web_status
```

```yaml
tools:
  changesets: true       # the five pm_changeset_* tools
```

```yaml
tools:
  maintenance: true      # pm_repair / pm_restore / pm_validate_branches
                         # pm_fix_malformed / pm_push_all
```

`tools.changesets` is tri-state. Left unset — which is what an untouched
`config.yaml` gives you — it **follows `hub`**: a changeset groups one change
across several projects, which only a hub has, so a hub gets the family and a
plain repo does not. Writing `changesets: false` in a hub config, or
`changesets: true` in a leaf one, overrides that inference. `tools.web` and
`tools.maintenance` get no such inference — a hub is no likelier than a leaf
repo to want the dashboard driven from an agent's tool list, and it breaks no
more often — so both are a plain `false` by default everywhere.

`tools.maintenance` is the odd one out in *why* it is hidden. The other two
are hidden because nobody calls them; these five are hidden because they are
aimed at the wrong audience. Repairing a hub, un-quarantining a malformed
file or driving a coordinated push is human recovery work, and every one of
the five has a CLI equivalent, so hiding them from the agent's tool list
takes away no reach:

| Tool | CLI command |
|------|-------------|
| `pm_repair` | `projectman repair` |
| `pm_restore` | `projectman restore <filename> [--project NAME]` |
| `pm_validate_branches` | `projectman validate-branches` |
| `pm_fix_malformed` | `projectman fix-malformed <filename> --id ID --title T --type story\|task` |
| `pm_push_all` | `projectman push-all [--dry-run] [--projects a,b]` |

A hidden tool is hidden from `tools/list` **and** from `tools/call`: calling
one gets the same `Unknown tool: <name>` any misspelled name gets, with
`is_error` set. The flags are read when the server starts, so a change takes
effect on the next server restart.

## index.yaml

Compact project dashboard. Auto-generated by write operations and audits.

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

## Changeset Format (changesets/CS-PRJ-1.md)

Changesets coordinate multi-project changes across a hub. They use YAML frontmatter with a list of project entries.

```markdown
---
id: CS-PRJ-1
title: Add authentication across services
status: open
entries:
  - project: my-api
    ref: feature/auth
    pr_number: null
    status: pending
  - project: my-frontend
    ref: feature/auth-ui
    pr_number: null
    status: pending
created: '2026-03-01'
updated: '2026-03-01'
---

## Description

Coordinated authentication changes across the API and frontend services.
```

### Changeset Frontmatter Fields

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `id` | string | yes | Pattern: `CS-PREFIX-N` (e.g. `CS-PRJ-1`) |
| `title` | string | yes | Short descriptive title |
| `status` | enum | yes | `open`, `partial`, `merged`, `closed` |
| `entries` | list | yes | List of project entries (see below) |
| `created` | date | yes | ISO date |
| `updated` | date | yes | ISO date |

### Changeset Entry Fields

| Field | Type | Description |
|-------|------|-------------|
| `project` | string | Registered project name |
| `ref` | string | Git branch/ref for this project's changes |
| `pr_number` | int\|null | PR number once created |
| `status` | string | `pending`, `open`, `merged`, `closed`, `no-pr` |

### Changeset Status Lifecycle

```
open → partial → merged
         ↓
       closed
```

Status is determined automatically: all entries merged → `merged`, some merged → `partial`, any closed → `closed`.

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
| `item_type` | enum | `story`, `task`, `epic`, `changeset` |
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
the audit reads, hashed by content: item files, `config.yaml`, project and hub
docs, `malformed/`, `logs/*.jsonl`, sprints and indexes. It is stable across
calls with no writes in between and changes whenever any audit input changes,
so a poller can tell an unchanged project from a changed one without diffing
reports. `DRIFT.md` itself and derived caches such as `embeddings.db` are
excluded from the hash. The same digest appears in every `pm_audit` response.

Severity levels:
- **ERROR** — critical inconsistencies (done stories with incomplete tasks, done epics with open stories, missing documentation)
- **WARNING** — likely needs action (undecomposed stories, stale items, orphaned references, malformed files)
- **INFO** — suggestions (thin descriptions, point mismatches, stale drafts, stale documentation)

The audit runs 18 checks covering stories, tasks, epics, documentation, hub docs, assignments, dependencies, malformed files, and completion evidence.
