# Auditing & Drift Detection

## Running an Audit

```
/pm audit
```

Or via CLI: `projectman audit` (use `--all` for all hub projects)

## Checks (13 total)

| # | Check | Severity | Description |
|---|-------|----------|-------------|
| 1 | Done story with incomplete tasks | Error | Story marked done but has tasks not yet done |
| 2 | Undecomposed story | Warning | Active/ready story with no tasks |
| 3 | Stale in-progress tasks | Warning | Task in-progress for >14 days without update |
| 4 | Point mismatch | Info | Story points ≠ sum of task points |
| 5 | Thin description | Info | Story or task body under 20 characters |
| 6 | Documentation staleness | Error/Warning/Info | Missing docs, unfilled templates, or docs >30 days old |
| 7 | Empty active epic | Warning | Active epic with no linked stories |
| 8 | Done epic with open stories | Error | Epic marked done but has stories still open |
| 9 | Orphaned epic reference | Warning | Story references a non-existent epic ID |
| 10 | Stale draft epic | Info | Epic in draft >30 days with no linked stories |
| 11 | Hub documentation checks | Warning/Info | Missing or stale hub docs (VISION.md, ARCHITECTURE.md, DECISIONS.md) |
| 12 | Stale task assignment | Warning | Task assigned to someone with no updates for 14+ days |
| 13 | Malformed files | Warning | Files quarantined in .project/malformed/ |

## Severity Levels

- **ERROR** — Must be fixed (data inconsistencies that break assumptions)
- **WARNING** — Likely needs action (stale items, empty entities, malformed files)
- **INFO** — Suggestions for improvement (thin descriptions, stale docs, point mismatches)

## DRIFT.md

Audit results are written to `.project/DRIFT.md`. Review this file to track project health over time.

## Activity Log

Every create, update, delete, and archive operation is recorded in `.project/activity.jsonl` as an append-only audit trail.

### Viewing the Log

```
/pm activity
```

Or via MCP: `pm_activity()`

### Query Parameters

| Parameter | Description |
|-----------|-------------|
| `item_id` | Filter by item ID (e.g. `US-PRJ-1`) |
| `event_type` | Filter by event type: `create`, `update`, `delete`, `archive` |
| `from_date` | Start date (ISO format, e.g. `2026-03-01`) |
| `to_date` | End date (ISO format) |
| `actor` | Filter by who performed the action (e.g. `claude`) |
| `limit` | Max entries to return (default 20) |
| `offset` | Pagination offset |

### Log Entry Format

Each line in `activity.jsonl` is a JSON object:

```json
{
  "event_type": "update",
  "item_id": "US-PRJ-1",
  "item_type": "story",
  "changes": {"status": ["backlog", "active"]},
  "timestamp": "2026-03-01T15:00:00.000000",
  "actor": "claude",
  "source": "mcp"
}
```

- **event_type**: `create`, `update`, `delete`, `archive`
- **item_type**: `story`, `task`, `epic`, `changeset`
- **changes**: For creates, the initial field values. For updates, `[old, new]` pairs.
- **source**: Where the action originated — `mcp`, `web`, or `cli`
