# Epics

Epics are strategic initiatives that group related stories. They are first-class
entities stored in `.project/epics/` with YAML frontmatter, just like stories
and tasks.

**In a hub, epics are hub-level.** They live in the hub's own store and carry
the hub's prefix, and the stories they group may sit in any number of
subprojects. That is what makes an epic the place a cross-repo initiative is
tracked: the stories live with their code, the epic lives above them.

## Creating an Epic

```
/pm create epic "Unified Authentication" "Single sign-on across all services"
```

Or via MCP: `pm_create_epic(title, description, priority?, target_date?, tags?)`

`pm_create_epic` takes **no prefix**. In a hub it always writes to the hub's own
store, so the new epic is `EPIC-HUB-1` in `.project/epics/`; outside a hub it
writes to the single store, which is the same rule. To make an epic
project-specific, link only that project's stories to it.

## Epic Format

```yaml
---
id: EPIC-HUB-1
title: "Unified Authentication"
status: draft
priority: must
points: null
target_date: '2026-06-30'
tags: [security, mvp]
created: '2026-02-15'
updated: '2026-02-15'
---

## Vision

Single sign-on across all services by Q2.

## Success Criteria

- [ ] Users can log in once and access all services
- [ ] JWT tokens are validated across all backends
- [ ] Session timeout is consistent (30 min)
```

## Epic Lifecycle

```
draft → active → done → archived
```

1. **Draft** — write the epic with vision and success criteria
2. **Active** — stories are being created and worked on
3. **Done** — all linked stories are complete
4. **Archived** — historical record

## Linking Stories to Epics

Stories link to epics via the `epic_id` frontmatter field, and a story in one
repo may name an epic in the hub:

```yaml
---
id: US-API-5
title: Backend auth service
epic_id: EPIC-HUB-1
status: active
---
```

Link during creation:

```
pm_create_story(title, description, prefix="API", epic_id="EPIC-HUB-1")
```

Or link an existing story:

```
pm_update("US-API-5", epic_id="EPIC-HUB-1")
```

The story is addressed by its ID, whose prefix says which store it is in; the
epic is addressed by its ID too. Nothing names a directory.

## Viewing Epic Progress

```
pm_epic("EPIC-HUB-1")
```

Returns the epic details plus:

- Linked stories with their tasks (paginated, default 10 per page)
- Total and completed points (the rollup always covers **all** stories, not just
  the page)
- Completion percentage
- `has_more` / `next_offset` for pagination when there are many stories

### The hub rollup, grouped by project

An epic in the hub's own store rolls up **every** store: the hub's own stories
first, then each attached subproject in registration order. The totals cover all
of them, each story row carries a `project`, and `rollup` gains a `by_project`
breakdown — one `{name, prefix, stories, total_points, completed_points}` row
per store that actually has a linked story.

`limit` and `offset` page through the flattened list, so a page can span two
projects:

```
pm_epic("EPIC-HUB-1", limit=10, offset=10)
```

A registered subproject whose store is not mounted is named in
`rollup.not_attached`, with the usual attach hint, rather than being silently
dropped — a rollup missing a whole repo has to say so. Mount it with
`projectman sync` (or `projectman attach` inside that checkout) and re-run.

A subproject-local epic, and every epic outside a hub, returns exactly the
single-store shape above.

### How epics are counted elsewhere

Epics are counted once. `pm_status` with no prefix reports the hub's *own* epic
count. The hub rollup's `total_epics` is the hub's epics plus any a subproject
has not migrated up yet, with the hub's share also under `hub_epics`. The
dashboards' per-project Epics column stays each subproject's own, because a hub
epic belongs to no single project.

## Migrating Subproject-Local Epics Up

A hub built before epics moved up has `EPIC-{PROJECT}-N` files sitting in the
subproject stores.
[`projectman migrate-hub`](../reference/cli.md#projectman-migrate-hub) moves
them: each one is written into the hub's `.project/epics/` under a fresh
hub-prefixed ID taken from the hub store's own counter (so `next_epic_id`
advances exactly as `pm_create_epic` would have advanced it), and every story in
*every* store that referenced the old ID has its `epic_id` rewritten —
including a story in one subproject that pointed at an epic living in another,
since the mapping is hub-wide rather than per project. Each store that changed
is committed inside itself, so a worktree store commits on its `projectman`
branch, and the commit message names the mapping. The command prints it too:

```
Moved 2 subproject epics up to the hub.
  alpha: EPIC-ALP-1 -> EPIC-HUB-1 (1 story relinked: US-ALP-2)
  beta:  EPIC-BET-1 -> EPIC-HUB-2 (2 stories relinked: US-ALP-3, US-BET-2)
```

The epics step is independent of the store move the same command does, so it
runs on a hub whose stores already live at `projects/{name}/.project` —
`migrate-hub` is still the command to reach for. `--dry-run` prints the mapping
it *would* make and changes nothing, not even `next_epic_id`; a hub with no
subproject epics says there is nothing to move and exits 0; re-running is a
no-op, because after the first run there are no epics left outside the hub. It
refuses, having changed nothing, if the hub tree or any store it would commit in
is dirty.

## Audit Checks

The audit system validates epic consistency:

- **Empty active epic** [WARNING] — active epic with no linked stories
- **Done epic with open stories** [ERROR] — epic marked done but stories still open
- **Orphaned epic reference** [WARNING] — story references non-existent epic
- **Stale draft epic** [INFO] — draft epic with no stories for 30+ days

## Best Practices

- Keep epics focused on a clear strategic goal
- Link all related stories to their epic for tracking, wherever those stories live
- Use `pm_epic(id)` to review progress regularly
- Move epics to done only when all linked stories are complete
- Archive completed epics to keep the board clean
