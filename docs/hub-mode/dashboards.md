# Generated Dashboards

The hub auto-generates markdown dashboards that give you a cross-repo view of all your projects at a glance.

## Dashboard Files

Two dashboards are generated in `.project/dashboards/`:

### status.md

A summary table of every project in your hub:

```markdown
# Hub Status

| Project | Stories | Tasks | Points | Done | Remaining | % |
|---------|---------|-------|--------|------|-----------|----|
| my-api | 24 | 67 | 145 | 98 | 47 | 68% |
| my-frontend | 18 | 42 | 89 | 45 | 44 | 51% |
| my-mobile | 12 | 31 | 64 | 20 | 44 | 31% |
| **Total** | **54** | **140** | **298** | **163** | **135** | **55%** |
```

### burndown.md

Per-project burndown with ASCII progress bars:

```markdown
# Burndown

my-api:      [====================--------] 68%  (98/145 pts)
my-frontend: [===============-------------] 51%  (45/89 pts)
my-mobile:   [=========-------------------] 31%  (20/64 pts)
overall:     [=================-----------] 55%  (163/298 pts)
```

## Generating Dashboards

Dashboards are regenerated automatically by:

- **The nightly cron job** (`projectman audit --all`)
- **The `pm_burndown` MCP tool** in hub mode
- **Manually** via Python:

```python
from projectman.hub.dashboards import generate_dashboards
from projectman.config import find_project_root

root = find_project_root()
generate_dashboards(root)
```

## Reading Dashboards

Since dashboards are markdown files committed to git, you can:

- View them directly on GitHub
- Read them in any markdown viewer
- Track changes over time via git history (useful for velocity trends)
- Reference them in PRs or standup notes

## Customization

Dashboard generation happens in `projectman/hub/dashboards.py`. The output format is plain markdown, so you can modify the generation code to add:

- Sprint-specific breakdowns
- Per-assignee workload views
- Priority-based filtering
- Custom sections for your team's needs
