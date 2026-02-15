# Auditing & Drift Detection

## Running an Audit

```
/pm-audit
```

Or via CLI: `projectman audit`

## Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Done story with incomplete tasks | Error | Story marked done but tasks aren't |
| Undecomposed story | Warning | Active/ready story with no tasks |
| Stale in-progress | Warning | Task in-progress for >14 days |
| Point mismatch | Info | Story points ≠ sum of task points |
| Thin description | Info | Description under 20 characters |

## DRIFT.md

Audit results are written to `.project/DRIFT.md`. Review this file to track project health over time.
