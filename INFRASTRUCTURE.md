# ProjectMan — Infrastructure

## Environments

<!-- REQUIRED: List all deployment environments and their purposes.
     Include: URLs, regions, scaling config, access methods. -->

| Environment | URL | Purpose | Notes |
|------------|-----|---------|-------|
| Development | | Local dev | |
| Staging | | Pre-production testing | |
| Production | | Live | |

## CI/CD

<!-- REQUIRED: Document the build and deployment pipeline.
     Include: trigger conditions, build steps, deployment strategy, rollback procedure. -->

### Build Pipeline

### Deployment Process

Release checklist (the repo root is also the Claude Code plugin, ADR-006):

1. Bump `version` in `pyproject.toml` and in `.claude-plugin/plugin.json` to the same value. Claude Code only offers a plugin update when the plugin.json version rises; `tests/test_plugin_drift.py` fails when the two differ.
2. Run `projectman build-plugin` from the repo root to re-render `agents/` and `skills/` from `src/projectman/templates`. `tests/test_plugin_drift.py` fails when the committed files drift from the templates.
3. Run `uv lock` so `uv.lock` carries the new version (the plugin's MCP server and SessionStart hook launch through `uv run --project ${CLAUDE_PLUGIN_ROOT}`).
4. Move the `[Unreleased]` notes in `CHANGELOG.md` under the new version heading and update the compare links.
5. Run the full test suite, commit ("Cut X.Y.Z: ..."), tag `vX.Y.Z`, push the branch and the tag.

### Installation

The Claude Code plugin is the supported install path (ADR-006): `/plugin marketplace add Biztactix-Ryan/ProjectMan`, then `/plugin install projectman@projectman`. It needs uv on `PATH` and a Claude Code release with plugin support; no minimum version is recorded yet (verified on Claude Code 2.1.292). Users update with `/plugin marketplace update projectman`, `/plugin update projectman@projectman` and `/reload-plugins`.

`projectman setup-claude` and `projectman refresh-skills` are deprecated: they print the plugin steps and write nothing; the old behaviour stays behind a hidden `--legacy` flag for one release. Machines installed with setup-claude move over with `projectman migrate-to-plugin` (`--dry-run` to preview), which removes the old agent and skill copies, the user-scope projectman MCP server, the `./.mcp.json` entry and the per-project pm-context.sh hook. The pipx CLI is still how `projectman init`, `web` and `migrate-to-plugin` are run from a shell. Full steps: `docs/installation.md`, "Install as a Claude Code plugin".

### Rollback Procedure

## Hosting & Services

<!-- Where is this deployed? Cloud provider, services used, regions.
     Include: compute, storage, CDN, DNS, email, etc. -->

## Monitoring & Alerting

<!-- How do you know when something is wrong?
     Include: monitoring tools, key metrics, alert channels, on-call. -->

## Environment Variables

<!-- List all required env vars and their purposes.
     DO NOT include actual secrets — just names and descriptions. -->

| Variable | Required | Description |
|----------|----------|-------------|
| | | |

## Backup & Recovery

<!-- Backup strategy, retention, recovery procedures, RTO/RPO targets. -->

---
*Last reviewed: {{ date }}*
*Update this document when infrastructure changes. The daily audit checks for staleness.*
