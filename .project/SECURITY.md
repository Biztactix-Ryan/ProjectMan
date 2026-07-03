# ProjectMan — Security

ProjectMan is a local-only CLI/MCP tool. It has no authentication, network services, or remote data storage by default.

## Authentication

Not applicable — ProjectMan runs locally as the current user. No multi-user auth is needed.

## Authorization

Not applicable — single-user tool with filesystem-level access control. The user has full access to their `.project/` data.

## Data Protection

### Storage

All project data is stored as plain-text markdown files in `.project/`. Data is protected by filesystem permissions and git history.

### Sensitive Data

ProjectMan does not store credentials, tokens, or PII. All data is project management metadata (titles, descriptions, points, statuses).

### Embeddings

Semantic search embeddings are cached in a local SQLite database. Contains only vector representations of story/task text — no secrets.

## API Security

### Web Dashboard

The optional web dashboard (`pm_web_start`) binds to `localhost` by default. It serves a read-write interface with no authentication — appropriate for local-only use.

**Risk**: If the host parameter is changed to `0.0.0.0`, the dashboard would be network-accessible without authentication.

### MCP Server

Communicates via stdio transport only — no network exposure.

## Secrets Management

No secrets are managed. Configuration in `.project/config.yaml` contains only project metadata.

## Known Risks & Mitigations

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Web dashboard exposed on non-localhost | Low | Default bind is localhost; document the risk | Mitigated |
| Arbitrary file paths in store operations | Low | Paths are constructed from validated IDs within `.project/` | Mitigated |

---
*Last reviewed: 2026-02-16*
*Update this document when security posture changes. The daily audit checks for staleness.*
