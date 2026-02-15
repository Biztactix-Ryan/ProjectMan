# Nightly Cron Setup

## Automated Index Rebuild

Set up a cron job to keep indexes fresh:

```bash
# crontab -e
0 2 * * * cd /path/to/hub && projectman audit
```

## What It Does

- Rebuilds `index.yaml` for each project
- Runs audit checks
- Updates DRIFT.md with current findings
- Regenerates hub dashboards
