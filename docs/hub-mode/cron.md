# Nightly Cron Setup

## Automated Index Rebuild

Set up a cron job to keep indexes fresh and commit any pending PM changes:

```bash
# crontab -e
0 2 * * * cd /path/to/hub && projectman sync && projectman audit && projectman commit --scope all
```

Running `projectman sync` before the audit ensures all submodules are up to date with the latest changes before checks run. The final `projectman commit --scope all` commits any pending `.project/` changes across hub and all subprojects.

## What It Does

- Pulls latest submodule changes (via `projectman sync`)
- Rebuilds `index.yaml` for each project
- Runs 13 audit checks including epic consistency and hub doc validation
- Updates DRIFT.md with current findings
- Regenerates hub dashboards
- Commits all pending `.project/` changes with auto-generated messages

## Commit Scope Options

The `--scope` flag on `projectman commit` controls what gets committed:

| Scope | What it commits |
|-------|----------------|
| `all` | Hub-level `.project/` files **and** all per-project `.project/projects/{name}/` files |
| `hub` | Only hub-level `.project/` files (not per-project data) |
| `project:<name>` | Only `.project/projects/{name}/` files for a specific project |

For nightly jobs, `--scope all` is recommended to capture everything in a single pass.
