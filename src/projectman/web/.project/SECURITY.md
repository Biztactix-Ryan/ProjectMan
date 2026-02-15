# ProjectMan Web — Security

## Authentication

### Method

Optional token-based auth (Phase 1). Designed as a single-user local tool — no authentication required when running on localhost.

### Token/Session Management

Not implemented in Phase 1. Future: token-based auth for team/network deployments.

### Multi-factor Authentication

Not applicable for Phase 1 (local-only tool).

## Authorization

### Roles & Permissions

| Role | Permissions | Description |
|------|------------|-------------|
| Local user | Full access | Single-user mode, all operations permitted |

### Enforcement

No authorization middleware in Phase 1. All API endpoints are open when the server is running. Bind to `localhost` by default to limit exposure.

## Data Protection

### Encryption

- **In transit**: Not enforced in Phase 1 (localhost HTTP). Add TLS for network deployments.
- **At rest**: Relies on filesystem permissions. No application-level encryption.

### PII Handling

ProjectMan stores project management data (stories, tasks, epics). No user PII is collected or stored by the web layer. Assignee names in task metadata are the only person-related data.

### Data Retention

All data persists in `.project/` files until explicitly archived or deleted. Git history provides full audit trail.

## API Security

- **Rate limiting**: None in Phase 1 (local use)
- **Input validation**: Pydantic models validate all inputs (fibonacci points, valid IDs, status enums, required fields)
- **CORS**: Configured in FastAPI middleware (restrict to same-origin by default)
- **CSP headers**: To be configured

## Secrets Management

No secrets required for Phase 1. No API keys, database credentials, or external service tokens.

## Known Risks & Mitigations

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Server exposed on 0.0.0.0 without auth | Medium | Default to localhost binding; document risk of `--host 0.0.0.0` | Planned |
| No TLS on HTTP | Low | Localhost-only by default; TLS needed for network deployment | Accepted |
| No input sanitization for markdown bodies | Low | Jinja2 auto-escapes HTML in templates; markdown rendered server-side | Mitigated |

## Incident Response

Local-only tool — no incident response process required for Phase 1. For future team deployments, establish communication plan and escalation path.

---
*Last reviewed: 2026-02-15*
*Update this document when security posture changes. The daily audit checks for staleness.*