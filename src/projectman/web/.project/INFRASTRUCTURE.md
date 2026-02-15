# ProjectMan Web — Infrastructure

## Environments

| Environment | URL | Purpose | Notes |
|------------|-----|---------|-------|
| Development | http://localhost:8000 | Local dev | Default FastAPI dev server via Uvicorn |
| Staging | — | Not yet configured | |
| Production | — | Not yet configured | Single-user local tool for now |

## CI/CD

### Build Pipeline

Not yet configured. The web module is part of the ProjectMan monorepo, so it inherits the parent project's CI setup (pytest).

### Deployment Process

Local only for Phase 1. Run `projectman web` to start the server.

### Rollback Procedure

Git-backed storage means all data changes are tracked in version control. Rollback via `git revert` or `git checkout`.

## Hosting & Services

- **Compute**: Local machine (Uvicorn ASGI server)
- **Storage**: Local filesystem (`.project/` directory)
- **CDN**: None (static files served by FastAPI)
- **DNS**: localhost

Phase 1 is designed for single-user local use. Network deployment and cloud hosting are future considerations.

## Monitoring & Alerting

- **Health check**: FastAPI `/docs` endpoint confirms server is running
- **Audit**: `pm_audit()` provides project health checks (drift detection, consistency)
- **Logging**: Uvicorn stdout/stderr

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECTMAN_ROOT` | No | Override project root discovery (defaults to `.project/` in current directory or ancestors) |

## Backup & Recovery

- **Backup**: Git version control tracks all `.project/` file changes
- **Recovery**: `git log` + `git checkout` for any previous state
- **RTO**: Instant (git operations)
- **RPO**: Last git commit

---
*Last reviewed: 2026-02-15*
*Update this document when infrastructure changes. The daily audit checks for staleness.*