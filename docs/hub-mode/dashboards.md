# Generated Dashboards

The hub can generate two markdown dashboards that give a cross-repo view of
every project at a glance. They are written to the **hub's own**
`.project/dashboards/`, from the same rollup `pm_burndown` and `GET /api/status`
read — every mounted store at `projects/{name}/.project`, plus the hub's own.

## status.md

```markdown
# Hub Status Dashboard

**Total Projects:** 3
**Total Epics:** 6
**Total Stories:** 54
**Total Tasks:** 140
**Completion:** 55%

## Epic Progress

| Project | Epics | Stories | Completion |
|---------|-------|---------|------------|
| my-api | 3 | 24 | 68% |
| my-frontend | 2 | 18 | 51% |

## Projects

| Project | Epics | Stories | Tasks | Points | Done | Status |
|---------|-------|---------|-------|--------|------|--------|
| my-api | 3 | 24 | 67 | 145 | 98 | active |
| my-frontend | 2 | 18 | 42 | 89 | 45 | active |
| my-mobile | — | — | — | — | — | not attached |

## Not Attached

- **my-mobile** — no store mounted at projects/my-mobile/.project — run `projectman migrate-hub` if this project's PM data is still in the hub, or `projectman add-project my-mobile <url>` to attach a fresh one
```

## burndown.md

```markdown
# Hub Burndown Dashboard

**Total Points:** 298
**Completed:** 163
**Remaining:** 135
**Completion:** 55%

## Per-Project Burndown

**my-api**: [██████████████░░░░░░] 98/145 pts
**my-frontend**: [██████████░░░░░░░░░░] 45/89 pts
**my-mobile**: not attached — no points to burn
```

## Unattached Projects Are Rendered, Not Skipped

Generating a dashboard is a read, so it never fails because one subproject's
store is not mounted. Such a project appears twice: once in the Projects table
with a `not attached` status and dashes for its numbers, and once under a
**Not Attached** heading with the hint that says how to fix it. The wording is
the one `pm_status`, the rollup and the web API all use, so the four never
disagree about the same project.

## Epic Counting

A hub epic belongs to no single project, so it is counted **once**, outside the
project rows: `Total Epics` is the hub's own epics plus any a subproject has not
migrated up yet, while each project row's `Epics` column stays that
subproject's own count. See [epics.md](epics.md).

## Generating Dashboards

Nothing regenerates the dashboards on a schedule today — no CLI command and no
MCP tool writes them. Generate them from Python:

```python
from projectman.hub.dashboards import generate_dashboards
from projectman.config import find_project_root

generate_dashboards(find_project_root())
```

Run `projectman sync` first so every store is current and mounted.

## Reading Dashboards

Since the dashboards are markdown files in the hub's store, you can:

- View them directly on the hub's forge
- Read them in any markdown viewer
- Track changes over time via git history (useful for velocity trends)
- Reference them in reviews or standup notes

## Customization

Generation happens in `projectman/hub/dashboards.py`, and the output is plain
markdown, so the generator is straightforward to extend with sprint
breakdowns, per-assignee workload views, priority filters, or whatever your team
reads every morning.
