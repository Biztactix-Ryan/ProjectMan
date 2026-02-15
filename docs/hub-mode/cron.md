# Nightly Cron Setup

## Automated Index Rebuild

Set up a cron job to keep indexes fresh:

```bash
# crontab -e
0 2 * * * cd /path/to/hub && projectman sync && projectman audit
```

Running `projectman sync` before the audit ensures all submodules are up to date with the latest changes before checks run.

## What It Does

- Pulls latest submodule changes (via `projectman sync`)
- Rebuilds `index.yaml` for each project
- Runs 13 audit checks including epic consistency and hub doc validation
- Updates DRIFT.md with current findings
- Regenerates hub dashboards
