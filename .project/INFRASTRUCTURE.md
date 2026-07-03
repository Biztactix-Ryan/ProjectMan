# ProjectMan — Infrastructure

ProjectMan is a locally-installed CLI/MCP tool distributed via pip/pipx. There is no hosted infrastructure — it runs entirely on the user's machine.

## Environments

| Environment | URL | Purpose | Notes |
|------------|-----|---------|-------|
| Development | local | Local dev with `pip install -e ".[all,dev]"` | Python venv |
| Production | local | Installed via `pipx install "projectman[all]"` | User machines |

## CI/CD

### Build Pipeline

No CI/CD pipeline currently configured. Tests are run locally via `pytest`.

### Distribution

Installed directly from GitHub via pipx:
```bash
pipx install "projectman[all] @ git+https://github.com/Biztactix-Ryan/ProjectMan.git"
```

Build system: Hatchling (PEP 517 compliant).

## Hosting & Services

- **Compute**: User's local machine only
- **MCP Transport**: stdio (no network)
- **Web Dashboard**: Local FastAPI server on `localhost` (user-started, not always running)
- **Storage**: Local filesystem (`.project/` directory in the repo)
- **Embeddings Cache**: Local SQLite database

## Environment Variables

No environment variables required. All configuration lives in `.project/config.yaml`.

---
*Last reviewed: 2026-02-16*
*Update this document when infrastructure changes. The daily audit checks for staleness.*
